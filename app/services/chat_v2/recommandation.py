"""
geo_recommendations.py

Runs the existing GEO audit for GPT/GEMINI/CLAUDE, gets recommendations for
exactly 6 product-page criteria, validates them with Pydantic, and saves the
result as JSON in product.recommendation.

Assumption:
    Your existing file is named `llm_audit.py` and contains:
      - run_single_model_audit()
      - build_chat_model_no_tools()

Change that import if your filename is different.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .llm_runner import build_chat_model, run_single_model_audit

MODEL_NAMES = ("GPT", "GEMINI", "CLAUDE")


class Criterion(str, Enum):
    title = "title"
    description = "description"
    features = "features"
    attributes = "attributes"
    assets = "assets"
    pricing = "pricing"


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact: int = Field(ge=1, le=10)
    effort: Literal["Low effort", "Medium effort", "High effort"]
    recommendation: str = Field(min_length=1)
    why: str = Field(min_length=1)
    action: str = Field(min_length=1)


class CriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=3)


class ModelRecommendations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Literal["GPT", "GEMINI", "CLAUDE"]

    # These six fields are intentionally explicit so they can never be omitted.
    title: CriterionResult
    description: CriterionResult
    features: CriterionResult
    attributes: CriterionResult
    assets: CriterionResult
    pricing: CriterionResult


class CriterionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    recommendation_count: int = Field(ge=1)
    avg_impact: float = Field(ge=1, le=10)


class ProductRecommendations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[ModelRecommendations] = Field(min_length=3, max_length=3)

    # Always exactly these six keys.
    criteria: dict[Criterion, CriterionSummary]


RECOMMENDATION_SYSTEM_PROMPT = """
You are a GEO (Generative Engine Optimization) recommendation engine for
e-commerce product pages.

Your job is to analyze the supplied product data and GEO audit data and give
concrete recommendations for AI search/recommendation engines.

You MUST return recommendations for exactly these 6 criteria:
- title
- description
- features
- attributes
- assets
- pricing

Rules:
- Never add another criterion.
- Give 1-3 recommendations for every criterion.
- impact is 1-10.
- effort must be exactly: Low effort, Medium effort, or High effort.
- score is 0-100 and represents the current GEO quality of that criterion.
- recommendation = short recommendation title.
- why = concise GEO reason.
- action = exact practical change to make.
- Do not invent product facts.
- Base recommendations on the supplied audit data.
- Keep everything concise and actionable.
"""


def _product_data(product: Any) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
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
        "short_description": product.short_description,
        "long_description": product.long_description,
        "meta_title": product.meta_title,
        "meta_description": product.meta_description,
        "regular_price": product.regular_price,
        "sale_price": product.sale_price,
        "currency": product.currency,
        "rating": product.rating,
        "rating_count": product.rating_count,
        "no_of_faqs": product.no_of_faqs,
        "no_of_reviews": product.no_of_reviews,
    }


async def _get_model_recommendations(
    model_name: Literal["GPT", "GEMINI", "CLAUDE"],
    product_data: dict[str, Any],
    audit_data: Any,
) -> ModelRecommendations:
    llm = build_chat_model(model_name).with_structured_output(ModelRecommendations)

    audit_json = (
        audit_data.model_dump(mode="json")
        if hasattr(audit_data, "model_dump")
        else audit_data
    )

    prompt = f"""
Model: {model_name}

PRODUCT:
{product_data}

GEO AUDIT:
{audit_json}

Return the final recommendations now.
"""

    result = await llm.ainvoke(
        [
            SystemMessage(content=RECOMMENDATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    )

    result = ModelRecommendations.model_validate(result)

    # Never trust the model to label itself correctly.
    result.model = model_name
    return result


def _build_summary(
    model_results: list[ModelRecommendations],
) -> dict[Criterion, CriterionSummary]:
    """
    Build the top-level summary used by the UI.

    Score is weighted by recommendation count, so models that produced more
    recommendations contribute proportionally more to that criterion.
    """
    summary: dict[Criterion, CriterionSummary] = {}

    for criterion in Criterion:
        results = [getattr(model, criterion.value) for model in model_results]
        all_recommendations = [
            recommendation
            for result in results
            for recommendation in result.recommendations
        ]

        count = len(all_recommendations)

        weighted_score = round(
            sum(result.score * len(result.recommendations) for result in results)
            / count
        )

        avg_impact = round(
            sum(r.impact for r in all_recommendations) / count,
            1,
        )

        summary[criterion] = CriterionSummary(
            score=weighted_score,
            recommendation_count=count,
            avg_impact=avg_impact,
        )

    return summary


async def generate_product_recommendations(
    db: AsyncSession,
    product: Any,
    *,
    search_keyword: str,
    user_prompt: str,
) -> ProductRecommendations:
    """
    Run all 3 models and save the final JSON to product.recommendation.

    Example:

        result = await generate_product_recommendations(
            db,
            product,
            search_keyword=product.title,
            user_prompt="Audit this product page for GEO.",
        )
    """
    product_data = _product_data(product)
    model_results: list[ModelRecommendations] = []

    for model_name in MODEL_NAMES:
        # Existing audit/tool-calling code from your file.
        audit, _usage = await run_single_model_audit(
            model_name=model_name,
            user_prompt=user_prompt,
            search_keyword=search_keyword,
        )

        recommendations = await _get_model_recommendations(
            model_name=model_name,  # type: ignore[arg-type]
            product_data=product_data,
            audit_data=audit,
        )

        model_results.append(recommendations)

    final_result = ProductRecommendations(
        models=model_results,
        criteria=_build_summary(model_results),
    )

    # Product.recommendation must be a SQLAlchemy JSON/JSONB column.
    product.recommendation = final_result.model_dump(mode="json")

    db.add(product)

    return final_result
