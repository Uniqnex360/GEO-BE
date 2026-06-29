from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.schemas import (
    ProductCreate,
    ProductUpdate,
)
from app.services import ProductService

router = APIRouter()


@router.post("/create/")
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """create product"""

    try:

        response = await ProductService.create_product(
            db=db, data=payload.model_dump(), user=user, tenant_id=user.get("tenant_id")
        )

        return {"message": "Product created successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/update/{product_id}/")
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """update product"""

    try:

        response = await ProductService.update_product(
            db=db,
            product_id=product_id,
            data=payload.model_dump(exclude_unset=True),
            user=user,
        )

        return {"message": "Product updated successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/status/{product_id}")
async def active_inactive_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """activate/deactivate Product"""

    try:

        response = await ProductService.soft_delete_product(
            db=db, product_id=product_id, user=user
        )

        return {"message": "Product status updated successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """logical delete"""

    try:

        await ProductService.delete_product(db=db, product_id=product_id, user=user)

        return {"message": "Product deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list/")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """list products"""

    try:

        products, total = await ProductService.list_products(
            db=db,
            user=user,
            tenant_id=user.get("tenant_id"),
            page=page,
            limit=limit,
            search=search,
        )

        return {
            "data": products,
            "pagination": {"page": page, "limit": limit, "total": total},
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/detail/{product_id}")
async def product_detail(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """product detail"""

    try:

        data = await ProductService.detail(db=db, product_id=product_id, tenant_id=user.get("tenant_id"), user=user)

        return data

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

