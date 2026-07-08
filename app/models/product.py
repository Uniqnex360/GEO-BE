from typing import Optional
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import ForeignKey, String, Text, Float, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, LLMModels


class ProductFeature(BaseModel):
    """Product features"""

    __tablename__ = "product_features"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    # relationship
    product: Mapped["Product"] = relationship(back_populates="features")


class ProductFAQ(BaseModel):
    """Product FAQ"""

    __tablename__ = "product_faqs"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # relationship
    product: Mapped["Product"] = relationship(back_populates="faqs")


class Product(BaseModel):
    """table for products"""

    __tablename__ = "products"

    # foreign keys
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)

    # product fields - Altered to JSONB to store {value, score, tips}
    name: Mapped[dict] = mapped_column(String, nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(255), nullable=True)
    model_number: Mapped[str] = mapped_column(String(255), nullable=True)
    product_type: Mapped[str] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(255), nullable=True)

    model_choice: Mapped[LLMModels] = mapped_column(
        SQLEnum(
            LLMModels, values_callable=lambda x: [e.value for e in x], name="llmmodels"
        ),
        nullable=False,
        default=LLMModels.GPT,
    )

    sku: Mapped[str] = mapped_column(String(255), nullable=True)
    mpn: Mapped[str] = mapped_column(String(255), nullable=True)
    upc: Mapped[str] = mapped_column(String(255), nullable=True)
    gtin: Mapped[str] = mapped_column(String(255), nullable=True)
    ean: Mapped[str] = mapped_column(String(255), nullable=True)

    product_url: Mapped[str] = mapped_column(Text, nullable=True)
    texonomy: Mapped[str] = mapped_column(Text, nullable=True)
    short_description: Mapped[str] = mapped_column(Text, nullable=True)
    long_description: Mapped[str] = mapped_column(Text, nullable=True)
    specifications: Mapped[str] = mapped_column(Text, nullable=True)

    # analysis specific fields to catch JSON details
    description_analysis: Mapped[dict] = mapped_column(JSONB, nullable=True)
    features_analysis: Mapped[dict] = mapped_column(JSONB, nullable=True)
    attributes_analysis: Mapped[dict] = mapped_column(JSONB, nullable=True)
    assets: Mapped[dict] = mapped_column(JSONB, nullable=True)
    faqs_analysis: Mapped[dict] = mapped_column(JSONB, nullable=True)
    reviews_analysis: Mapped[dict] = mapped_column(JSONB, nullable=True)

    # price
    regular_price: Mapped[float] = mapped_column(Float, nullable=True)
    sale_price: Mapped[float] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(255), nullable=True)

    # meta
    rating: Mapped[float] = mapped_column(Float, nullable=True)
    rating_count: Mapped[float] = mapped_column(Float, nullable=True)
    meta_title: Mapped[dict] = mapped_column(
        String, nullable=True
    )  # Acts as product_title dict
    meta_description: Mapped[str] = mapped_column(Text, nullable=True)
    meta_keywords: Mapped[dict] = mapped_column(
        String, nullable=True
    )  # Catch JSON list, score, tips

    no_of_faqs: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None
    )
    no_of_reviews: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None
    )

    # relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="products")
    brand: Mapped["Brand"] = relationship(back_populates="products")
    features: Mapped[list["ProductFeature"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    faqs: Mapped[list["ProductFAQ"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    chats = relationship("Chat", back_populates="product")
