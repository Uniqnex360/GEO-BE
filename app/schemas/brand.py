from typing import Optional
from pydantic import BaseModel


class BrandBase(BaseModel):
    """Base class for brand"""

    domain: str
    name: str
    industry: str
    country: str
    competitor: str


class BrandCreate(BrandBase):
    """Schema for brand creation"""

    pass


class BrandUpdate(BaseModel):
    """Schema for brand update"""

    id: int
    domain: Optional[str] = None
    name: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None


class BrandDetail(BrandBase):
    """Schema for brand details"""

    id: int
