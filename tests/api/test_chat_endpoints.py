import json
import pytest

from django.contrib.auth import get_user_model
from ninja.testing import TestAsyncClient

from config.api import api
from app.models import Conversation, Message

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_create_conversation_and_send_message_triggers_celery(monkeypatch):
    User = get_user_model()

    # create user
    user = await User.objects.acreate(username="tester")

    # patch auth handler to inject user into request
    import common.auth as auth_module

    async def fake_auth_call(self, request):
        request.auth = user
        return user

    monkeypatch.setattr(auth_module.AsyncSessionAuth, "__call__", fake_auth_call, raising=True)

    # patch celery task .delay to capture args
    called = {}

    def fake_delay(prompt, conv_id, agent_type=None, llm_overrides=None, agent_kwargs=None):
        called.update({
            "prompt": prompt,
            "conversation_id": conv_id,
            "agent_type": agent_type,
            "llm_overrides": llm_overrides,
        })
        return None

    from app.tasks import run_manus_agent
    monkeypatch.setattr(run_manus_agent, "delay", fake_delay)

    client = TestAsyncClient(api)

    # create conversation
    payload = {
        "model": "gpt-4o-mini",
        "content": "Halo pertama",
        "agent_type": "data_analysis",
        "llm_overrides": {"model": "gpt-4o-mini", "temperature": 0.1}
    }
    resp = await client.post("/v1/chat/conversations", json=payload)
    assert resp.status_code == 200
    conv_id = resp.json()["id"]

    # send message
    msg_payload = {"content": "Pesan kedua"}
    resp2 = await client.post(f"/v1/chat/conversations/{conv_id}/messages", json=msg_payload)
    assert resp2.status_code == 200

    # check celery captured
    assert called["prompt"] == "Pesan kedua"
    assert called["conversation_id"] == str(conv_id)
    assert called["agent_type"] == "data_analysis"
    assert called["llm_overrides"]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_trigger_first_message(monkeypatch):
    User = get_user_model()
    user = await User.objects.acreate(username="tester2")

    # patch auth to inject user
    import common.auth as auth_module

    async def fake_auth_call(self, request):
        request.auth = user
        return user

    monkeypatch.setattr(auth_module.AsyncSessionAuth, "__call__", fake_auth_call, raising=True)

    # patch task delay
    captured = {}

    def fake_delay(prompt, conv_id, agent_type=None, llm_overrides=None, agent_kwargs=None):
        captured.update({
            "prompt": prompt,
            "cid": conv_id,
            "agent_type": agent_type,
            "llm_overrides": llm_overrides,
        })

    from app.tasks import run_manus_agent
    monkeypatch.setattr(run_manus_agent, "delay", fake_delay)

    # create conversation and initial message
    conv = await Conversation.objects.acreate(user=user, title="t", llm_model="gpt-x", agent_type="data_analysis", llm_overrides={"model": "gpt-x"})
    await Message.objects.acreate(conversation=conv, role=Message.ROLE.USER, content="First")

    client = TestAsyncClient(api)
    resp = await client.post(f"/v1/chat/conversations/{conv.id}/trigger-first-message")
    assert resp.status_code == 200

    # ensure prompt is the earliest user message and llm_overrides passed
    assert captured["prompt"] == "First"
    assert captured["cid"] == str(conv.id)
    assert captured["agent_type"] == "data_analysis"
    assert captured["llm_overrides"]["model"] == "gpt-x"