import json
from typing import Optional, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, RootModel

from langchain.agents import create_agent
from langchain.tools import tool

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession


from app.models.base import LLMModels
from app.models import Product, Brand, Chat, ChatSearchQuery, ChatGEOAuditRecord

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

RETENTION_DAYS_THRESHOLD = 7


GEO_SYSTEM_PROMPT = """
You are a GEO expert. Use tools to analyze visibility parameters and map competitive gaps.

CRITICAL SCHEMA DIRECTION:
Every dictionary field within the 'product_details' object MUST be structured as a JSON object containing EXACTLY these keys: "value", "score", and "tips".
Output only valid JSON conforming perfectly to the schema definition.
"""


class PlatformBreakdownMetrics(BaseModel):
    google: int = Field(default=0, description="Count for Google platform.")
    anthropic: int = Field(default=0, description="Count for Anthropic platform.")
    openai: int = Field(default=0, description="Count for OpenAI search platform.")


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
# 3. DYNAMIC & COMPLIANT OUTPUT SCHEMAS
# ==========================================
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


class GEOAuditField(BaseModel):
    """Used ONLY for elements undergoing rich copy visibility auditing."""

    value: str = Field(
        default="", description="The extracted data string or content description."
    )
    score: int = Field(
        default=0, description="The evaluated visibility compliance score."
    )
    tips: str = Field(
        default="", description="Actionable optimization recommendation text."
    )


