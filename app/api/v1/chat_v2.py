from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.security import validate_jwt_token, settings
from app.models.base import LLMModels
from app.services import run_geo_audit_stream

router = APIRouter()


class GEOAuditRequest(BaseModel):
    """V2 Flexible Request Inputs for multiple source identification types."""

    product_name: Optional[str] = Field(None, description="Name of the target product")
    product_url: Optional[str] = Field(
        None, description="Target product landing page URL"
    )
    website: Optional[str] = Field(None, description="Brand/corporate target domain")
    sku: Optional[str] = Field(None, description="Stock Keeping Unit number")
    mpn: Optional[str] = Field(None, description="Manufacturer Part Number")
    upc: Optional[str] = Field(None, description="Universal Product Code")
    country: Optional[str] = Field(None, description="Target geographical focus region")
    extra_context: Optional[str] = Field(
        None, description="Additional context parameter text"
    )
    model_choice: LLMModels = Field(
        default=LLMModels.GPT, description="Selected LLM execution engine"
    )


@router.post("/init_llm_analyzes/")
async def execute_geo_audit_endpoint(
    payload: GEOAuditRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """
    Executes a multi-model responsive audit across your 3 allowed models.
    Streams immediate progress details, and records to postgresql asynchronously.
    """
    
    data = GEOAuditRequest().model_dump() 
    print("data", type(data), data)
    tenant_id = data.get("tenant_id")
    
    return StreamingResponse(
        run_geo_audit_stream(payload, db, tenant_id), media_type="application/x-ndjson"
    )
