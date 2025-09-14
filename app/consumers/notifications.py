
from typing import Any
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def ws_group_name(conversation_id: str) -> str:
    return f"conv_{conversation_id}"


def send_notification(conversation_id: str, event: str, payload: dict[str, Any]) -> None:
    """
    Kirim ke group WebSocket: {type: "notify", event: "...", payload: {...}}
    Sinkron (aman dipanggil dari konteks non-async seperti Celery task).
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        ws_group_name(str(conversation_id)),
        {"type": "notify", "event": event, "payload": payload},
    )


async def send_notification_async(conversation_id: str, event: str, payload: dict[str, Any]) -> None:
    """
    Versi async untuk dipanggil dari coroutine (avoid async_to_sync di dalam event loop).
    """
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        ws_group_name(str(conversation_id)),
        {"type": "notify", "event": event, "payload": payload},
    )


# Alias agar sesuai dengan penamaan yang diminta (optional)

def send_notifications(conversation_id: str, event: str, payload: dict[str, Any]) -> None:
    send_notification(conversation_id, event, payload)
