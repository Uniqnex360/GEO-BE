from typing import Any, Optional
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, LLMModels


class Brand(BaseModel):
    """table for brands"""

    __tablename__ = "brands"

    # foreign keys
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    last_updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    deleted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # brand fields
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    competitor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="brands")
    products: Mapped[list["Product"]] = relationship(
        back_populates="brand",
    )
    brand_analytics: Mapped[list["BrandAnalytic"]] = relationship(
        back_populates="brand",
        cascade="all, delete-orphan",
    )


class BrandAnalytic(BaseModel):
    """table that holds data for brand analytics"""

    __tablename__ = "brand_analytics"

    # foreign keys
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)

    # relationships
    brand: Mapped["Brand"] = relationship(back_populates="brand_analytics")

    # float fields
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # strings
    sentiment: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Model Enum Implementation
    model_choice: Mapped[LLMModels] = mapped_column(
        PG_ENUM(LLMModels, name="llmmodels", create_type=False),
        nullable=False,
        default=LLMModels.GPT,
    )

    # dimension fields (store the weighted scores)
    mention_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    citation_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    share_of_voice_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    product_coverage_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    category_coverage_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    knowledge_graph_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    authority_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # diagnosis & recommendations
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )

    # raw structured collections (JSON columns)
    categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    competitors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    generated_prompts: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    prompt_factory: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    dimensions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # raw metric values
    share_of_voice_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    share_of_voice_raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    product_coverage_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    product_coverage_raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    category_coverage_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    category_coverage_raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    knowledge_graph_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    knowledge_graph_raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    authority_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    authority_raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
