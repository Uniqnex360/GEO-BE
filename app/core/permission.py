# app/core/permissions.py

from fastapi import Depends, HTTPException, status

from app.core.security import validate_jwt_token


async def require_super_admin(
    user: dict = Depends(validate_jwt_token),
):
    """Allow only super admins"""

    if not user.get("is_super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required"
        )

    return user
