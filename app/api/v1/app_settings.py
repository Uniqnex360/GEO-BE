from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.models import AppSettings

router = APIRouter()


@router.get("/")
async def get_settings_data(
    tenant_id: int = Query(6),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """api that show settings details"""
    try:
        query = select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        result = await db.execute(query)

        # ✅ Fetch the actual model instance out of the SQLAlchemy wrapper
        settings = result.scalar_one_or_none()

        # Optional: Return a 404 if the settings don't exist for that tenant
        if not settings:
            raise HTTPException(
                status_code=404, detail="Settings not found for this tenant"
            )

        return {"data": settings}

    except HTTPException:
        raise  # Re-raise the 404 cleanly without catching it below
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
