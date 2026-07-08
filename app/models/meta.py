from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped

from app.models.base import BaseModel


class MetaTable(BaseModel):
    """Table to store category, industry, and taxonomy metadata."""

    __tablename__ = "meta"

    __table_args__ = (
        UniqueConstraint(
            "category_name",
            "industry_name",
            "taxonomy",
            name="uq_meta_category_industry_taxonomy",
        ),
    )

    category_name: Mapped[str] = mapped_column(String)
    industry_name: Mapped[str] = mapped_column(String)
    taxonomy: Mapped[str] = mapped_column(String)
