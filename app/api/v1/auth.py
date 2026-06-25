from jose import jwt, JWTError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import AccessToken, RefreshToken
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    validate_jwt_token,
)

router = APIRouter()


@router.post("/register/")
async def register(user=Depends(validate_jwt_token)):
    print("user", user)

    return {"message": "register"}


@router.post("/access_token/")
async def access_token(payload: AccessToken, db: AsyncSession = Depends(get_db)):
    """return both access & refresh token for a user"""

    # 1. get user
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 2. verify password
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3. create tokens
    access_token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "is_super_admin": user.is_super_admin,
            "tenant_id": user.tenant_id if user.tenant_id else None,
        }
    )

    refresh_token = create_refresh_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "is_super_admin": user.is_super_admin,
            "tenant_id": user.tenant_id if user.tenant_id else None,
        }
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user.role,
        "token_type": "bearer",
    }


@router.post("/refresh_token/")
async def refresh_token(
    payload: RefreshToken,
    db: AsyncSession = Depends(get_db),
):
    try:
        decoded = jwt.decode(
            payload.refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )

        print("refresh token", decoded)

        # must be refresh token
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = decoded.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # fetch latest user state from DB
        result = await db.execute(select(User).where(User.id == int(user_id)))

        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        new_access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "is_super_admin": user.is_super_admin,
                "tenant_id": user.tenant_id,
            }
        )

        # keep refresh token context consistent
        new_refresh_token = create_refresh_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "is_super_admin": user.is_super_admin,
                "tenant_id": user.tenant_id,
            }
        )

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
