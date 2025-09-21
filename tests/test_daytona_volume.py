import json
import types
import sys
import os
import uuid
import contextlib

import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from ninja.testing import TestAsyncClient
from config.api import api


def test_admin_list_display_includes_daytona_fields():
    from django.contrib import admin
    from app.models import Conversation

    # Ensure model is registered in admin and list_display contains fields
    assert Conversation in admin.site._registry
    model_admin = admin.site._registry[Conversation]
    fields = tuple(model_admin.list_display)
    for f in ("title", "llm_model", "daytona_volume_id", "daytona_volume_name"):
        assert f in fields, f"Admin list_display should include {f}"


class _DaytonaVolumesStub:
    def __init__(self, record):
        self._record = record

    # Creation path used by our API logic
    def create(self, name=None, size=None, **kwargs):
        # record inputs for assertion
        self._record["create_called_with"] = {"name": name, "size": size, **kwargs}
        # return a structure that the code can parse for id/name
        return {"id": "vol-123", "name": name or "vol-123"}

    # Deletion path used by cleanup signal
    def delete(self, id=None, *args, **kwargs):
        self._record["delete_called_with"] = id or kwargs.get("id")

    # Alternative naming used in some SDK variants
    def remove(self, id=None, *args, **kwargs):
        self._record["remove_called_with"] = id or kwargs.get("id")


class _DaytonaStub:
    def __init__(self, _config, record):
        self._config = _config
        self._record = record
        self.volumes = _DaytonaVolumesStub(record)
        # also provide nested variant "volume.create" expected by our code fallback
        self.volume = self.volumes

    # Alternative top-level method
    def create_volume(self, name=None, size=None, **kwargs):
        return self.volumes.create(name=name, size=size, **kwargs)


class _DaytonaConfigStub:
    def __init__(self, api_key=None, api_url=None, target=None):
        self.api_key = api_key
        self.api_url = api_url
        self.target = target


@pytest.fixture()
def daytona_stub(monkeypatch):
    """Monkeypatch a minimal 'daytona' SDK into sys.modules and set required env vars."""
    record = {}

    mod = types.ModuleType("daytona")
    # Expose Daytona and DaytonaConfig classes like the SDK
    def Daytona(cfg):
        # record the config used to initialize
        record["config"] = {
            "api_key": getattr(cfg, "api_key", None),
            "api_url": getattr(cfg, "api_url", None),
            "target": getattr(cfg, "target", None),
        }
        return _DaytonaStub(cfg, record)

    mod.Daytona = Daytona
    mod.DaytonaConfig = _DaytonaConfigStub

    monkeypatch.setitem(sys.modules, "daytona", mod)

    # Ensure env vars exist to trigger provisioning branch
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    monkeypatch.setenv("DAYTONA_API_URL", "https://api.daytona.local")
    monkeypatch.setenv("DAYTONA_TARGET", "local")

    yield record

    # Cleanup
    with contextlib.suppress(KeyError):
        del sys.modules["daytona"]


@pytest.fixture()
def auth_client():
    User = get_user_model()
    # Ensure a user exists
    user = User.objects.filter(username="testuser").first()
    if not user:
        user = User(username="testuser", email="test@example.com")
        user.set_password("pass12345!")
        user.save()

    client = Client()
    client.force_login(user)
    return client


@pytest.fixture(scope="module")
def ninja_client():
    return TestAsyncClient(api)


