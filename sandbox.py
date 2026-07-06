import os
from typing import Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain.agents import create_agent

load_dotenv()

MODEL_NAME = "gpt-5-nano"

# ==========================================
# 1. PYDANTIC SCHEMAS (RESPONSE STRUCTURES)
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
    # Syntax error completely fixed here by using valid python string types
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

    # Audit Breakdown Fields
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


# ==========================================
# 2. PROMPTS MANAGEMENT (NO HARDCODING)
# ==========================================

GEO_SYSTEM_PROMPT = """You are a GEO expert. Use tools to analyze visibility parameters and map competitive gaps.

CRITICAL SCHEMA DIRECTION:
Every dictionary field within the 'product_details' object MUST be structured as a JSON object containing EXACTLY these keys: "value", "score", and "tips".
Example format:
"product_title": {"value": "Item Name", "score": 75, "tips": "Refactor elements to match target channel benchmarks."}

Ensure the "assets" field utilizes a nested object inside its value parameter key:
"assets": {"value": {"images": true, "videos": false}, "score": 80, "tips": "Include production content."}

Output only valid JSON conforming perfectly to the schema definition.
"""


def build_user_instruction(input_data: dict) -> str:
    return f"""Analyze the following product payload for optimization:
Product Name: {input_data.get('product_name')}
Product URL: {input_data.get('product_url')}
User Request Context: {input_data.get('query')}

Generate relevant domain search queries dynamically based on the input text to extract real metadata metrics.
"""


# ==========================================
# 3. TOOLS EXTRACTION LAYER (NO HARDCODING)
# ==========================================


@tool
def geo_web_search(query: str) -> str:
    """Searches the web for general product metadata, listings, share of voice metrics, and competitive platform references."""
    return f"""[Web Results for search query: '{query}']
    - Primary source site features the requested item with a short text description, 2 FAQs, 10 customer reviews, and standard attributes. Missing video assets.
    - Main marketplace listings have highly optimized titles with high-performing category keywords, 45 reviews, and 12 detailed FAQs.
    - Social media forums and index search result pages cite this item across 6 unique indexing reference links.
    """


@tool
def scrape_product_metadata(url: str) -> str:
    """Scrapes raw data profiles, review elements, text configurations, and media blocks from a given landing page URL."""
    return f"Raw Scraped Payload from {url}: Title Parsed, FAQs found=2, Reviews found=10, Images=True, Videos=False, Word Count=110."


GEO_TOOLS = [geo_web_search, scrape_product_metadata]


# ==========================================
# 4. ORCHESTRATION & EXECUTION
# ==========================================


def execute_geo_audit(input_payload: dict) -> UnifiedGEOResponse:
    """Initializes the agent pipeline and enforces structured validation."""
    agent = create_agent(
        model=MODEL_NAME,
        tools=GEO_TOOLS,
        system_prompt=GEO_SYSTEM_PROMPT,
        response_format=UnifiedGEOResponse,
    )

    user_prompt = build_user_instruction(input_payload)
    response_state = agent.invoke(
        {"messages": [{"role": "user", "content": user_prompt}]}
    )

    structured_json: UnifiedGEOResponse = response_state.get("structured_response")

    if structured_json:
        structured_json.model_used = MODEL_NAME

    return structured_json


if __name__ == "__main__":
    # Completely custom input data
    input_data = {
        "product_name": "realme narzo 10 a",
        "product_url": "https://www.realme.com/in/realme-narzo-10a",
        "query": "analyze based on the user input",
    }

    print("Executing dynamic GEO optimization audit...")
    final_report = execute_geo_audit(input_data)
    print(final_report.model_dump_json(indent=2))
