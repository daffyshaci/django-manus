from channels.generic.websocket import AsyncJsonWebsocketConsumer
from .notifications import ws_group_name

class ConversationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group = ws_group_name(self.conversation_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def notify(self, event):
        # event = {"type":"notify", "event": "...", "payload": {...}}
        await self.send_json(event)
