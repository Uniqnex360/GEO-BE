"""
GEO (Generative Engine Optimization) audit orchestration.

Given a product identifier (name / SKU / MPN / UPC / URL), this module:
  1. Looks up an existing product record, or creates one with LLM-enriched
     baseline metadata if it doesn't exist yet.
  2. Serves a cached report if a recent audit already exists.
  3. Otherwise runs the audit through every configured LLM (GPT / Gemini /
     Claude), persisting a Chat, its ChatSearchQuery rows, and a
     ChatGEOAuditRecord per model.
  4. Streams progress as newline-delimited JSON events the whole way through.
"""

import json
from typing import AsyncGenerator, Optional
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

from app.models.base import LLMModels
from app.models import Product, Brand, Chat, ChatSearchQuery, ChatGEOAuditRecord

# ======================================================================
# CONSTANTS
# ======================================================================

RETENTION_DAYS_THRESHOLD = 7

GEO_SYSTEM_PROMPT = """
You are a GEO expert. Use tools to analyze visibility parameters and map competitive gaps.

CRITICAL SCHEMA DIRECTION:
Every dictionary field within the 'product_details' object MUST be structured as a JSON object containing EXACTLY these keys: "value", "score", and "tips".
Output only valid JSON conforming perfectly to the schema definition.
"""


# ======================================================================
# REQUEST SCHEMA
# ======================================================================


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


# ======================================================================
# OUTPUT SCHEMAS
# ======================================================================


class AssetMetrics(BaseModel):
    images: bool = Field(default=False, description="True if images are present.")
    videos: bool = Field(default=False, description="True if videos are present.")


class PlatformBreakdownMetrics(BaseModel):
    google: int = Field(default=0, description="Count for Google platform.")
    anthropic: int = Field(default=0, description="Count for Anthropic platform.")
    openai: int = Field(default=0, description="Count for OpenAI search platform.")
    bing: int = Field(default=0, description="Count for Bing platform.")


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
    assets_present: AssetMetrics = Field(description="Media asset indicators.")
    no_of_features: int = Field(description="Count of main features listed.")
    word_count: int = Field(description="Word count of their product description.")


class CompetitorProductLink(BaseModel):
    """A clickable reference to a specific competitor product surfaced during a search query."""

    competitor_name: str = Field(description="Name of the competitor/brand.")
    product_name: str = Field(description="Name of the competitor's product.")
    product_url: str = Field(
        description="Direct URL to the competitor's product page, so the user can open it."
    )
    price: Optional[str] = Field(
        None,
        description="Listed price of the competitor product, if found (e.g. '$49.99').",
    )


class GEOAuditField(BaseModel):
    """Used ONLY for elements undergoing rich copy visibility auditing."""

    value: str = Field(
        default="", description="The extracted data string or content description."
    )
    score: int = Field(
        default=0, description="The evaluated visibility compliance score."
    )
    tips: str = Field(
        default="",
        description=(
            "Concrete, ready-to-paste optimization advice. NEVER stop at naming the problem or telling the reader "
            "to 'add', 'include', or 'change' something in the abstract - always write out the exact finished "
            "content that should go in, AND exactly where it goes. Format: '<WHERE (field/section/position)>: "
            '<WHAT TO DO> -> "<exact copy-pasteable text>"\'. '
            "Examples of GOOD tips: "
            "'Description, first sentence: state shipping coverage explicitly -> \"Ships to Germany within 3-5 "
            "business days.\"'  "
            "'Product title: replace with this exact title -> \"Bosch GKS 190 Circular Saw - 1400W, 190mm Blade, "
            "Ships to Ireland\"'  "
            "'Below the price: add this exact badge text -> \"In Stock - Dispatched within 24 hours\"'  "
            "If recommending a testimonial, quote the FULL testimonial text verbatim as it should appear, not a "
            "description of what a testimonial should say. If recommending region-specific content (e.g. a "
            "location-targeted headline or an FAQ answer), write the complete final text, not just the topic. "
            "BAD tips (never do this): 'Add an in-stock badge.' / 'Include Irish customer testimonials.' / "
            "'Highlight that it ships to Ireland.' - these name the fix but give nothing the reader can paste in."
        ),
    )


