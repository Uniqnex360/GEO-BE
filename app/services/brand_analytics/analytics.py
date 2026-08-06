"""
Streams progress for a brand-visibility run as newline-delimited JSON, e.g.:

    {"type": "status", "color": "green", "message": "Running openai model..."}
    {"type": "recommendation", "model": "openai", "recommendation": {...}}
    {"type": "result", "color": "green", "model": "openai", "cached": false, "brand_analytic_id": 42, "recommendations": [...]}
    {"type": "error", "color": "red", "message": "..."}

Flow per call:
  1. get-or-create the Brand row for this tenant
  2. for each provider (openai / anthropic / google):
       - if a BrandAnalytic for this brand+model exists within
         ANALYTICS_FRESHNESS_DAYS, reuse it and emit cached recommendations
       - otherwise run the full pipeline, streaming status and recommendations as it goes,
         then persist the result
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from langchain_core.language_models import BaseChatModel

from app.core.database import SessionLocal
from app.models.brand import Brand, BrandAnalytic
from app.models.base import LLMModels

from .helpers import get_llm, BrandVisibilityAnalyzer
from .types import BrandInput, BrandVisibilityReport

# How many days a previous run is still considered fresh enough to reuse
# instead of re-running the whole (expensive) pipeline. Single knob to tune.
ANALYTICS_FRESHNESS_DAYS = 7

# provider key (as used by get_llm) -> stored enum value
MODEL_ENUM_MAP = {
    "openai": LLMModels.GPT,
    "anthropic": LLMModels.CLAUDE,
    "google": LLMModels.GEMINI,
}


def _emit(payload: dict) -> str:
    return json.dumps(payload) + "\n"


def _status(message: str, color: str = "green") -> str:
    return _emit({"type": "status", "color": color, "message": message})


async def _get_or_create_brand(
    db: AsyncSession,
    tenant_id: int,
    brand_name: str,
    country: str,
    website: str,
) -> Brand:
    brand_input = BrandInput(
        brand_name=brand_name,
        country=country,
        website=website,
    )

    stmt = select(Brand).where(Brand.tenant_id == tenant_id, Brand.name == brand_name)
    brand = (await db.scalars(stmt)).first()

    if brand:
        return brand

    brand = Brand(
        tenant_id=tenant_id,
        name=brand_name,
        domain=brand_input.domain,
        country=country,
    )
    db.add(brand)
    await db.commit()
    await db.refresh(brand)

    return brand


async def _get_recent_analytic(
    db: AsyncSession,
    tenant_id: int,
    brand_id: int,
    model_choice: LLMModels,
    freshness_days: int,
) -> Optional[BrandAnalytic]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=freshness_days)

    stmt = (
        select(BrandAnalytic)
        .where(
            BrandAnalytic.tenant_id == tenant_id,
            BrandAnalytic.brand_id == brand_id,
            BrandAnalytic.model_choice == model_choice,
            BrandAnalytic.created_at >= cutoff,
        )
        .order_by(BrandAnalytic.created_at.desc())
    )

    return (await db.scalars(stmt)).first()


async def _save_analytic(
    db: AsyncSession,
    tenant_id: int,
    brand: Brand,
    model_choice: LLMModels,
    report: BrandVisibilityReport,
) -> BrandAnalytic:
    dims = {d.name: d for d in report.dimensions}

    def weighted(name: str):
        d = dims.get(name)
        return d.weighted_score if d else None

    def raw(name: str):
        d = dims.get(name)
        return d.raw_value if d else None

    profile = report.raw_responses.get("brand_profile", {})

    analytic = BrandAnalytic(
        tenant_id=tenant_id,
        brand_id=brand.id,
        overall_score=report.overall_score,
        sentiment=report.sentiment,
        model_choice=model_choice,
        mention_score=weighted("mention"),
        citation_score=weighted("citation"),
        share_of_voice_score=weighted("share_of_voice"),
        product_coverage_score=weighted("product_coverage"),
        category_coverage_score=weighted("category_coverage"),
        knowledge_graph_score=weighted("knowledge_graph"),
        authority_score=weighted("authority"),
        sentiment_score=weighted("sentiment"),
        diagnosis=report.diagnosis.model_dump(),
        recommendations=[r.model_dump() for r in report.recommendations],
        categories=profile.get("product_categories"),
        competitors=profile.get("competitors"),
        generated_prompts=report.raw_responses.get("generated_prompts"),
        prompt_factory=report.raw_responses.get("prompt_battery"),
        dimensions=[d.model_dump() for d in report.dimensions],
        share_of_voice_value=raw("share_of_voice"),
        share_of_voice_raw_response=report.raw_responses.get("share_of_voice"),
        product_coverage_value=raw("product_coverage"),
        product_coverage_raw_response=report.raw_responses.get("product_coverage"),
        category_coverage_value=raw("category_coverage"),
        category_coverage_raw_response=report.raw_responses.get("category_coverage"),
        knowledge_graph_value=raw("knowledge_graph"),
        knowledge_graph_raw_response=report.raw_responses.get("knowledge_graph"),
        authority_value=raw("authority"),
        authority_raw_response=report.raw_responses.get("authority"),
    )
    db.add(analytic)
    await db.commit()
    await db.refresh(analytic)
    return analytic


async def start_brand_analytics(
    brand_name: str,
    country: str,
    website: str,
    extra_context: str,
    tenant_id: int,
    freshness_days: int = ANALYTICS_FRESHNESS_DAYS,
) -> AsyncGenerator[str, None]:
    async with SessionLocal() as db:
        try:
            yield _status(f"Looking up brand '{brand_name}'...")
            brand = await _get_or_create_brand(
                db, tenant_id, brand_name, country, website
            )

            brand_input = BrandInput(
                brand_name=brand_name,
                country=country,
                website=website,
                extra_context=extra_context,
            )

            for provider in ["openai", "anthropic", "google"]:
                model_choice = MODEL_ENUM_MAP[provider]

                yield _status(f"Checking for a recent {provider} analysis...")
                existing = await _get_recent_analytic(
                    db, tenant_id, brand.id, model_choice, freshness_days
                )

                if existing:
                    yield _status(
                        f"Found a {provider} analysis from the last {freshness_days} "
                        "day(s) - reusing it instead of re-running."
                    )

                    # Extract recommendations stored in database column
                    cached_recommendations = existing.recommendations or []

                    # Stream each cached recommendation individually
                    for rec in cached_recommendations:
                        yield _emit(
                            {
                                "type": "recommendation",
                                "model": provider,
                                "recommendation": rec,
                            }
                        )

                    # Emit result event with cached recommendations payload included
                    yield _emit(
                        {
                            "type": "result",
                            "color": "green",
                            "model": provider,
                            "cached": True,
                            "brand_analytic_id": existing.id,
                            "recommendations": cached_recommendations,
                        }
                    )
                    continue

                yield _status(f"Running {provider} model...")
                llm: BaseChatModel = get_llm(provider)
                analyzer = BrandVisibilityAnalyzer(brand_input, llm)

                report: Optional[BrandVisibilityReport] = None
                async for event in analyzer.analyze_stream():
                    if event["type"] == "status":
                        yield _status(f"[{provider}] {event['message']}")
                    elif event["type"] == "recommendation":
                        # Relay individual live recommendations if streamed by analyzer
                        yield _emit(
                            {
                                "type": "recommendation",
                                "model": provider,
                                "recommendation": event.get("recommendation"),
                            }
                        )
                    elif event["type"] == "result":
                        report = event["report"]

                if report is None:
                    raise RuntimeError(f"{provider} analysis did not produce a report")

                yield _status(f"Saving {provider} results...")
                saved = await _save_analytic(db, tenant_id, brand, model_choice, report)

                yield _emit(
                    {
                        "type": "result",
                        "color": "green",
                        "model": provider,
                        "cached": False,
                        "brand_analytic_id": saved.id,
                        "recommendations": saved.recommendations or [],
                    }
                )

            yield _status("All models complete.")

        except Exception as e:
            yield _emit(
                {
                    "type": "error",
                    "color": "red",
                    "message": str(e),
                }
            )
