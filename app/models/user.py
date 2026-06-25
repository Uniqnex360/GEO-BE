from enum import Enum

from sqlalchemy import String, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class UserRoleEnum(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class User(BaseModel):
    """user model for entire app"""

    __tablename__ = "users"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(512), nullable=False)

    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)

    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    role: Mapped[UserRoleEnum] = mapped_column(
        SQLEnum(UserRoleEnum), default=UserRoleEnum.MEMBER, nullable=False
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
