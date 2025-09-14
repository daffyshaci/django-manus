from ninja import NinjaAPI
# from core.chat.api import router as chat_router
# from core.ai.api import router as ai_router
from app.api import router as app_router


# Initialize main API instance
api = NinjaAPI(
    title="Larasana v3 API",
    version="1.0.0",
    description="Comprehensive API for Larasana v3 platform including chat, AI, billing, and user management",
    docs_url="/docs/",
    openapi_url="/openapi.json"
)

# # Add chat router with versioning
api.add_router("/v1/chat", app_router, tags=["chat"])
# # Add AI router with versioning
# api.add_router("/v1/ai", ai_router, tags=["ai"])
