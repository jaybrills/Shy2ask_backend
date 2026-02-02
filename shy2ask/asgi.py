"""
ASGI config for shy2ask project.

Serves both HTTP and WebSocket via Daphne. HTTP uses Django; WebSocket uses
chat.routing (ChatConsumer, NotificationConsumer).
"""
import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shy2ask.settings")

# Django ASGI app for HTTP (must be called after setdefault)
django_asgi_app = get_asgi_application()

from chat.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
