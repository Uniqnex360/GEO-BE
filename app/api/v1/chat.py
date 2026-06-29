from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.config import settings
from app.core.security import validate_jwt_token
from app.services import ChatService

router = APIRouter()


@router.post("/init_llm_analyzes/")
async def init_llm_analyzes(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):

    print("body", body)
    """
    example body
    {
    'product_name': 'test', 
    'product_url': 'https://www.chmarine.com/international-cruiser-250-antifoul-3L/', 
    'extra_context': 'test', 
    'model': 'gpt-5-nano'}
    """

    return StreamingResponse(
        ChatService(openai_api_key=settings.OPENAI_API_KEY).start_analysis(
            db, body, user.get("tenant_id")
        ),
        media_type="application/x-ndjson",
    )
