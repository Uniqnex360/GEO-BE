from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


from app.core.database import get_db
from app.core.security import validate_jwt_token, settings
from app.models.base import LLMModels
from app.models.product import Product
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
    tenant_id: int


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

    print("payload:", payload.model_dump())

    return StreamingResponse(
        run_geo_audit_stream(
            payload=payload, db=db, tenant_id=payload.tenant_id, user_id=user.get("id")
        ),
        media_type="application/x-ndjson",
    )


MAX_GENERATED_VERSIONS = 3

VALID_CRITERIA = {
    "title",
    "description",
    "features",
    "attributes",
    "assets",
    "pricing",
}


llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
    api_key=settings.OPENAI_API_KEY,
)


@router.post("/generate-single-recommandation/")
async def generate_single_recommandataion(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    print("payload:", payload)

    # ============================================================
    # 1. PAYLOAD
    # ============================================================

    criterion = payload.get("criterion")
    recommendations = payload.get("recommendations") or {}
    versions = payload.get("versions") or []
    

    if criterion not in VALID_CRITERIA:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid criterion: {criterion}",
        )

    if not isinstance(versions, list):
        raise HTTPException(
            status_code=400,
            detail="versions must be a list",
        )

    if len(versions) >= MAX_GENERATED_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=(f"Maximum {MAX_GENERATED_VERSIONS} " f"versions are allowed"),
        )

    # ============================================================
    # 2. GET PRODUCT
    # ============================================================
    #
    # Change this according to where your product_id comes from.
    #
    # Example:
    # product_id = payload.get("product_id")
    #
    # or:
    # product_id = user.get("product_id")
    #
    # ============================================================

    product_id = payload.get("product_id")

    if not product_id:
        raise HTTPException(
            status_code=400,
            detail="product_id is required",
        )

    result = await db.execute(select(Product).where(Product.id == product_id))

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    # ============================================================
    # 3. PRODUCT DATA
    # ============================================================

    product_data = {
        "name": product.name,
        "product_name_ai": product.product_name_ai,
        "brand_name": product.brand_name,
        "manufacturer": product.manufacturer,
        "model_number": product.model_number,
        "product_type": product.product_type,
        "category": product.category,
        "sku": product.sku,
        "mpn": product.mpn,
        "upc": product.upc,
        "gtin": product.gtin,
        "ean": product.ean,
        "product_url": product.product_url,
        "texonomy": product.texonomy,
        "short_description": product.short_description,
        "long_description": product.long_description,
        "features_ai": product.features_ai,
        "current_ai_features": product.current_ai_features,
        "description_ai": product.description_ai,
        "specifications": product.specifications,
        "assets": product.assets,
        "regular_price": product.regular_price,
        "sale_price": product.sale_price,
        "currency": product.currency,
        "rating": product.rating,
        "rating_count": product.rating_count,
        "meta_title": product.meta_title,
        "meta_description": product.meta_description,
        "meta_keywords": product.meta_keywords,
        "actual_content": product.actual_content,
    }

    # ============================================================
    # 4. PREVIOUS VERSIONS
    # ============================================================

    previous_versions = "\n".join(
        f"{index + 1}. {version}" for index, version in enumerate(versions)
    )

    if not previous_versions:
        previous_versions = "None"

    # ============================================================
    # 5. LLM RECOMMENDATIONS
    # ============================================================

    chatgpt_recommendations = recommendations.get("chatgpt") or []

    gemini_recommendations = recommendations.get("gemini") or []

    claude_recommendations = recommendations.get("claude") or []

    # ============================================================
    # 6. PROMPT
    # ============================================================

    system_prompt = """
You are a product content generation assistant.

Generate exactly ONE final copy-pastable value
for the requested product criterion.

IMPORTANT:

- Return ONLY the final content.
- Do not return explanations.
- Do not return analysis.
- Do not return multiple options.
- Do not return bullets unless the criterion
  itself requires a list.
- Do not use action language.
- Do not say "Update", "Change", "Improve",
  "Standardize", "Consider", etc.
- Do not include labels such as "Title:".
- Do not invent product information.
- Use the product data as the source of truth.
- Use the ChatGPT, Gemini and Claude
  recommendations as guidance.
- Create ONE final value.

For title:
Return one copy-pastable product title.

For description:
Return one copy-pastable product description.

For features:
Return  copy-pastable features value.

For attributes:
Return  copy-pastable attributes value.

For assets:
Return one copy-pastable assets value.

For pricing:
Return one copy-pastable pricing value.

If previous generated versions are supplied,
create a NEW version.

Do not repeat a previous version exactly.
"""

    human_prompt = f"""
Criterion:
{criterion}

PRODUCT:
{product_data}

CHATGPT RECOMMENDATIONS:
{chatgpt_recommendations}

GEMINI RECOMMENDATIONS:
{gemini_recommendations}

CLAUDE RECOMMENDATIONS:
{claude_recommendations}

PREVIOUS GENERATED VERSIONS:
{previous_versions}

Generate exactly ONE new copy-pastable
value for "{criterion}".
"""

    # ============================================================
    # 7. CALL CHATGPT
    # ============================================================

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
        )

    except Exception as exc:
        print(
            "LLM generation error:",
            exc,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to generate recommendation",
        )

    # ============================================================
    # 8. GET GENERATED VALUE
    # ============================================================

    generated_value = response.content

    if not isinstance(
        generated_value,
        str,
    ):
        generated_value = str(generated_value)

    generated_value = generated_value.strip()

    if not generated_value:
        raise HTTPException(
            status_code=500,
            detail="Generated recommendation is empty",
        )

    # ============================================================
    # 9. TOKEN USAGE
    # ============================================================

    usage = (
        getattr(
            response,
            "usage_metadata",
            None,
        )
        or {}
    )

    input_tokens = usage.get(
        "input_tokens",
        0,
    )

    output_tokens = usage.get(
        "output_tokens",
        0,
    )

    total_tokens = usage.get(
        "total_tokens",
        input_tokens + output_tokens,
    )

    token_usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }

    # ============================================================
    # 10. GET EXISTING SINGLE RECOMMANDATION JSON
    # ============================================================

    single_recommandation = product.single_recommandation or {}

    # Make a copy so we don't accidentally
    # overwrite other criteria.
    single_recommandation = dict(single_recommandation)

    # ============================================================
    # 11. APPEND NEW VERSION
    # ============================================================

    existing_criterion = single_recommandation.get(criterion) or {}

    existing_values = existing_criterion.get("value") or []

    # The request's versions should normally
    # already contain these values.
    #
    # Prefer the DB values if they exist so
    # we don't accidentally lose stored versions.
    if existing_values:
        current_versions = list(existing_values)
    else:
        current_versions = list(versions)

    # Prevent duplicates if the model somehow
    # returns an existing value.
    if generated_value in current_versions:
        raise HTTPException(
            status_code=500,
            detail=("Generated recommendation " "duplicated an existing version"),
        )

    current_versions.append(generated_value)

    # Safety limit.
    current_versions = current_versions[:MAX_GENERATED_VERSIONS]

    # ============================================================
    # 12. UPDATE ONLY THIS CRITERION
    # ============================================================

    single_recommandation[criterion] = {
        "value": current_versions,
        "token_usage": token_usage,
    }

    # ============================================================
    # 13. SAVE TO THE ONE JSONB COLUMN
    # ============================================================

    product.single_recommandation = single_recommandation

    await db.commit()

    # ============================================================
    # 14. RESPONSE
    # ============================================================

    return {
        "single_recommandation": {
            criterion: {
                "value": current_versions,
                "token_usage": token_usage,
            }
        }
    }
