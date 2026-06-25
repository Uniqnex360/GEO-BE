from fastapi import APIRouter

from .auth import router as auth_router
from .user import router as user_router
from .brand import router as brand_router
from .product import router as product_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(user_router, prefix="/user", tags=["User"])
router.include_router(brand_router, prefix="/brand", tags=["Brand"])
router.include_router(product_router, prefix="/product", tags=["Product"])
