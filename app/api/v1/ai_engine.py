from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.services import AIEngineService

router = APIRouter()


@router.get("/list/")
async def list_metrics(
    db: AsyncSession = Depends(get_db), user: dict = Depends(validate_jwt_token)
):
    """returns requried data for the ai engine tab"""

    try:
        return await AIEngineService.get_detail(db, user.get("tenant_id"), user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
