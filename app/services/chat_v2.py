from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import validate_jwt_token, settings
from app.services.chat_v2 import ChatV2Service

router = APIRouter()


@router.post("/init_llm_analyzes/")
async def init_llm_analyzes(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """
    Initializes systemic optimization discovery runs. Returns an
    NDJSON application stream pipeline mapping diagnostic parameters.
    """
    # Safe lookup extraction pattern for mapping targeted tenant identity
    tenant_id = user.get("tenant_id")

    # Initialize service instance and pass the generation generator to response engine
    service = ChatV2Service(openai_api_key=settings.OPENAI_API_KEY)

    return StreamingResponse(
        service.start_analysis(db, body, tenant_id),
        media_type="application/x-ndjson",
    )
