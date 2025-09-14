import json
import logging
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async  # Import yang lebih eksplisit
from asgiref.sync import async_to_sync


class DefaultConsumer(AsyncWebsocketConsumer):
    async def connect(self) -> None:
        await self.accept()

    async def disconnect(self) -> None:
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        logging.info(f"WebSocket disconnected for room {self.room_group_name}")
