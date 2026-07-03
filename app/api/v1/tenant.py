from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.permission import require_super_admin
from app.core.database import get_db
from app.models import Tenant, Product
from app.schemas import (
    TenantCreate,
    TenantUpdate,
    TenantResponse,
)

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


@router.put(
    "/update/{tenant_id}/",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
)
async def update_tenant(
    tenant_id: int,
    body: TenantUpdate,  # Pydantic schema with optional fields
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    """API to update an existing project/tenant"""

    # 1. Fetch the existing tenant
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. If name is changing, check for uniqueness conflicts
    if body.name and body.name != tenant.name:
        existing = await db.scalar(select(Tenant).where(Tenant.name == body.name))
        if existing:
            raise HTTPException(status_code=400, detail="Project name already exists")

    # 3. Dynamically update fields that were passed in the request body
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "website_url" and value is not None:
            value = str(value)
        setattr(tenant, key, value)

    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.delete(
    "/toggle-status/{tenant_id}/",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
)
async def toggle_tenant_status(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    """API to soft-delete (is_active=False) or restore (is_active=True) a tenant"""

    # 1. Fetch the tenant
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. Toggle the is_active status (vice-versa logic)
    tenant.is_active = not tenant.is_active

    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.get("/list/")
async def list_tenants(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    search: Optional[str] = Query(None),
    tenant_id: Optional[int] = Query(
        None, description="Super admins can filter by a specific tenant ID"
    ),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_super_admin),
):
    """List projects/tenants with pagination and admin access controls"""

    try:
        is_super_admin = user.get("is_super_admin", False)

        # --- Resolve Tenant ID Context ---
        # If super admin, pull from query params; otherwise, enforce their token identity mapping
        active_tenant_id = tenant_id if is_super_admin else user.get("tenant_id")

        # Base query with product count
        query = select(
            Tenant,
            func.count(Product.id).label("products_count"),
        ).outerjoin(
            Product,
            Product.tenant_id == Tenant.id,
        )

        # Separate count query for pagination
        count_query = select(func.count(Tenant.id))

        # --- Access Restrictions & Filter Pipeline ---
        filters = [Tenant.is_deleted.is_(False)]

        if not is_super_admin:
            if not active_tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied. No tenant association found.",
                )
            filters.append(Tenant.id == active_tenant_id)
        else:
            # If a super admin passes a specific tenant_id query param, filter down to it
            if active_tenant_id:
                filters.append(Tenant.id == active_tenant_id)

        query = query.where(*filters)
        count_query = count_query.where(*filters)

        # Search
        if search:
            search_filter = Tenant.name.ilike(f"%{search}%")
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Pagination
        offset = (page - 1) * limit

        query = (
            query.group_by(Tenant.id)
            .order_by(Tenant.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        # Execute tenant query
        result = await db.execute(query)
        rows = result.all()

        # Execute total count query
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        return {
            "data": [
                {
                    "id": tenant.id,
                    "name": tenant.name,
                    "industry": tenant.industry,
                    "description": tenant.description,
                    "website_url": tenant.website_url,
                    "countries": tenant.countries or [],
                    "is_active": tenant.is_active,
                    "status": ("Active" if tenant.is_active else "Paused"),
                    "updatedAt": (
                        tenant.updated_at.isoformat()
                        if tenant.updated_at
                        else "just now"
                    ),
                    "productsCount": products_count,
                    "visibilityScore": getattr(
                        tenant,
                        "visibility_score",
                        0,
                    ),
                    "platforms": getattr(
                        tenant,
                        "platforms",
                        ["ChatGPT", "Claude"],
                    ),
                }
                for tenant, products_count in rows
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": ((total + limit - 1) // limit),
            },
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
