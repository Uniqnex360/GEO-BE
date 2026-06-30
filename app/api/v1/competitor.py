from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.services import CompetitorService

router = APIRouter()


@router.get("/dashboard/")
async def competitor_dashboard(
    db: AsyncSession = Depends(get_db), user: dict = Depends(validate_jwt_token)
):
    """returns competitor dashboard data"""

    try:
        return await CompetitorService.get_dashboard(
            db, user, user.get("tenant_id")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
