import re
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, RootModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.database import get_db
from app.core.security import validate_jwt_token
from app.models import Product

router = APIRouter()

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

MAX_REWRITE_COUNT = 3

DO_NOT_INVENT_SPECS_RULE = "- Do not invent specifications."
NO_NAME_IN_BODY_RULE = (
    "- Do not mention the product name, model number, or product code anywhere "
    'in the output, including mid-sentence — refer to it only as "this product", '
    '"this component", "this item", or by its general category (e.g. "this acorn nut").'
)
NO_NAME_OPENING_RULE = (
    "- Do not begin with the product name, brand name, or model number — "
    "open with a general statement about its function, category, or use instead."
)
NO_CODES_RULE = "- Do NOT include the SKU, MPN, UPC/EAN, model number, or any internal product codes."
NO_PROMO_PRICE_RULE = '- Do NOT add prices, quantities, or marketing words like "best", "cheap", "discount".'
AVOID_AI_STYLE_RULE = "- Avoid AI-style wording."
AVOID_PROMO_LANGUAGE_RULE = "- Avoid promotional language."

REWRITE_SYSTEM_PROMPT = """You are a senior industrial ecommerce content editor.
Rewrite content so it sounds naturally human-written. Improve Search Engine
Optimization (SEO) and Generative Engine Optimization (GEO). Preserve technical
accuracy. Do not invent specifications. Avoid AI-style wording, repetitive
phrasing, and promotional language."""

REWRITE_TITLE_PROMPT = (
    """
You are a senior industrial ecommerce content editor.
Rewrite the following product title.
Requested improvement:
{selected_option}
Original Title:
{original}
Goals:
- Improve readability.
- Sound naturally human-written.
- Improve SEO and GEO.
- Preserve technical accuracy.
"""
    + DO_NOT_INVENT_SPECS_RULE
    + "\n"
    + NO_CODES_RULE
    + "\n"
    + NO_PROMO_PRICE_RULE
    + "\n"
    + AVOID_AI_STYLE_RULE
    + "\n"
    + AVOID_PROMO_LANGUAGE_RULE
    + """
Return only the rewritten title.
"""
)

REWRITE_FEATURES_PROMPT = (
    """
You are a senior ecommerce content editor.
Rewrite or extract clear product features from the following context.
Requested improvement:
{selected_option}
Source Context:
{original}
Goals:
- Improve readability.
- Sound naturally human-written.
- Preserve technical accuracy.
- Improve SEO and GEO.
"""
    + DO_NOT_INVENT_SPECS_RULE
    + "\n"
    + NO_CODES_RULE
    + "\n"
    + NO_NAME_IN_BODY_RULE
    + """
Return only the rewritten bullet list.
"""
)

REWRITE_DESCRIPTION_PROMPT = (
    """
You are a senior ecommerce content editor.
Rewrite the following product description.
Requested improvement:
{selected_option}
Original Description:
{original}
Goals:
- Improve readability.
- Improve grammar.
- Sound naturally human-written.
- Preserve technical accuracy.
- Improve SEO and GEO.
"""
    + NO_NAME_IN_BODY_RULE
    + "\n"
    + NO_NAME_OPENING_RULE
    + "\n"
    + NO_CODES_RULE
    + """
- Remove repetitive wording.
"""
    + DO_NOT_INVENT_SPECS_RULE
    + """
Return only the rewritten description.
"""
)


def parse_title(text: str) -> str:
    return text.strip().strip('"').strip("'")


def parse_features(text: str) -> List[str]:
    return [
        line.strip("-•*0123456789. ").strip()
        for line in text.splitlines()
        if line.strip()
        and (
            line.strip().startswith(("-", "•", "*"))
            or re.match(r"^\d+\.", line.strip())
        )
    ]


def parse_description(text: str) -> str:
    return text.strip()


REWRITE_SPECS = {
    "title": {"prompt": REWRITE_TITLE_PROMPT, "parse": parse_title},
    "features": {"prompt": REWRITE_FEATURES_PROMPT, "parse": parse_features},
    "description": {"prompt": REWRITE_DESCRIPTION_PROMPT, "parse": parse_description},
}

