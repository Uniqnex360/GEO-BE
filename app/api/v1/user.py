from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.schemas import UserCreate, ListApiResponse, UserDetail, PaginationMeta
from app.services import UserService

router = APIRouter()


@router.post("/create/")
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """just creates user"""

    try:
        user = await UserService.create_user(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": user.id,
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role,
    }


@router.get("/list/", response_model=ListApiResponse[UserDetail])
async def list_user(
    user: dict = Depends(validate_jwt_token),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
):
    users, total = await UserService.list_users(
        db=db,
        is_super_admin = user.get("is_super_admin", False),
        tenant_id=user.get("tenant_id"),
        page=page,
        limit=limit,
    )

    return ListApiResponse[UserDetail](
        data=[UserDetail.model_validate(u) for u in users],
        pagination=PaginationMeta(
            page=page,
            limit=limit,
            total=total,
        ),
        message="users fetched successfully",
    )
