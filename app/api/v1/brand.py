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
    BrandCreate,
    BrandUpdate,
)
from app.services import BrandService

router = APIRouter()


@router.post("/create/")
async def create_brand(
    payload: BrandCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """create brand"""

    try:
        is_super_admin = user.get("is_super_admin")
        data = payload.model_dump()
        print("data", data)
        tenant_id = data.get("tenant_id") if is_super_admin else user.get("tenant_id")
        print("tenant id", tenant_id)
        response = await BrandService.create_brand(
            db=db, data=data, user=user, tenant_id=tenant_id
        )

        return {"message": "Brand created successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/update/{brand_id}/")
async def update_brand(
    brand_id: int,
    payload: BrandUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """update brand"""

    try:
        response = await BrandService.update_brand(
            db=db,
            brand_id=brand_id,
            data=payload.model_dump(exclude_unset=True),
            user=user,
        )

        return {"message": "Brand updated successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/status/{brand_id}")
async def active_inactive_brand(
    brand_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """activate/deactivate brand"""

    try:

        response = await BrandService.soft_delete_brand(
            db=db, brand_id=brand_id, user=user
        )

        return {"message": "Brand status updated successfully", "data": response}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete/{brand_id}")
async def delete_brand(
    brand_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """logical delete"""

    try:

        await BrandService.delete_brand(db=db, brand_id=brand_id, user=user)

        return {"message": "Brand deleted successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list/")
async def list_brands(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1),
    tenant_id: int = Query(None),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """list brands"""

    try:

        is_super_admin = user.get("is_super_admin")
        tenant_id = tenant_id if is_super_admin else user.get("tenant_id")

        brands, total = await BrandService.list_brands(
            db=db,
            user=user,
            tenant_id=tenant_id,
            page=page,
            limit=limit,
            search=search,
        )

        return {
            "data": brands,
            "pagination": {"page": page, "limit": limit, "total": total},
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/meta-list/")
async def meta_brand_list(
    tenant_id: int = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """api that lists all brands for a tenant"""

    try:
        is_super_admin = user.get("is_super_admin")
        tenant_id = tenant_id if is_super_admin else user.get("tenant_id")
        brands = await BrandService.meta_list(
            db=db,
            user=user,
            tenant_id=tenant_id,
        )
        return brands
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
