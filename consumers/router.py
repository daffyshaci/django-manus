from django.urls import re_path, path

from .default_consumers import DefaultConsumer
from app.consumers.agent_consumers import ConversationConsumer
# from core.chat.tasks.consumers import ConversationConsumer


websocket_urlpatterns = [
    re_path(r'ws/default/$', DefaultConsumer.as_asgi()),
    re_path(r"ws/conversations/(?P<conversation_id>[^/]+)/$", ConversationConsumer.as_asgi()),
    # re_path(r"ws/conversations/(?P<conversation_id>[^/]+)/$", ConversationConsumer.as_asgi()),
]
