"""
Main Django Ninja API. Swagger UI at /docs, OpenAPI schema at /openapi.json.
"""
from ninja import NinjaAPI

from account.api import auth_router, profile_router
from chat.censor_api import censor_router
from chat.realtime_api import realtime_router
from chat.subscription_api import subscription_router
from .parser import FlexibleParser

# Base URL for Swagger "Try it out" (UI devs). Prefer request host so /docs works on any domain.
def _get_servers():
    return [
        {"url": "/", "description": "Current host (relative)"},
        {"url": "http://localhost:8000", "description": "Local"},
        {"url": "http://127.0.0.1:8000", "description": "Local (127)"},
    ]

api = NinjaAPI(
    title="Shy2Ask API",
    version="1.0.0",
    description=(
        "**Auth:** register, login (email + OTP verification), forgot/reset password. "
        "**Profile:** GET/PATCH /profile/me, list users (staff). "
        "**Censor:** POST /censor/text and POST /censor/image (rule-based + OpenAI). "
        "**Requests:** Create and list shy requests, manage conversations. "
        "Protected routes use **Bearer token** (Header: `Authorization: Bearer <token>`)."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
    parser=FlexibleParser(),
    openapi_extra={
        "servers": _get_servers(),
        "tags": [
            {"name": "Auth", "description": "Register, login, verify email, password reset"},
            {"name": "Profile", "description": "Current user profile and staff user list"},
            {"name": "Censor", "description": "Text and image content moderation"},
            {"name": "Requests", "description": "Real-time ShyRequests and Conversations"},
        ],
    },
)

api.add_router("/auth", auth_router)
api.add_router("/profile", profile_router)
api.add_router("/censor", censor_router)
api.add_router("/requests", realtime_router)
api.add_router("", subscription_router)  # /subscriptions (AI-based: request_updates, deal_alerts)
