from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Brand(BaseModel):
    """table for brands"""

    __tablename__ = "brands"

    # foreign keys
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)

    # brand fields
    domain: Mapped[str] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(255), nullable=True)

    # relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="brands")
    products: Mapped[list["Product"]] = relationship(
        back_populates="brand",
    )
