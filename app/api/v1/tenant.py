from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.permission import require_super_admin
from app.core.database import get_db
from app.models import Tenant
from app.schemas import TenantCreate, TenantResponse

router = APIRouter()


@router.post(
    "/create/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    """API to create project/tenant"""

    # check existing tenant/project name
    from sqlalchemy import select

    existing = await db.scalar(select(Tenant).where(Tenant.name == body.name))

    if existing:
        raise HTTPException(status_code=400, detail="Project already exists")

    tenant = Tenant(
        name=body.name,
        industry=body.industry,
        website_url=str(body.website_url) if body.website_url else None,
        description=body.description,
        countries=body.countries,
    )

    db.add(tenant)

    await db.commit()
    await db.refresh(tenant)

    return tenant


@router.get("/list/")
async def list_tenants(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    """List projects/tenants"""

    try:
        tenant_id = user.get("tenant_id")
        is_super_admin = user.get("is_super_admin", False)

        query = select(Tenant)
        count_query = select(func.count(Tenant.id))

        # normal users can only see their own tenant
        if not is_super_admin:
            filters = [
                Tenant.id == tenant_id,
                Tenant.is_deleted.is_(False),
            ]

            query = query.where(*filters)
            count_query = count_query.where(*filters)

        else:
            query = query.where(Tenant.is_deleted.is_(False))

            count_query = count_query.where(Tenant.is_deleted.is_(False))

        # search
        if search:
            search_filter = Tenant.name.ilike(f"%{search}%")

            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # pagination
        offset = (page - 1) * limit

        query = query.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)

        result = await db.execute(query)
        tenants = result.scalars().all()

        total_result = await db.execute(count_query)
        total = total_result.scalar()

        return {
            "data": [
                {
                    "id": tenant.id,
                    "name": tenant.name,
                    "industry": tenant.industry,
                    "website_url": tenant.website_url,
                    "description": tenant.description,
                    "countries": tenant.countries or [],
                    "is_active": tenant.is_active,
                    "created_at": tenant.created_at,
                    "updated_at": tenant.updated_at,
                }
                for tenant in tenants
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": ((total + limit - 1) // limit),
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
