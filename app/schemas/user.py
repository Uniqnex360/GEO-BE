from typing import Optional
from pydantic import BaseModel, EmailStr
from app.models import UserRoleEnum

class TenantDetail(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    tenant_id: int
    email: EmailStr
    password: str
    timezone: str = "UTC"
    is_super_admin: bool = False
    role: UserRoleEnum = UserRoleEnum.MEMBER


class UserDetail(BaseModel):
    id: int
    email: str
    role: str
    tenant: Optional[TenantDetail] = None

    class Config:
        from_attributes = True