@pytest.mark.asyncio
async def test_create_conversation_persists_daytona_volume_fields(monkeypatch, daytona_stub, ninja_client):
    # Run Celery tasks eagerly in tests so background provisioning executes synchronously
    from celery import current_app as celery_app
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    # Stub agent classes used inside Celery task to avoid real network/LLM calls
    import app.tasks as tasks_module

    class _DummyAgent:
        @classmethod
        async def create(cls, **kwargs):
            return cls()

        async def run(self, prompt):
            return "ok"

        async def cleanup(self):
            return None

    monkeypatch.setattr(tasks_module, "Manus", _DummyAgent, raising=False)
    monkeypatch.setattr(tasks_module, "DataAnalysis", _DummyAgent, raising=False)

    # Prepare authenticated user via CombinedAuth monkeypatch
    User = get_user_model()
    user = await User.objects.acreate(username="tester_daytona")

    import common.auth as auth_module

    async def fake_auth_call(self, request):
        request.auth = user
        return user

    monkeypatch.setattr(auth_module.CombinedAuth, "__call__", fake_auth_call, raising=False)

    # Create conversation via API with required payload
    payload = {
        "model": "gpt-4o-mini",
        "content": "Hello Dayt",
        "agent_type": "data_analysis",
        "llm_overrides": {"temperature": 0.1},
    }
    resp = await ninja_client.post("/v1/chat/conversations", json=payload)
    assert resp.status_code in (200, 201), resp.content
    data = resp.json()

    # Validate that server returned an id and volume fields persisted
    conv_id = data.get("id") or data.get("conversation_id")
    assert conv_id, f"Unexpected response payload: {data}"

    from app.models import Conversation

    conv = await Conversation.objects.aget(id=conv_id)
    assert (conv.daytona_volume_id or conv.daytona_volume_name), "Conversation did not persist any Daytona volume identifier"

    # Also assert our stub was invoked with config
    assert daytona_stub.get("config"), "Daytona client was not constructed"


@pytest.mark.asyncio
async def test_volume_info_endpoint_returns_volume(monkeypatch, ninja_client):
    from app.models import Conversation
    from app.config import config

    # Prepare authenticated user via CombinedAuth monkeypatch
    User = get_user_model()
    user = await User.objects.acreate(username="tester_volinfo")

    import common.auth as auth_module

    async def fake_auth_call(self, request):
        request.auth = user
        return user

    monkeypatch.setattr(auth_module.CombinedAuth, "__call__", fake_auth_call, raising=False)

    # Create a conversation for that user with preset volume fields
    conv = await Conversation.objects.acreate(
        user=user,
        title="Vol Test",
        daytona_volume_id="vol-xyz",
        daytona_volume_name="conv-vol-test",
    )

    url = f"/v1/chat/conversations/{conv.id}/volume-info"
    resp = await ninja_client.get(url)
    assert resp.status_code == 200, resp.content
    data = resp.json()

    assert data["conversation_id"] == str(conv.id)
    assert data["daytona_volume_id"] == "vol-xyz"
    assert data["daytona_volume_name"] == "conv-vol-test"
    assert data["work_dir"] == config.sandbox.work_dir


def test_cleanup_signal_deletes_volume_when_enabled(monkeypatch):
    from celery import current_app as celery_current_app
    # Pastikan task Celery dijalankan secara sinkron saat test
    celery_current_app.conf.task_always_eager = True
    celery_current_app.conf.task_eager_propagates = True

    from app.models import Conversation

    # Enable cleanup behavior
    monkeypatch.setenv("DAYTONA_DELETE_VOLUME_ON_CONVERSATION_DELETE", "1")

    # Prepare SDK stub capturing deletion
    record = {}

    import types, sys
    mod = types.ModuleType("daytona")

    class _DaytonaVolumesStub:
        def __init__(self, record):
            self._record = record
        def delete(self, id=None, *args, **kwargs):
            self._record["delete_called_with"] = id or kwargs.get("id")
        def remove(self, id=None, *args, **kwargs):
            self._record["remove_called_with"] = id or kwargs.get("id")

    class _DaytonaStub:
        def __init__(self, cfg, record):
            self.volumes = _DaytonaVolumesStub(record)
            self.volume = self.volumes

    class _DaytonaConfigStub:
        def __init__(self, api_key=None, api_url=None, target=None):
            pass

    def Daytona(cfg):
        return _DaytonaStub(cfg, record)

    mod.Daytona = Daytona
    mod.DaytonaConfig = _DaytonaConfigStub

    monkeypatch.setitem(sys.modules, "daytona", mod)

    # Create a conversation with a volume id and then delete it
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.filter(username="cleanup").first()
    if not user:
        user = User(username="cleanup", email="cleanup@example.com")
        user.set_password("pass12345!")
        user.save()

    conv = Conversation.objects.create(user=user, daytona_volume_id="vol-delete-me")
    conv.delete()

    # Our stub should have received a deletion call (executed via Celery eager)
    deleted_id = record.get("delete_called_with") or record.get("remove_called_with")
    assert deleted_id == "vol-delete-me"