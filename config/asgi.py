import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from common.channels_auth import ClerkJWTAuthMiddleware

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.local')
django.setup()

from consumers.router import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        # WebSocket auth via Clerk JWT. If you still need session-based WS, wrap inside Clerk middleware or add a fallback.
        "websocket": ClerkJWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
