from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

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
    recommendations: list[Recommendation] = Field(
        min_length=1,
        max_length=3,
    )


class ModelRecommendations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Literal["GPT", "GEMINI", "CLAUDE"]

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

    models: list[ModelRecommendations] = Field(
        min_length=3,
        max_length=3,
    )

    criteria: dict[Criterion, CriterionSummary]


RECOMMENDATION_SYSTEM_PROMPT = """
You are a GEO optimization expert.

Analyze the provided product and GEO audit.

Generate actionable recommendations for:

1. title
2. description
3. features
4. attributes
5. assets
6. pricing

For every criterion:

- Give a score from 0 to 100.
- Give 1 to 3 actionable recommendations.
- Each recommendation must contain:
  - impact: 1-10
  - effort: Low effort / Medium effort / High effort
  - recommendation
  - why
  - action

Recommendations must be specific to the product and audit.

Do not invent product facts.

Return ONLY the requested structured output.
"""


def _product_data(product: Any) -> dict[str, Any]:
    """
    Convert SQLAlchemy ORM object into a plain dict.

    IMPORTANT:
    This dict is created while the SQLAlchemy session is alive.
    The LLM layer never receives the ORM object.
    """

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

    if hasattr(audit_data, "model_dump"):
        audit_json = audit_data.model_dump(mode="json")
    else:
        audit_json = audit_data

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

    # Make absolutely sure model name is correct.
    result.model = model_name

    return result


def _build_summary(
    model_results: list[ModelRecommendations],
) -> dict[Criterion, CriterionSummary]:

    summary: dict[Criterion, CriterionSummary] = {}

    for criterion in Criterion:

        results = [getattr(model, criterion.value) for model in model_results]

        all_recommendations = [
            recommendation
            for result in results
            for recommendation in result.recommendations
        ]

        count = len(all_recommendations)

        if count == 0:
            raise ValueError(f"No recommendations returned for {criterion.value}")

        weighted_score = round(
            sum(result.score * len(result.recommendations) for result in results)
            / count
        )

        avg_impact = round(
            sum(recommendation.impact for recommendation in all_recommendations)
            / count,
            1,
        )

        summary[criterion] = CriterionSummary(
            score=weighted_score,
            recommendation_count=count,
            avg_impact=avg_impact,
        )

    return summary


async def _run_one_model(
    model_name: Literal["GPT", "GEMINI", "CLAUDE"],
    product_data: dict[str, Any],
    search_keyword: str,
    user_prompt: str,
) -> ModelRecommendations:

    # First call: GEO audit
    audit, _usage = await run_single_model_audit(
        model_name=model_name,
        user_prompt=user_prompt,
        search_keyword=search_keyword,
    )

    # Second call: recommendations
    recommendations = await _get_model_recommendations(
        model_name=model_name,
        product_data=product_data,
        audit_data=audit,
    )

    return recommendations


async def generate_product_recommendations(
    product_data: dict[str, Any],
    *,
    search_keyword: str,
    user_prompt: str,
) -> ProductRecommendations:
    """
    Run GPT + GEMINI + CLAUDE concurrently.

    NO DATABASE SESSION HERE.

    This is intentional:
    LLM calls can take a long time and should never hold
    a Neon/Postgres connection open.
    """

    results = await asyncio.gather(
        *[
            _run_one_model(
                model_name=model_name,
                product_data=product_data,
                search_keyword=search_keyword,
                user_prompt=user_prompt,
            )
            for model_name in MODEL_NAMES
        ],
        return_exceptions=True,
    )

    model_results: list[ModelRecommendations] = []
    errors: list[str] = []

    for model_name, result in zip(MODEL_NAMES, results):

        if isinstance(result, Exception):
            errors.append(f"{model_name}: {type(result).__name__}: {result}")
            continue

        model_results.append(result)

    if len(model_results) != len(MODEL_NAMES):

        error_message = " | ".join(errors)

        raise RuntimeError("GEO recommendation generation failed. " f"{error_message}")

    # Keep deterministic model ordering.
    model_results.sort(key=lambda item: MODEL_NAMES.index(item.model))

    return ProductRecommendations(
        models=model_results,
        criteria=_build_summary(model_results),
    )