FIELD_COLUMN_MAP = {
    "title": {
        "versions_column": "product_name_ai",
        "counter_column": "ai_title_rewrite_count",
    },
    "features": {
        "versions_column": "features_ai",
        "counter_column": "ai_features_rewrite_count",
    },
    "description": {
        "versions_column": "description_ai",
        "counter_column": "ai_description_rewrite_count",
    },
}


def get_fallback_original(product_obj: Any, field: str) -> Optional[Any]:
    """
    Retrieves fallback text directly from the Product table if no prior version
    was passed in the request body, cascading down to available fields.
    """
    title_text = getattr(product_obj, "name", None) or getattr(
        product_obj, "title", None
    )
    desc_text = getattr(product_obj, "long_description", None) or getattr(
        product_obj, "short_description", None
    )
    features_text = getattr(product_obj, "current_ai_features", None)

    if field == "title":
        # Title Priority: Existing Title -> Existing Description -> Existing Features
        return (
            title_text
            or desc_text
            or (
                features_text[0]
                if isinstance(features_text, list) and features_text
                else None
            )
        )

    if field == "description":
        # Description Priority: Existing Description -> Existing Title -> Existing Features
        if desc_text:
            return desc_text
        if title_text:
            return title_text
        if features_text and isinstance(features_text, list):
            return "\n".join(f"- {f}" for f in features_text)
        return None

    if field == "features":
        # Features Priority: Existing Features -> Existing Description -> Existing Title
        if features_text:
            return features_text
        if desc_text:
            return desc_text
        if title_text:
            return title_text
        return None

    return None


async def call_openai(
    prompt: str,
    system_prompt: str = REWRITE_SYSTEM_PROMPT,
    model: str = "gpt-3.5-turbo",
    temperature: float = 0.3,
    max_tokens: Optional[int] = 500,
) -> Optional[str]:
    try:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
    except OpenAIError as e:
        print("OpenAI Error:", e)
        return None


async def append_ai_history(
    db: AsyncSession,
    product_obj: Any,
    field: str,
    version: str,
    value: Any,
    entry_type: str,
    source: str,
    option: str,
) -> None:
    pass


class FieldVersions(RootModel[Dict[str, Union[str, List[str]]]]):
    pass


class RegenerateContentRequest(BaseModel):
    product_id: int
    option: str = ""
    title: Optional[FieldVersions] = None
    features: Optional[FieldVersions] = None
    description: Optional[FieldVersions] = None


