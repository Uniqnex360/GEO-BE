"""
Pydantic schemas for GEO audit requests, LLM structured outputs, and
internal enrichment payloads.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.models.base import LLMModels

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
    product_url: str = Field(
        default="",
        description=(
            "Verified competitor product page URL resolved directly from SerpApi. "
            "Never fabricate or construct this URL."
        ),
    )
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
        description=(
            "Exact verified canonical URL of the competitor product page. "
            "Never fabricate, infer, rewrite, or guess the URL. "
            "Only use a URL explicitly returned by a trusted search result. "
            'If unavailable, return "".'
        )
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


class Citation(BaseModel):
    source: str = Field(
        default="",
        description="Name of the website or publication that cited/referenced the product.",
    )
    url: str = Field(
        default="",
        description="Exact verified URL of the source page. Never fabricate, guess, or construct URLs.",
    )
    quote: str = Field(
        default="",
        description="The relevant excerpt or statement from the source referencing the product.",
    )
    trust: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Trust/authority score of the citation source from 0 to 10.",
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
    product_found: bool = Field(description="True if target product/brand was discovered.")
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

    optimization_tips_for_better_result: str = Field(
        description=(
            "Strategic GEO suggestion explaining WHERE and WHAT to optimize. "
            "Identifies the target field/section and the high-level fix required "
            "(e.g., adjusting price positioning, adding local relevance, tweaking title structure, "
            "or recommending a new FAQ section if none exists on the product page). "
            "BAD: Do not supply the finished copy here-keep this focused purely on the strategy/location."
        )
    )

    copy_pasteable_solution: str = Field(
        description=(
            "The exact, finished, copy-pasteable text, example title, or full FAQ section implementing the suggestion. "
            "Never stop at naming the fix-always supply the literal text ready for deployment. "
            "IF THE PRODUCT PAGE LACKS AN FAQ SECTION: Create and supply a complete, production-ready Q&A block here "
            "addressing common consumer query gaps. "
            "Examples: 'For a lower-cost option, see the Pilot G2 at $2.50.' or "
            "'Q: Is this pen refillable? A: Yes, it accepts standard G2 gel refills.'"
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
    citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "Verified external sources cited when referencing the target product. "
            "Each citation must contain the source name, exact verified URL, "
            "relevant quote, and trust score."
        ),
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


class ProductEnrichment(BaseModel):
    """Best-effort metadata inferred for a product that isn't in our database yet.

    NOTE: previously these two counters defaulted to `None` while typed as
    `int`, which is a schema/type mismatch (and meant "unknown" silently
    became `None` instead of a real int). They now default to `0` and are
    correctly typed as plain `int`.
    """

    product_name: Optional[str] = None
    brand_name: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    no_of_faqs: int = Field(
        default=0,
        description="Estimated number of FAQs for this item. CRITICAL: Do not return 0; if unknown, estimate a realistic baseline count based on product type.",
    )
    no_of_reviews: int = Field(
        default=0,
        description="Estimated number of customer reviews for this item. CRITICAL: Do not return 0; if unknown, estimate a realistic baseline count based on product type.",
    )
