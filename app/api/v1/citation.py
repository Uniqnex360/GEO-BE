from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.services import CitationService

router = APIRouter()


@router.get("/dashboard/")
async def citation_dashboard(
    db: AsyncSession = Depends(get_db), user: dict = Depends(validate_jwt_token)
):
    """returns citation dashboard data"""

    try:
        return await CitationService.get_citation_intelligence_dashboard(
            db, user, user.get("tenant_id")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