@router.post("/regenerate-ai-contents/")
async def regenerate_ai_contents(
    payload: RegenerateContentRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    stmt = select(Product).where(Product.id == payload.product_id)
    res = await db.execute(stmt)
    product_obj = res.scalar_one_or_none()

    if not product_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    result: Dict[str, Any] = {}
    has_updates = False

    field_requests = {
        "title": payload.title.root if payload.title else None,
        "features": payload.features.root if payload.features else None,
        "description": payload.description.root if payload.description else None,
    }

    for field, spec in REWRITE_SPECS.items():
        payload_versions = field_requests.get(field)
        if payload_versions is None:
            continue

        target_version = None
        for i in range(1, MAX_REWRITE_COUNT + 1):
            v_key = f"v{i}"
            if v_key not in payload_versions:
                target_version = v_key
                break

        if target_version is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum allowed rewrite count ({MAX_REWRITE_COUNT}) reached for '{field}'.",
            )

        # 1. Look for existing version iterations (v3 -> v2 -> v1)
        original = None
        existing_v_indices = sorted(
            [
                int(k[1:])
                for k in payload_versions.keys()
                if k.startswith("v") and k[1:].isdigit()
            ],
            reverse=True,
        )

        for idx in existing_v_indices:
            val = payload_versions.get(f"v{idx}")
            if val:
                original = val
                break

        # 2. Check 'current' field in request body
        if not original:
            original = payload_versions.get("current")

        # 3. Fallback to DB attributes (includes Feature -> Title / Description fallback)
        if not original:
            original = get_fallback_original(product_obj, field)

        # 4. Special Fallback Handling for Features when original is still null/empty
        if field == "features" and (not original or len(original) == 0):
            # Fallback to Title
            original = (
                getattr(product_obj, "name", None)
                or getattr(product_obj, "title", None)
                or getattr(product_obj, "long_description", None)
                or getattr(product_obj, "short_description", None)
            )

        if not original:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not generate '{field}'. Missing product details in payload and database.",
            )

        # Format features list if provided as a List[str]
        if field == "features" and isinstance(original, list):
            original = "\n".join(f"- {f}" for f in original)

        columns = FIELD_COLUMN_MAP[field]
        versions_column = columns["versions_column"]
        counter_column = columns["counter_column"]

        db_versions_raw = getattr(product_obj, versions_column, None)
        db_versions = dict(db_versions_raw) if isinstance(db_versions_raw, dict) else {}

        if target_version in db_versions:
            result[field] = {
                "version": target_version,
                "value": db_versions[target_version],
                "cached": True,
            }
            continue

        prompt = spec["prompt"].format(
            selected_option=payload.option, original=original
        )

        raw = await call_openai(
            prompt=prompt,
            system_prompt=REWRITE_SYSTEM_PROMPT,
            model="gpt-3.5-turbo",
            max_tokens=500,
        )

        if raw is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to rewrite {field}",
            )

        parsed_value = spec["parse"](raw)

        db_versions[target_version] = parsed_value
        setattr(product_obj, versions_column, db_versions)
        flag_modified(product_obj, versions_column)

        current_count = getattr(product_obj, counter_column, 0) or 0
        setattr(product_obj, counter_column, min(current_count + 1, MAX_REWRITE_COUNT))

        has_updates = True

        result[field] = {
            "version": target_version,
            "value": parsed_value,
            "cached": False,
        }

        await append_ai_history(
            db=db,
            product_obj=product_obj,
            field=field,
            version=target_version,
            value=parsed_value,
            entry_type="rewrite",
            source="regenerateAiContents",
            option=payload.option,
        )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields were provided to regenerate.",
        )

    if has_updates:
        await db.commit()
        await db.refresh(product_obj)

    return result


class UpdateProductAIContentRequest(BaseModel):
    product_id: int
    title: Optional[str] = None
    features: Optional[List[str]] = None
    description: Optional[str] = None


class UpdateProductAIContentResponse(BaseModel):
    success: bool
    message: str
    product_id: int
    updated_fields: dict


@router.patch(
    "/update-product-ai-content/",
    response_model=UpdateProductAIContentResponse,
    status_code=status.HTTP_200_OK,
)
async def update_product_ai_content(
    payload: UpdateProductAIContentRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(validate_jwt_token),
):
    """
    Applies selected AI-generated content or user-edited versions to the main product fields:
    - title -> updates product.name
    - features -> updates product.current_ai_features
    - description -> updates product.long_description
    """
    stmt = select(Product).where(Product.id == payload.product_id)
    res = await db.execute(stmt)
    product_obj = res.scalar_one_or_none()

    if not product_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    updated_fields = {}

    # 1. Apply title -> product.name
    if payload.title is not None:
        product_obj.name = payload.title.strip()
        updated_fields["name"] = product_obj.name

    # 2. Apply features -> product.current_ai_features
    if payload.features is not None:
        # Clean empty strings if present
        cleaned_features = [
            f.strip() for f in payload.features if isinstance(f, str) and f.strip()
        ]
        product_obj.current_ai_features = cleaned_features
        updated_fields["current_ai_features"] = product_obj.current_ai_features

    # 3. Apply description -> product.long_description
    if payload.description is not None:
        product_obj.long_description = payload.description.strip()
        updated_fields["long_description"] = product_obj.long_description

    if not updated_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field ('title', 'features', or 'description') must be provided to apply updates.",
        )

    # Save updates to DB
    await db.commit()
    await db.refresh(product_obj)

    return UpdateProductAIContentResponse(
        success=True,
        message="Product content applied successfully.",
        product_id=product_obj.id,
        updated_fields=updated_fields,
    )
