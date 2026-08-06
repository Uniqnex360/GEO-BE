from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.schemas import (
    BrandCreate,
    BrandUpdate,
)
from app.services import BrandService, start_brand_analytics

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
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
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
            sort_by=sort_by,
            sort_order=sort_order,
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


@router.post("/init_brand_analyzes/")
async def init_brand_analyzes(
    body: dict,
    user: dict = Depends(validate_jwt_token),
):
    brand_name: str = body.get("brand_name")
    country: str = body.get("country")
    website: str = body.get("website")
    extra_context: str = body.get("extra_context") or ""
    tenant_id: int = body.get("tenant_id")

    if not all([brand_name, country, website, tenant_id]):
        raise HTTPException(
            status_code=400,
            detail="brand_name, country, website, and tenant_id are required",
        )

    # Session is opened inside the stream generator so it stays alive for the
    # full NDJSON response (not tied to request-scoped Depends(get_db)).
    return StreamingResponse(
        start_brand_analytics(
            brand_name=brand_name,
            country=country,
            website=website,
            extra_context=extra_context,
            tenant_id=tenant_id,
        ),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/summary/")
async def get_brands_summary(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1),
    tenant_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, description="Search by brand name or domain"),
    model: Optional[str] = Query(
        None, description="Filter averages by AI model (e.g. GPT, CLAUDE, GEMINI)"
    ),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
):
    """
    Returns a list of brands grouped by Brand Name with all averaged metric scores across run analytics.
    """
    try:
        is_super_admin = user.get("is_super_admin", False)
        effective_tenant_id = (
            tenant_id if is_super_admin and tenant_id else user.get("tenant_id")
        )
        data, pagination = await BrandService.get_brands_analytics_summary(
            db=db,
            user=user,
            tenant_id=effective_tenant_id,
            page=page,
            limit=limit,
            search=search,
            model_filter=model,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return {
            "status": "success",
            "data": data,
            "pagination": pagination,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{brand_id}/detail/")
async def get_brand_detail(
    brand_id: int,
    tenant_id: Optional[int] = Query(None),
    model: Optional[str] = Query(
        None, description="Filter metrics by AI model enum (GPT, CLAUDE, GEMINI)"
    ),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """
    Get detailed analytics overview for a specific Brand.
    Returns averaged metric scores, AI model comparisons, latest diagnosis/recommendations,
    and complete run history.
    """
    try:
        is_super_admin = user.get("is_super_admin", False)
        effective_tenant_id = (
            tenant_id if is_super_admin and tenant_id else user.get("tenant_id")
        )

        detail = await BrandService.get_brand_analytics_detail(
            db=db,
            brand_id=brand_id,
            user=user,
            tenant_id=effective_tenant_id,
            model_filter=model,
        )

        return {
            "status": "success",
            "data": detail,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