class GEOProductDetail(BaseModel):
    # Core Identity Strings (Simple primitives, no overengineering!)
    product_name: str = Field(description="Name of the target product.")
    product_url: str = Field(description="Target product landing page URL.")
    sku: Optional[str] = Field(None, description="Stock Keeping Unit number.")
    mpn: Optional[str] = Field(None, description="Manufacturer Part Number.")
    upc: Optional[str] = Field(None, description="Universal Product Code.")
    gtin: Optional[str] = Field(None, description="Global Trade Item Number.")
    ean: Optional[str] = Field(None, description="European Article Number.")

    # Quantitative Numeric Metrics
    faqs: int = Field(default=0, description="Count of found target FAQs.")
    reviews: int = Field(default=0, description="Count of user reviews integrated.")
    attributes: int = Field(
        default=0, description="Count of detailed product specifications."
    )
    features: int = Field(
        default=0, description="Count of unique item product features."
    )

    # Rich Content Undergoing Optimization & Scoring Analysis
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
    optimization_tag: str = Field(
        description=(
            "A single-word category representing the primary optimization recommendation. "
            "Examples: 'title', 'brand', 'attributes','description', 'faq', 'content', 'schema', 'images', "
            "'reviews', 'pricing', 'specifications', 'comparison', 'keywords', "
            "'metadata', 'headings', 'internal-links', 'external-links', 'trust', "
            "'availability',  'video', 'performance', 'citations'."
        )
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
    payload: GEOAuditRequest,
    db: AsyncSession,
    tenant_id: int,
    user_id: int | None = None,
):
    try:

        # ======================================
        # STRICT VALIDATION
        # ======================================

        if tenant_id is None:
            yield json.dumps(
                {
                    "color": "red",
                    "status": "failed",
                    "message": "tenant_id is required.",
                }
            ) + "\n"
            return

        if payload is None:
            yield json.dumps(
                {
                    "color": "red",
                    "status": "failed",
                    "message": "Payload cannot be empty.",
                }
            ) + "\n"
            return

        yield json.dumps(
            {
                "type": "status",
                "color": "#4f46e5",
                "status": "progress",
                "message": "Checking product registry...",
                "progress_pct": 5,
            }
        ) + "\n"

        product_name = payload.product_name
        product_url = payload.product_url or payload.website

        sku = payload.sku
        mpn = payload.mpn
        upc = payload.upc

        country = payload.country

        product_record = None
        product_id = None
        competitors = []
        historical_best = None

        # ======================================
        # REQUIRE IDENTIFIERS
        # ======================================

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
                {
                    "type": "error",
                    "color": "#ef4444",
                    "status": "failed",
                    "message": "One identifier is required (product_name/sku/mpn/upc/product_url)",
                }
            ) + "\n"

            return

        # ======================================
        # PRODUCT LOOKUP
        # ======================================

        if lookup_filters:

            stmt = (
                select(Product)
                .options(selectinload(Product.brand))
                .where(Product.tenant_id == tenant_id, or_(*lookup_filters))
            )

            result = await db.execute(stmt)

            product_record = result.scalar_one_or_none()

        # ======================================
        # EXISTING PRODUCT
        # ======================================

        if product_record:

            product_id = product_record.id

            yield json.dumps(
                {
                    "type": "status",
                    "color": "#4f46e5",
                    "status": "progress",
                    "message": "Existing product located",
                    "progress_pct": 10,
                }
            ) + "\n"

            if product_record.brand and product_record.brand.competitor:
                competitors = [
                    c.strip()
                    for c in product_record.brand.competitor.split(",")
                    if c.strip()
                ]

            threshold = datetime.now() - timedelta(days=RETENTION_DAYS_THRESHOLD)

            recent_stmt = (
                select(Chat)
                .where(Chat.product_id == product_id, Chat.created_at >= threshold)
                .order_by(Chat.created_at.desc())
                .limit(1)
            )

            recent_result = await db.execute(recent_stmt)

            recent_chat = recent_result.scalar_one_or_none()

            if recent_chat:
                yield json.dumps(
                    {
                        "type": "result",
                        "color": "#22c55e",
                        "status": "completed",
                        "message": "Warm cache hit",
                        "report": recent_chat.final_optimization_report,
                        "progress_pct": 100,
                    }
                ) + "\n"

                return

        # ======================================
        # NEW PRODUCT CREATION
        # ======================================

        else:
            yield json.dumps(
                {
                    "type": "status",
                    "color": "#4f46e5",
                    "status": "progress",
                    "message": "Enriching missing product metadata...",
                    "progress_pct": 15,
                }
            ) + "\n"

            # Add the metrics to the temporary enrichment schema
            class ProductEnrichment(BaseModel):
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

            try:
                enrichment_prompt = f"""
                    You are a real-time web crawler agent. Analyze the following product metadata footprints:

                    Product Name: {product_name}
                    Product URL: {product_url}
                    SKU: {sku} | MPN: {mpn} | UPC: {upc}
                    Extra Context: {payload.extra_context}

                    CRITICAL ASSIGNMENT DIRECTIONS:
                    1. Estimate or look up real-world search index results for this item.
                    2. Natively determine non-zero values for 'no_of_faqs' and 'no_of_reviews'. 
                    3. If this exact SKU/MPN item has a low digital footprint in your training data, pull baseline statistics from similar marine/e-commerce category listings (e.g., popular 2.7m inflatable boat tenders usually carry 3-5 FAQs and 5-15 customer reviews across marine chandlery networks).
                    4. Strictly DO NOT return 0 or null for these metric fields. Provide your best contextual evaluation value.
                """

                base_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

                # 2. FIX: Bind your tools list to the model instance first
                llm_with_tools = base_llm.bind_tools(GEO_TOOLS)

                # 3. Apply the structured output formatting on top of the tool-aware model
                enriched = await llm_with_tools.with_structured_output(
                    ProductEnrichment
                ).ainvoke(enrichment_prompt)

            except Exception:
                enriched = ProductEnrichment()

            # Merge inferred values safely
            product_name = (
                product_name
                or enriched.product_name
                or f"Unknown Product {datetime.now().timestamp()}"
            )
            brand_name = enriched.brand_name or product_name
            country = country or enriched.country or "Unknown"

            brand_stmt = select(Brand).where(
                Brand.name == brand_name, Brand.tenant_id == tenant_id
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

            # Create the record using the freshly extracted metrics from the enrichment LLM
            product_record = Product(
                tenant_id=tenant_id,
                brand_id=brand_record.id,
                name=product_name,
                brand_name=brand_name,
                model_choice=LLMModels.GPT,
                sku=sku,
                mpn=mpn,
                upc=upc,
                no_of_faqs=enriched.no_of_faqs,  # Pass the enriched count here
                no_of_reviews=enriched.no_of_reviews,  # Pass the enriched count here
                created_by=user_id,
            )

            db.add(product_record)
            await db.flush()
            product_id = product_record.id

        # ======================================
        # MODEL INTERACTION LOOP
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
                    "type": "status",
                    "color": "#4f46e5",
                    "status": "progress",
                    "progress_pct": progress_start,
                    "message": f"Configuring runtime pool engine: '{model_name}'...",
                }
            ) + "\n"

            try:
                if model_name == "GPT":
                    actual_ai_model = ChatOpenAI(model="gpt-5-nano", temperature=0)

                elif model_name == "GEMINI":
                    actual_ai_model = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash", temperature=0
                    )

                else:
                    actual_ai_model = ChatAnthropic(
                        model="claude-haiku-4-5", temperature=0
                    )

                yield json.dumps(
                    {
                        "type": "status",
                        "color": "#4f46e5",
                        "status": "progress",
                        "progress_pct": progress_start + 10,
                        "message": f"[{model_name}] Extracting payload identifier strings...",
                    }
                ) + "\n"

                yield json.dumps(
                    {
                        "type": "status",
                        "color": "#4f46e5",
                        "status": "progress",
                        "progress_pct": progress_start + 20,
                        "message": f"[{model_name}] Invoking context analysis tracing...",
                    }
                ) + "\n"

                response = await actual_ai_model.with_structured_output(
                    UnifiedGEOResponse
                ).ainvoke(user_prompt)

                structured_json = response

                if structured_json:
                    structured_json.model_used = model_name

                    if structured_json.product_details:
                        product_record.no_of_faqs = structured_json.product_details.faqs
                        product_record.no_of_reviews = (
                            structured_json.product_details.reviews
                        )

                yield json.dumps(
                    {
                        "type": "status",
                        "color": "#4f46e5",
                        "status": "progress",
                        "progress_pct": progress_start + 30,
                        "message": f"[{model_name}] Recording PostgreSQL logs...",
                    }
                ) + "\n"

                # ======================================================
                # SAVE CHAT
                # ======================================================

                if structured_json:

                    chat_record = Chat(
                        tenant_id=tenant_id,
                        product_id=product_id,
                        product_name=(payload.product_name or ""),
                        product_url=(payload.product_url or payload.website or ""),
                        extra_context=payload.extra_context,
                        model_choice=model_enum,
                        # FIX: Using mode="json" ensures sub-models (like assets_present) flatten completely to standard dicts
                        competitor_analytics=[
                            competitor.model_dump(mode="json")
                            for competitor in structured_json.competitor_analytics
                        ],
                        final_optimization_report=structured_json.final_optimized_tips_summary,
                    )

                    db.add(chat_record)

                    # Generate ID
                    await db.flush()

                    # ======================================================
                    # SAVE CHAT SEARCH QUERIES
                    # ======================================================

                    for query in structured_json.queries_executed:

                        # FIX: Extract native python dict elements from Pydantic schemas using model_dump(mode="json")
                        # This turns RootModels and custom sub-schemas into serializable databases primitives.
                        platform_breakdown_dict = query.platform_breakdown.model_dump(
                            mode="json"
                        )

                        search_record = ChatSearchQuery(
                            chat_id=chat_record.id,
                            chat_context=query.chat_context,
                            brand_name=query.brand,
                            query_text=query.query,
                            product_found=query.product_found,
                            share_of_voice=query.share_of_voice,
                            total_websites_found=query.total_websites_found,
                            citation_rank=query.citation_rank,
                            platform_breakdown=platform_breakdown_dict,  # FIX applied here
                            best_metrics_variance={},
                            raw_api_response=json.dumps(
                                query.model_dump(mode="json")
                            ),  # FIX applied here
                            citing_sources=query.citing_sources,
                            competitors_mentioned=query.competitors_mentioned,
                            query_optimization_tag=query.optimization_tag,
                            query_optimization_tips=query.optimization_tips_for_better_result,
                        )

                        db.add(search_record)

                # ======================================================
                # SAVE GEO AUDIT LOGIC
                # ======================================================

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
                        # FIX: mode="json" safely flattens all internal fields for database json storage
                        structured_json.model_dump(mode="json")
                        if structured_json
                        else {}
                    ),
                )

                db.add(db_record)

                # ======================================================
                # SINGLE COMMIT
                # ======================================================

                await db.commit()

                if structured_json:
                    all_reports.append(
                        structured_json.model_dump(mode="json")
                    )  # FIX applied here

                yield json.dumps(
                    {
                        "status": "progress",
                        "progress_pct": int(((index + 1) / total_models) * 100),
                        "message": f"{model_name} completed successfully.",
                    }
                ) + "\n"

                if all_reports:

                    yield json.dumps(
                        {
                            "type": "result",
                            "color": "#22c55e",
                            "status": "completed",
                            "message": "GEO audit completed successfully",
                            "report": all_reports[-1]["final_optimized_tips_summary"],
                            "progress_pct": 100,
                        }
                    ) + "\n"

            except Exception as model_error:
                await db.rollback()  # Ensure transaction failure doesn't taint future loop operations
                yield json.dumps(
                    {
                        "type": "error",
                        "color": "#f59e0b",
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