class GEOProductDetail(BaseModel):
    product_name: str = Field(description="Name of the target product.")
    product_url: str = Field(description="Target product landing page URL.")
    sku: Optional[str] = Field(None, description="Stock Keeping Unit number.")
    mpn: Optional[str] = Field(None, description="Manufacturer Part Number.")
    upc: Optional[str] = Field(None, description="Universal Product Code.")
    gtin: Optional[str] = Field(None, description="Global Trade Item Number.")
    ean: Optional[str] = Field(None, description="European Article Number.")

    faqs: int = Field(default=0, description="Count of found target FAQs.")
    reviews: int = Field(default=0, description="Count of user reviews integrated.")
    attributes: int = Field(
        default=0, description="Count of detailed product specifications."
    )
    features: int = Field(
        default=0, description="Count of unique item product features."
    )

    product_title: GEOAuditField = Field(
        description="Audit and scoring for visibility title formatting optimization."
    )
    description_analysis: GEOAuditField = Field(
        description="Audit and scoring for description keyword optimization."
    )
    keywords: GEOAuditField = Field(
        description="Audit and scoring for extracted target context search terms."
    )
    assets: GEOAuditField = Field(
        description="Audit and scoring for structural image/video configurations."
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
    platform_breakdown: PlatformBreakdownMetrics = Field(
        description="Distribution metrics across discovery platforms."
    )
    citing_sources: list[str] = Field(description="List of source URLs referenced.")
    competitors_mentioned: list[str] = Field(
        description="Competitor platforms or alternative brands found."
    )

    # NEW: clickable competitor product references for this query.
    competitor_products: list[CompetitorProductLink] = Field(
        default_factory=list,
        description=(
            "Specific competitor products discovered while researching this query. Each entry MUST include a "
            "real product_url so the user can click through and view the listing directly."
        ),
    )

    optimization_tag: str = Field(
        description=(
            "A single-word category representing the primary optimization recommendation. "
            "Examples: 'title', 'brand', 'attributes','description', 'faq', 'content', 'schema', 'images', "
            "'reviews', 'pricing', 'specifications', 'comparison', 'keywords', "
            "'metadata', 'headings', 'internal-links', 'external-links', 'trust', "
            "'availability',  'video', 'performance', 'citations'."
        )
    )

    # UPDATED description: now demands finished, pasteable content + exact placement,

    optimization_tips_for_better_result: str = Field(
        description=(
            "Strategic SEO suggestion explaining WHERE and WHAT to optimize. "
            "Identifies the target field/section and the high-level fix required "
            "(e.g., adjusting price positioning, adding local relevance, or tweaking title structure). "
            "BAD: Do not supply the finished copy here—keep this focused purely on the strategy/location."
        )
    )

    copy_pasteable_solution: str = Field(
        description=(
            "The exact, finished, copy-pasteable text or example title implementing the suggestion. "
            "Never stop at naming the fix—always supply the literal text ready for deployment. "
            "Example: 'For a lower-cost option, see the Pilot G2 at $2.50.' or 'Premium Fountain Pen - Smooth Writing Ergonomic Executive Pen'."
        )
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
        description=(
            "Summarized checklist of the highest-impact fixes across product_details and queries_executed. Each "
            "checklist line must follow the same rule as the individual tips fields: name where it goes and give "
            "the exact finished content to paste in, not just the action. E.g. '- In Stock badge (below price): "
            "\"In Stock - Dispatched within 24 hours\"' rather than '- Add an in-stock badge.'"
        )
    )


# ======================================================================
# TOOLS
# ======================================================================


@tool
def geo_web_search(query: str) -> str:
    """Searches the web for general product metadata, listings, share of voice metrics, and competitive platform references."""
    return f"[Web Results for search query: '{query}'] - 2 FAQs, 10 customer reviews found."


@tool
def scrape_product_metadata(url: str) -> str:
    """Scrapes raw data profiles, review elements, text configurations, and media blocks from a given landing page URL."""
    return f"Raw Scraped Payload from {url}: FAQs found=2, Reviews found=10."


GEO_TOOLS = [geo_web_search, scrape_product_metadata]


class ProductEnrichment(BaseModel):
    """Best-effort metadata inferred for a product that isn't in our database yet."""

    product_name: Optional[str] = None
    brand_name: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    no_of_faqs: int = Field(
        default=None,
        description="Estimated number of FAQs for this item. CRITICAL: Do not return 0; if unknown, estimate a realistic baseline count based on product type.",
    )
    no_of_reviews: int = Field(
        default=None,
        description="Estimated number of customer reviews for this item. CRITICAL: Do not return 0; if unknown, estimate a realistic baseline count based on product type.",
    )


# ======================================================================
# STREAMING EVENT HELPERS
#
# All of these just DRY up "build a dict, json.dumps it, append a newline".
# The exact keys/values sent for each situation are unchanged from the
# original implementation - callers still choose exactly what goes in.
# ======================================================================


def _emit(**fields) -> str:
    return json.dumps(fields) + "\n"


def _status(message: str, progress_pct: int) -> str:
    return _emit(
        type="status",
        color="#4f46e5",
        status="progress",
        message=message,
        progress_pct=progress_pct,
    )


def _result(message: str, report) -> str:
    return _emit(
        type="result",
        color="#22c55e",
        status="completed",
        message=message,
        report=report,
        progress_pct=100,
    )


def _model_warning(model_name: str, error: Exception) -> str:
    return _emit(
        type="error",
        color="#f59e0b",
        status="warning",
        message=f"{model_name} failed: {str(error)}",
    )


# ======================================================================
# PRODUCT LOOKUP / CREATION HELPERS
# ======================================================================


def _build_lookup_filters(payload: GEOAuditRequest) -> list:
    filters = []
    if payload.product_name:
        filters.append(Product.name == payload.product_name)
    if payload.sku:
        filters.append(Product.sku == payload.sku)
    if payload.mpn:
        filters.append(Product.mpn == payload.mpn)
    if payload.upc:
        filters.append(Product.upc == payload.upc)
    return filters


async def _find_existing_product(
    db: AsyncSession, tenant_id: int, filters: list
) -> Optional[Product]:
    if not filters:
        return None
    stmt = (
        select(Product)
        .options(selectinload(Product.brand))
        .where(Product.tenant_id == tenant_id, or_(*filters))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_recent_cached_chat(db: AsyncSession, product_id: int) -> Optional[Chat]:
    threshold = datetime.now() - timedelta(days=RETENTION_DAYS_THRESHOLD)
    stmt = (
        select(Chat)
        .where(Chat.product_id == product_id, Chat.created_at >= threshold)
        .order_by(Chat.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _enrich_missing_product_metadata(
    payload: GEOAuditRequest,
) -> ProductEnrichment:
    """Ask an LLM to fill in baseline metadata for a product we don't have on file yet."""
    prompt = f"""
        You are a real-time web crawler agent. Analyze the following product metadata footprints:

        Product Name: {payload.product_name}
        Product URL: {payload.product_url}
        SKU: {payload.sku} | MPN: {payload.mpn} | UPC: {payload.upc}
        Extra Context: {payload.extra_context}

        CRITICAL ASSIGNMENT DIRECTIONS:
        1. Estimate or look up real-world search index results for this item.
        2. Natively determine non-zero values for 'no_of_faqs' and 'no_of_reviews'.
        3. If this exact SKU/MPN item has a low digital footprint in your training data, pull baseline statistics from similar marine/e-commerce category listings (e.g., popular 2.7m inflatable boat tenders usually carry 3-5 FAQs and 5-15 customer reviews across marine chandlery networks).
        4. Strictly DO NOT return 0 or null for these metric fields. Provide your best contextual evaluation value.
    """
    try:
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(GEO_TOOLS)
        return await model.with_structured_output(ProductEnrichment).ainvoke(prompt)
    except Exception:
        return ProductEnrichment()


async def _get_or_create_brand(
    db: AsyncSession,
    tenant_id: int,
    brand_name: str,
    country: str,
    user_id: Optional[int],
) -> Brand:
    stmt = select(Brand).where(Brand.name == brand_name, Brand.tenant_id == tenant_id)
    result = await db.execute(stmt)
    brand_record = result.scalar_one_or_none()
    if brand_record:
        return brand_record

    brand_record = Brand(
        tenant_id=tenant_id, name=brand_name, country=country, created_by=user_id
    )
    db.add(brand_record)
    await db.flush()
    return brand_record


async def _create_new_product(
    db: AsyncSession, payload: GEOAuditRequest, tenant_id: int, user_id: Optional[int]
) -> Product:
    enriched = await _enrich_missing_product_metadata(payload)

    product_name = (
        payload.product_name
        or enriched.product_name
        or f"Unknown Product {datetime.now().timestamp()}"
    )
    brand_name = enriched.brand_name or product_name
    country = payload.country or enriched.country or "Unknown"

    brand_record = await _get_or_create_brand(
        db, tenant_id, brand_name, country, user_id
    )

    product_record = Product(
        tenant_id=tenant_id,
        brand_id=brand_record.id,
        name=product_name,
        brand_name=brand_name,
        model_choice=LLMModels.GPT,
        sku=payload.sku,
        mpn=payload.mpn,
        upc=payload.upc,
        no_of_faqs=enriched.no_of_faqs,
        no_of_reviews=enriched.no_of_reviews,
        created_by=user_id,
    )
    db.add(product_record)
    await db.flush()
    return product_record


# ======================================================================
# LLM / MODEL-RUN HELPERS
# ======================================================================


def _build_chat_model(model_name: str):
    """Instantiate the right LangChain chat model for a given LLMModels value."""
    if model_name == "GPT":
        return ChatOpenAI(model="gpt-5-nano", temperature=0)
    if model_name == "GEMINI":
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    return ChatAnthropic(model="claude-haiku-4-5", temperature=0)


async def _run_single_model_audit(
    model_name: str, user_prompt: str
) -> Optional[UnifiedGEOResponse]:
    llm = _build_chat_model(model_name)
    structured_llm = llm.with_structured_output(UnifiedGEOResponse)
    # NOTE: previously GEO_SYSTEM_PROMPT was defined but never actually sent to the
    # model. Wiring it in here as the system message so the schema/formatting rules
    # it describes are actually enforced.
    return await structured_llm.ainvoke(
        [("system", GEO_SYSTEM_PROMPT), ("human", user_prompt)]
    )


# ======================================================================
# PERSISTENCE HELPERS
# ======================================================================


def _build_chat_record(
    tenant_id: int,
    product_id: int,
    payload: GEOAuditRequest,
    model_enum: LLMModels,
    structured: UnifiedGEOResponse,
) -> Chat:
    return Chat(
        tenant_id=tenant_id,
        product_id=product_id,
        product_name=payload.product_name or "",
        product_url=payload.product_url or payload.website or "",
        extra_context=payload.extra_context,
        model_choice=model_enum,
        competitor_analytics=[
            c.model_dump(mode="json") for c in structured.competitor_analytics
        ],
        final_optimization_report=structured.final_optimized_tips_summary,
    )


def _build_search_query_records(
    chat_id: int, queries: list[ChatQueryBase]
) -> list[ChatSearchQuery]:
    """
    NOTE: this now writes a `competitor_products` field (list of
    {competitor_name, product_name, product_url, price} dicts) alongside the
    existing `competitors_mentioned` list. The ChatSearchQuery model/table needs
    a matching `competitor_products` JSON column added via migration for this
    to persist - see explanation below.
    """
    return [
        ChatSearchQuery(
            chat_id=chat_id,
            chat_context=query.chat_context,
            brand_name=query.brand,
            query_text=query.query,
            product_found=query.product_found,
            share_of_voice=min(query.share_of_voice, 100.0),
            total_websites_found=query.total_websites_found,
            citation_rank=query.citation_rank,
            platform_breakdown=query.platform_breakdown.model_dump(mode="json"),
            best_metrics_variance={},
            raw_api_response=json.dumps(query.model_dump(mode="json")),
            citing_sources=query.citing_sources,
            competitors_mentioned=query.competitors_mentioned,
            competitor_products=[
                p.model_dump(mode="json") for p in query.competitor_products
            ],
            query_optimization_tag=query.optimization_tag,
            query_optimization_tips=query.optimization_tips_for_better_result,
            solution=query.copy_pasteable_solution,
        )
        for query in queries
    ]


def _build_audit_record(
    tenant_id: int,
    identifier: str,
    model_name: str,
    structured: Optional[UnifiedGEOResponse],
) -> ChatGEOAuditRecord:
    return ChatGEOAuditRecord(
        tenant_id=tenant_id,
        product_identifier=identifier,
        model_used=model_name,
        status="SUCCESS",
        audit_data=structured.model_dump(mode="json") if structured else {},
    )


def _resolve_identifier(payload: GEOAuditRequest) -> str:
    return (
        payload.product_name
        or payload.sku
        or payload.product_url
        or "Unknown Meta Query"
    )


# ======================================================================
# MAIN ENTRYPOINT
# ======================================================================


async def run_geo_audit_stream(
    payload: GEOAuditRequest,
    db: AsyncSession,
    tenant_id: int,
    user_id: int | None = None,
) -> AsyncGenerator[str, None]:
    try:
        if tenant_id is None:
            yield _emit(color="red", status="failed", message="tenant_id is required.")
            return

        if payload is None:
            yield _emit(
                color="red", status="failed", message="Payload cannot be empty."
            )
            return

        yield _status("Checking product registry...", 5)

        lookup_filters = _build_lookup_filters(payload)

        if not lookup_filters and not payload.product_url:
            yield _emit(
                type="error",
                color="#ef4444",
                status="failed",
                message="One identifier is required (product_name/sku/mpn/upc/product_url)",
            )
            return

        product_record = await _find_existing_product(db, tenant_id, lookup_filters)

        if product_record:
            product_id = product_record.id
            yield _status("Existing product located", 10)

            recent_chat = await _get_recent_cached_chat(db, product_id)
            if recent_chat:
                yield _result("Warm cache hit", recent_chat.final_optimization_report)
                return
        else:
            yield _status("Enriching missing product metadata...", 15)
            product_record = await _create_new_product(db, payload, tenant_id, user_id)
            product_id = product_record.id

        user_prompt = build_user_instruction_v2(payload)
        identifier = _resolve_identifier(payload)

        models = list(LLMModels)
        total_models = len(models)
        all_reports = []

        for index, model_enum in enumerate(models):
            model_name = model_enum.value
            progress_start = int((index / total_models) * 100)

            yield _status(
                f"Configuring runtime pool engine: '{model_name}'...", progress_start
            )

            try:
                yield _status(
                    f"[{model_name}] Extracting payload identifier strings...",
                    progress_start + 10,
                )
                yield _status(
                    f"[{model_name}] Invoking context analysis tracing...",
                    progress_start + 20,
                )

                structured = await _run_single_model_audit(model_name, user_prompt)

                if structured:
                    structured.model_used = model_name
                    if structured.product_details:
                        product_record.no_of_faqs = structured.product_details.faqs
                        product_record.no_of_reviews = (
                            structured.product_details.reviews
                        )

                yield _status(
                    f"[{model_name}] Recording PostgreSQL logs...", progress_start + 30
                )

                if structured:
                    chat_record = _build_chat_record(
                        tenant_id, product_id, payload, model_enum, structured
                    )
                    db.add(chat_record)
                    await db.flush()  # need chat_record.id before building search queries

                    for search_record in _build_search_query_records(
                        chat_record.id, structured.queries_executed
                    ):
                        db.add(search_record)

                    db.add(
                        _build_audit_record(
                            tenant_id, identifier, model_name, structured
                        )
                    )

                await db.commit()

                if structured:
                    all_reports.append(structured.model_dump(mode="json"))

                yield _emit(
                    status="progress",
                    progress_pct=int(((index + 1) / total_models) * 100),
                    message=f"{model_name} completed successfully.",
                )

                if all_reports:
                    yield _result(
                        "GEO audit completed successfully",
                        all_reports[-1]["final_optimized_tips_summary"],
                    )

            except Exception as model_error:
                await db.rollback()
                yield _model_warning(model_name, model_error)

    except Exception as e:
        await db.rollback()
        yield json.dumps({"status": "failed", "message": str(e)}) + "\n"
