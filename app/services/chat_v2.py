import json
import asyncio
from typing import Optional, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from langchain.agents import create_agent
from langchain.tools import tool

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession


from app.models.base import LLMModels
from app.models import Product, Brand, Chat, ChatSearchQuery, ChatGEOAuditRecord

RETENTION_DAYS_THRESHOLD = 7


GEO_SYSTEM_PROMPT = """
You are a GEO expert. Use tools to analyze visibility parameters and map competitive gaps.

CRITICAL SCHEMA DIRECTION:
Every dictionary field within the 'product_details' object MUST be structured as a JSON object containing EXACTLY these keys: "value", "score", and "tips".
Output only valid JSON conforming perfectly to the schema definition.
"""


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


def build_user_instruction_v2(input_data: GEOAuditRequest) -> str:
    return f"""Analyze the following product payload for optimization:
Product Name: {input_data.product_name}
Product URL: {input_data.product_url}
Website Reference: {input_data.website}
SKU: {input_data.sku} | MPN: {input_data.mpn} | UPC: {input_data.upc}
Geographic Target Region: {input_data.country}
User Request Extra Context: {input_data.extra_context}

Generate relevant domain search queries dynamically based on the input text to extract real metadata metrics.
"""


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


# ==========================================
# 3. YOUR EXACT PYDANTIC OUTPUT SCHEMAS
# ==========================================


class CompetitorMetrics(BaseModel):
    competitor_name: str = Field(description="Name of the competitor platform found.")
    product_title: str = Field(description="Title string used by this competitor.")
    no_of_faq: int = Field(description="Count of FAQs on their page.")
    no_of_reviews: int = Field(description="Count of reviews/ratings on their page.")
    keywords_used: list[str] = Field(
        description="Core keywords used by this competitor."
    )
    no_of_attributes: int = Field(
        description="Count of product attributes/specs listed."
    )
    assets_present: dict[str, bool] = Field(
        description="Media asset indicators (e.g., {'images': true, 'videos': false})."
    )
    no_of_features: int = Field(description="Count of main features listed.")
    word_count: int = Field(description="Word count of their product description.")


class GEOProductDetail(BaseModel):
    product_name: dict[str, Any] = Field(
        description="Expected structure: {'value': str, 'score': int, 'tips': str}"
    )
    product_url: dict[str, Any] = Field(
        description="Expected structure: {'value': str, 'score': int, 'tips': str}"
    )
    sku: dict[str, Any] = Field(
        description="Expected structure: {'value': str|None, 'score': int, 'tips': str}"
    )
    mpn: dict[str, Any] = Field(
        description="Expected structure: {'value': str|None, 'score': int, 'tips': str}"
    )
    upc: dict[str, Any] = Field(
        description="Expected structure: {'value': str|None, 'score': int, 'tips': str}"
    )
    gtin: dict[str, Any] = Field(
        description="Expected structure: {'value': str|None, 'score': int, 'tips': str}"
    )
    ean: dict[str, Any] = Field(
        description="Expected structure: {'value': str|None, 'score': int, 'tips': str}"
    )
    product_title: dict[str, Any] = Field(
        description="Expected structure: {'value': str, 'score': int, 'tips': str}"
    )
    description_analysis: dict[str, Any] = Field(
        description="Expected structure: {'value': str, 'score': int, 'tips': str}"
    )
    faqs: dict[str, Any] = Field(
        description="Expected structure: {'value': int, 'score': int, 'tips': str}"
    )
    reviews: dict[str, Any] = Field(
        description="Expected structure: {'value': int, 'score': int, 'tips': str}"
    )
    keywords: dict[str, Any] = Field(
        description="Expected structure: {'value': list[str], 'score': int, 'tips': str}"
    )
    attributes: dict[str, Any] = Field(
        description="Expected structure: {'value': int, 'score': int, 'tips': str}"
    )
    features: dict[str, Any] = Field(
        description="Expected structure: {'value': int, 'score': int, 'tips': str}"
    )
    assets: dict[str, Any] = Field(
        description="Expected structure: {'value': dict[str, bool], 'score': int, 'tips': str}"
    )


class ChatQueryBase(BaseModel):
    chat_context: str = Field(description="Scope tracking token context identifier.")
    brand: str = Field(description="Identified target brand.")
    query: str = Field(description="The generated search engine query executed.")
    product_found: bool = Field(description="True if target product was discovered.")
    share_of_voice: float = Field(description="Calculated share of voice percentage.")
    total_websites_found: int = Field(
        description="Count of unique reference web sources found."
    )
    citation_rank: int = Field(description="Organic ranking position across sources.")
    platform_breakdown: dict[str, int] = Field(
        description="Distribution count across platforms."
    )
    citing_sources: list[str] = Field(description="List of source URLs referenced.")
    competitors_mentioned: list[str] = Field(
        description="Competitor platforms or alternative brands found."
    )
    optimization_tips_for_better_result: str = Field(
        description="Query-specific optimization tip."
    )


