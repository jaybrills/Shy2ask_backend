"""
Main Django Ninja API: docs at /docs, OpenAPI at /openapi.json.
Auth, profile, censor (text + image).
"""
from ninja import NinjaAPI

from account.api import auth_router, profile_router
from chat.censor_api import censor_router

api = NinjaAPI(
    title="Shy2Ask API",
    version="1.0.0",
    description="Auth, profile, censor engine (text + image). Censor detects illegal words, prohibited products, demands.",
    docs_url="/docs",
)

api.add_router("/auth", auth_router)
api.add_router("/profile", profile_router)
api.add_router("/censor", censor_router)