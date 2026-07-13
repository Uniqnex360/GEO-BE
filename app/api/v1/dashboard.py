
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.services import TenantDashboardService

router = APIRouter()



@router.get("/")
async def meta_brand_list(
    tenant_id: int = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """api that lists all brands for a tenant"""

    try:
        is_super_admin = user.get("is_super_admin")
        tenant_id = tenant_id if is_super_admin else user.get("tenant_id")
        brands = await TenantDashboardService.get_overall_dashboard(
            db=db,
            user=user,
            tenant_id=tenant_id,
        )
        return brands
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
