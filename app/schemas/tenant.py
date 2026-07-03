# app/schemas/tenant.py

from pydantic import BaseModel, Field
from typing import Optional


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    industry: Optional[str] = Field(None, max_length=255)
    website_url: Optional[str] = None
    description: Optional[str] = None
    countries: list[str] = Field(default_factory=list)

class TenantUpdate(BaseModel):
    id: int 
    name: str = Field(..., min_length=2, max_length=255)
    industry: Optional[str] = Field(None, max_length=255)
    website_url: Optional[str] = None
    description: Optional[str] = None
    countries: list[str] = Field(default_factory=list)


class TenantResponse(BaseModel):
    id: int
    name: str
    industry: Optional[str]
    website_url: Optional[str]
    description: Optional[str]
    countries: list[str]

    model_config = {"from_attributes": True}