class BrandAnalysis(BaseModel):
    brand_name: str = Field(description="Extracted primary brand.")


class UnifiedGEOResponse(BaseModel):
    model_used: str = Field(
        description="The running LLM configuration model name identifier."
    )
    brand: BrandAnalysis = Field(description="Target brand information.")
    product_details: GEOProductDetail = Field(
        description="Granular field audit and scoring metrics."
    )
    competitor_analytics: list[CompetitorMetrics] = Field(
        description="Competitor baseline data blocks."
    )
    queries_executed: list[ChatQueryBase] = Field(
        description="Search trace matrix execution logs."
    )
    final_optimized_tips_summary: str = Field(
        description="Summarized actionable checklist adjustments."
    )


@tool
def geo_web_search(query: str) -> str:
    """Searches the web for general product metadata, listings, share of voice metrics, and competitive platform references."""
    return f"[Web Results for search query: '{query}'] - 2 FAQs, 10 customer reviews found."


@tool
def scrape_product_metadata(url: str) -> str:
    """Scrapes raw data profiles, review elements, text configurations, and media blocks from a given landing page URL."""
    return f"Raw Scraped Payload from {url}: FAQs found=2, Reviews found=10."


# Core toolkit hook list ingested directly by the agent instance
GEO_TOOLS = [geo_web_search, scrape_product_metadata]


