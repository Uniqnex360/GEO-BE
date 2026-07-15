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
        data = payload.model_dump()

        is_super_admin = user.get("is_super_admin")
        tenant_id = data.get("tenant_id") if is_super_admin else user.get("tenant_id")

        response = await ProductService.create_product(
            db=db, data=payload.model_dump(), user=user, tenant_id=tenant_id
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
    tenant_id: Optional[int] = Query(
        None, description="Super admins can filter by a specific tenant ID"
    ),
    brand: Optional[str] = Query(None, description="Comma-separated list of brands"),
):
    """list products"""

    is_super_admin = user.get("is_super_admin", False)
    active_tenant_id = tenant_id if is_super_admin else user.get("tenant_id")

    try:

        products, total, tenant_states = await ProductService.list_products(
            db=db,
            user=user,
            tenant_id=active_tenant_id,
            page=page,
            limit=limit,
            search=search,
            brand=brand
        )

        return {
            "data": products,
            "tenant_states": tenant_states,
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

        data = await ProductService.detail(
            db=db, product_id=product_id, tenant_id=user.get("tenant_id"), user=user
        )

        return data

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/detail/v2/{product_id}")
async def product_detail(
    product_id: int,
    tab: str = Query(
        "visibility", description="Target specific dashboard tab dataset dynamically"
    ),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """Product detail version 2 - Dynamically filtered by active tab state"""
    try:
        data = await ProductService.product_detail_v2(
            db=db,
            product_id=product_id,
            tenant_id=user.get("tenant_id"),
            user=user,
            tab=tab.lower().strip(),
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
