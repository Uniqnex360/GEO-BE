from fastapi import APIRouter

from .auth import router as auth_router
from .user import router as user_router
from .brand import router as brand_router
from .product import router as product_router
from .ai_sandbox import router as ai_sandbox
from .chat import router as chat_router
from .chat_v2 import router as chat_v2_router
from .ai_engine import router as ai_engine_router
from .citation import router as citation_router
from .competitor import router as competitor_router
from .tenant import router as tenant_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(user_router, prefix="/user", tags=["User"])
router.include_router(brand_router, prefix="/brand", tags=["Brand"])
router.include_router(product_router, prefix="/product", tags=["Product"])
router.include_router(ai_sandbox, prefix="/ai_sandbox", tags=["AI sandbox"])
router.include_router(chat_router, prefix="/chat", tags=["Chat"])
router.include_router(chat_v2_router, prefix="/chat/v2", tags=["Chat V2"])
router.include_router(ai_engine_router, prefix="/ai-engine", tags=["AI Engine"])
router.include_router(citation_router, prefix="/citation", tags=["Citation"])
router.include_router(competitor_router, prefix="/competitor", tags=["Competitor"])
router.include_router(tenant_router, prefix="/tenant", tags=["Tenant"])