async def run_geo_audit_stream(
    payload: dict,
    db: AsyncSession,
    tenant_id: int,
    user_id: int | None = None,
):

    try:

        yield json.dumps(
            {"status": "progress", "message": "Checking product registry..."}
        ) + "\n"

        product_name = payload.product_name
        product_url = payload.product_url or payload.website

        sku = payload.sku
        mpn = payload.mpn
        upc = payload.upc

        country = payload.country or "United States"

        product_record = None
        product_id = None
        competitors = []

        historical_best = None

        # ==============================
        # PRODUCT LOOKUP FILTERS
        # ==============================

        lookup_filters = []

        if product_name:
            lookup_filters.append(Product.name == product_name)

        if sku:
            lookup_filters.append(Product.sku == sku)

        if mpn:
            lookup_filters.append(Product.mpn == mpn)

        if upc:
            lookup_filters.append(Product.upc == upc)

        if not lookup_filters and not product_url:

            yield json.dumps(
                {"status": "failed", "message": "Missing structural identifiers."}
            ) + "\n"

            return

        # ==============================
        # LOAD PRODUCT + BRAND
        # ==============================

        if lookup_filters:

            stmt = (
                select(Product)
                .options(selectinload(Product.brand))
                .where((Product.tenant_id == tenant_id) & or_(*lookup_filters))
            )

            result = await db.execute(stmt)

            product_record = result.scalar_one_or_none()

        # ==============================
        # PRODUCT EXISTS LOGIC
        # ==============================

        if product_record:

            product_id = product_record.id

            yield json.dumps(
                {"status": "progress", "message": "Existing product located"}
            ) + "\n"

            if product_record.brand and product_record.brand.competitor:

                competitors = [
                    c.strip()
                    for c in product_record.brand.competitor.split(",")
                    if c.strip()
                ]

            # ==========================
            # CACHE RETENTION
            # ==========================

            threshold = datetime.now() - timedelta(days=RETENTION_DAYS_THRESHOLD)

            recent_stmt = (
                select(Chat)
                .where((Chat.product_id == product_id) & (Chat.created_at >= threshold))
                .order_by(Chat.created_at.desc())
                .limit(1)
            )

            recent_result = await db.execute(recent_stmt)

            recent_chat = recent_result.scalar_one_or_none()

            if recent_chat:

                yield json.dumps(
                    {
                        "status": "completed",
                        "message": "Warm cache hit",
                        "report": recent_chat.final_optimization_report,
                    }
                ) + "\n"

                return

            # ==========================
            # HISTORICAL BENCHMARK
            # ==========================

            metrics_stmt = (
                select(ChatSearchQuery)
                .join(Chat)
                .where(Chat.product_id == product_id)
                .order_by(ChatSearchQuery.share_of_voice.desc())
            )

            metrics_result = await db.execute(metrics_stmt)

            best_record = metrics_result.scalars().first()

            if best_record:

                historical_best = {
                    "best_share_of_voice": best_record.share_of_voice,
                    "best_citation_rank": best_record.citation_rank,
                }

        # ==============================
        # PRODUCT DOES NOT EXIST
        # ==============================

        else:

            yield json.dumps(
                {"status": "progress", "message": "Creating new registry entities..."}
            ) + "\n"

            brand_name = "Generic/Multi-Brand"

            brand_stmt = select(Brand).where(
                (Brand.name == brand_name) & (Brand.tenant_id == tenant_id)
            )

            brand_result = await db.execute(brand_stmt)

            brand_record = brand_result.scalar_one_or_none()

            if not brand_record:

                brand_record = Brand(
                    tenant_id=tenant_id,
                    name=brand_name,
                    country=country,
                    created_by=user_id,
                )

                db.add(brand_record)

                await db.flush()

            product_record = Product(
                tenant_id=tenant_id,
                brand_id=brand_record.id,
                name=(product_name or f"Product-{sku}"),
                brand_name=brand_name,
                sku=sku,
                mpn=mpn,
                upc=upc,
                created_by=user_id,
            )

            db.add(product_record)

            await db.flush()

            product_id = product_record.id

        # ======================================
        # KEEP YOUR EXISTING MODEL LOOP
        # ======================================

        models = list(LLMModels)

        total_models = len(models)

        user_prompt = build_user_instruction_v2(payload)

        all_reports = []

        for index, model_enum in enumerate(models):

            model_name = model_enum.value

            progress_start = int((index / total_models) * 100)

            yield json.dumps(
                {
                    "status": "progress",
                    "progress_pct": progress_start,
                    "message": f"Configuring runtime pool engine: '{model_name}'...",
                }
            ) + "\n"

            try:

                agent = create_agent(
                    model=model_name,
                    tools=GEO_TOOLS,
                    system_prompt=GEO_SYSTEM_PROMPT,
                    response_format=UnifiedGEOResponse,
                )

                yield json.dumps(
                    {
                        "status": "progress",
                        "progress_pct": progress_start + 10,
                        "message": f"[{model_name}] Extracting payload identifier strings...",
                    }
                ) + "\n"

                yield json.dumps(
                    {
                        "status": "progress",
                        "progress_pct": progress_start + 20,
                        "message": f"[{model_name}] Invoking context analysis tracing...",
                    }
                ) + "\n"

                response_state = await asyncio.to_thread(
                    agent.invoke,
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": user_prompt,
                            }
                        ]
                    },
                )

                structured_json: UnifiedGEOResponse = response_state.get(
                    "structured_response"
                )

                if structured_json:
                    structured_json.model_used = model_name

                yield json.dumps(
                    {
                        "status": "progress",
                        "progress_pct": progress_start + 30,
                        "message": f"[{model_name}] Recording PostgreSQL logs...",
                    }
                ) + "\n"

                identifier_field = (
                    payload.product_name
                    or payload.sku
                    or payload.product_url
                    or "Unknown Meta Query"
                )

                db_record = ChatGEOAuditRecord(
                    tenant_id=tenant_id,
                    product_identifier=identifier_field,
                    model_used=model_name,
                    status="SUCCESS",
                    audit_data=(
                        structured_json.model_dump() if structured_json else {}
                    ),
                )

                db.add(db_record)
                await db.commit()

                if structured_json:
                    all_reports.append(structured_json.model_dump())

                yield json.dumps(
                    {
                        "status": "progress",
                        "progress_pct": int(((index + 1) / total_models) * 100),
                        "message": f"{model_name} completed successfully.",
                    }
                ) + "\n"

            except Exception as model_error:

                yield json.dumps(
                    {
                        "status": "warning",
                        "message": f"{model_name} failed: {str(model_error)}",
                    }
                ) + "\n"

        # ======================================
        # SINGLE CONSOLIDATED COMMIT
        # ======================================

        try:

            for report in all_reports:

                geo_record = ChatGEOAuditRecord(
                    tenant_id=tenant_id,
                    product_identifier=(product_name or sku or product_url),
                    model_used=report["model_used"],
                    status="SUCCESS",
                    audit_data=report,
                )

                db.add(geo_record)

            await db.commit()

        except Exception as write_error:

            await db.rollback()

            yield json.dumps(
                {
                    "status": "failed",
                    "message": f"Persistence error: {str(write_error)}",
                }
            ) + "\n"

            return

    except Exception as e:

        await db.rollback()

        yield json.dumps({"status": "failed", "message": str(e)}) + "\n"
