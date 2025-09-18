import pytest

from django.contrib.auth import get_user_model
from django.test import override_settings
from ninja.testing import TestAsyncClient

from config.api import api
from app.models import Conversation, Message

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
@override_settings(
    CLERK_JWKS_URL="https://dummy.example/jwks.json",
    CLERK_ISSUER="https://dummy.example/issuer",
    CLERK_AUDIENCE="dummy_aud",
)
async def test_rest_flow_with_clerk_token(monkeypatch):
    User = get_user_model()
    user = await User.objects.acreate(username="clerk_user")

    # Monkeypatch Clerk JWT auth to accept any Bearer token and inject our user
    import common.auth as auth_module

    async def fake_clerk_call(self, request):
        request.auth = user
        return user

    monkeypatch.setattr(auth_module.AsyncClerkJWTAuth, "__call__", fake_clerk_call, raising=True)

    # Patch celery task .delay to capture args
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
    headers = {"Authorization": "Bearer testtoken"}

    # Create conversation (Authorized via Clerk token)
    payload = {
        "model": "gpt-4o-mini",
        "content": "Hallo via Clerk",
        "agent_type": "data_analysis",
        "llm_overrides": {"model": "gpt-4o-mini", "temperature": 0.2},
    }
    resp = await client.post("/v1/chat/conversations", json=payload, headers=headers)
    assert resp.status_code == 200
    conv_id = resp.json()["id"]

    # Send message (Authorized via Clerk token)
    msg_payload = {"content": "Pesan kedua dari Clerk"}
    resp2 = await client.post(f"/v1/chat/conversations/{conv_id}/messages", json=msg_payload, headers=headers)
    assert resp2.status_code == 200

    # Celery captured
    assert called["prompt"] == "Pesan kedua dari Clerk"
    assert called["conversation_id"] == str(conv_id)
    assert called["agent_type"] == "data_analysis"
    assert called["llm_overrides"]["temperature"] == 0.2


@pytest.mark.asyncio
@override_settings(
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
)
async def test_websocket_subscribe_with_clerk_token_receives_event(monkeypatch):
    User = get_user_model()
    user = await User.objects.acreate(username="clerk_ws_user")

    # Prepare a conversation for the user
    conv = await Conversation.objects.acreate(
        user=user,
        title="Conv WS",
        llm_model="gpt-x",
        agent_type="data_analysis",
        llm_overrides={"model": "gpt-x"},
    )

    # Monkeypatch WS Clerk middleware to trust token and inject our user
    import common.channels_auth as ws_auth_module

    async def fake_ws_call(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = user
        return await self.inner(scope, receive, send)

    monkeypatch.setattr(ws_auth_module.ClerkJWTAuthMiddleware, "__call__", fake_ws_call, raising=True)

    # Connect and subscribe
    try:
        from channels.testing import WebsocketCommunicator as WebSocketCommunicator
    except ImportError:
        from channels.testing import WebSocketCommunicator
    from config.asgi import application
    from app.consumers.notifications import ws_group_name
    from channels.layers import get_channel_layer

    path = f"/ws/conversations/{conv.id}/?token=testtoken"
    communicator = WebSocketCommunicator(application, path)
    connected, _ = await communicator.connect()
    assert connected is True

    # Publish an event to the conversation group
    channel_layer = get_channel_layer()
    event = {"type": "notify", "event": "test_event", "payload": {"conv": str(conv.id), "ok": True}}
    await channel_layer.group_send(ws_group_name(str(conv.id)), event)

    # Receive the pushed event from WS
    received = await communicator.receive_json_from()
    assert received["event"] == "test_event"
    assert received["payload"]["conv"] == str(conv.id)
    assert received["payload"]["ok"] is True

    await communicator.disconnect()