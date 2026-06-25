from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from app.core.config import settings

security = HTTPBearer()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:

    return pwd.hash(password)


def verify_password(plain, hashed) -> bool:
    return pwd.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    """function to get access_token"""

    payload = data.copy()

    payload["type"] = "access"
    payload["exp"] = datetime.utcnow() + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload["is_super_admin"] = data.get("is_super_admin", False)
    payload["tenant_id"] = data.get("tenant_id")

    return jwt.encode(payload, settings.SECRET_KEY, settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """function to get refresh token"""

    payload = data.copy()

    payload["type"] = "refresh"
    payload["exp"] = datetime.utcnow() + timedelta(days=7)  # refresh token longer life
    payload["is_super_admin"] = data.get("is_super_admin", False)
    payload["tenant_id"] = data.get("tenant_id")

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def validate_jwt_token(token=Depends(security)):
    try:
        payload = jwt.decode(
            token.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True},
        )

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        return payload

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")