from typing import Optional
from pydantic import BaseModel, Field

class ProductFeatureSchema(BaseModel):
    value: str


class ProductFAQSchema(BaseModel):
    question: str
    answer: str
    sort_order: int = 0


class ProductBase(BaseModel):
    """base class for product"""

    brand_id: int

    name: str
    brand_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    product_type: Optional[str] = None
    category: Optional[str] = None

    sku: Optional[str] = None
    mpn: Optional[str] = None
    upc: Optional[str] = None
    gtin: Optional[str] = None
    ean: Optional[str] = None

    product_url: Optional[str] = None
    taxonomy: Optional[str] = None
    short_description: Optional[str] = None
    long_description: Optional[str] = None
    specifications: Optional[str] = None

    # price
    regular_price: Optional[float] = None
    sale_price: Optional[float] = None
    currency: Optional[str] = None

    # meta
    rating: Optional[float] = None
    rating_count: Optional[float] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_keywords: Optional[str] = None

    # for foreign keys
    features: list[ProductFeatureSchema] = Field(
        default_factory=list
    )
    faqs: list[ProductFAQSchema] = Field(
        default_factory=list
    )


class ProductCreate(ProductBase):
    """schema for product creation"""

    tenant_id: Optional[int]

class ProductUpdate(ProductBase):
    """schema for product update"""

    tenant_id: Optional[int]


class ProductDetail(ProductBase):
    """product detail schema"""

    id: int
