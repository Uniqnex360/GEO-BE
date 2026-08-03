from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.services import CitationService

router = APIRouter()


@router.get("/dashboard/")
async def citation_dashboard(
    db: AsyncSession = Depends(get_db),
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(validate_jwt_token),
):
    """returns citation dashboard data"""

    try:
        print("tenant_id", tenant_id)
        return await CitationService.get_citation_intelligence_dashboard(
            db, user, tenant_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
