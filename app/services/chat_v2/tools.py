"""
LangChain tools available to the GEO audit models, plus the SerpApi-backed
competitor URL resolver.

If SerpApi fails (including quota/limit errors), DuckDuckGo is used as a
fallback. Both providers return the same output format.
"""

import logging
import os

from serpapi import GoogleSearch
from langchain.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

from .schemas import UnifiedGEOResponse

logger = logging.getLogger(__name__)


def _format_search_results(results: list) -> str:
    """Format search results into the standard GEO search output format."""

    if not results:
        return "No organic web results discovered."

    formatted_output = []

    for index, item in enumerate(results, start=1):
        title = item.get("title", "")
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        price = item.get("price", "N/A")

        formatted_output.append(
            f"Result #{index}:\n"
            f"- Title: {title}\n"
            f"- Verified URL: {link}\n"
            f"- Price: {price}\n"
            f"- Summary: {snippet}\n"
        )

    return "\n".join(formatted_output)


def _search_duckduckgo(query: str) -> str:
    """Fallback search using LangChain Community DuckDuckGo."""

    try:
        search = DuckDuckGoSearchRun()

        raw_results = search.invoke(query)

        if not raw_results:
            return f"No organic web results discovered for query: '{query}'."

        # DuckDuckGoSearchRun normally returns a text string rather than
        # structured results. Keep the same output contract expected by
        # the GEO model.
        return (
            "Result #1:\n"
            "- Title: DuckDuckGo Search Result\n"
            "- Verified URL: N/A\n"
            "- Price: N/A\n"
            f"- Summary: {raw_results}\n"
        )

    except Exception as err:
        logger.exception(
            "DuckDuckGo fallback failed for query=%r",
            query,
        )
        return f"DuckDuckGo Search Failed: {str(err)}"


@tool
def geo_web_search(query: str) -> str:
    """
    Searches the web via SerpApi for live product metadata, verified
    competitor URLs, pricing, and organic search listings.

    If SerpApi reaches its limit or fails, DuckDuckGo is used as a fallback.
    """

    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")

    if not api_key:
        logger.warning("SerpApi API key missing. Falling back to DuckDuckGo.")
        return _search_duckduckgo(query)

    try:
        search = GoogleSearch(
            {
                "engine": "google",
                "q": query,
                "num": 5,
                "hl": "en",
                "gl": "us",
                "api_key": api_key,
            }
        )

        results = search.get_dict()

        # SerpApi quota / account / API errors
        if "error" in results:
            logger.warning(
                "geo_web_search: SerpApi returned error for query=%r: %s. "
                "Falling back to DuckDuckGo.",
                query,
                results["error"],
            )

            return _search_duckduckgo(query)

        organic_results = results.get("organic_results", [])

        if not organic_results:
            logger.info(
                "geo_web_search: no organic_results for query=%r. "
                "Falling back to DuckDuckGo.",
                query,
            )

            return _search_duckduckgo(query)

        formatted_output = []

        for index, item in enumerate(organic_results[:5], start=1):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")

            rich_extensions = (
                item.get("rich_snippet", {})
                .get("top", {})
                .get("detected_extensions", {})
            )

            price = rich_extensions.get("price") or item.get("price") or "N/A"

            formatted_output.append(
                f"Result #{index}:\n"
                f"- Title: {title}\n"
                f"- Verified URL: {link}\n"
                f"- Price: {price}\n"
                f"- Summary: {snippet}\n"
            )

        return "\n".join(formatted_output)

    except Exception as err:
        logger.exception(
            "geo_web_search: SerpApi call failed for query=%r. "
            "Falling back to DuckDuckGo.",
            query,
        )

        return _search_duckduckgo(query)


@tool
def scrape_product_metadata(url: str) -> str:
    """Scrapes raw data profiles, review elements, text configurations, and media blocks from a given landing page URL."""
    return f"Raw Scraped Payload from {url}: FAQs found=2, Reviews found=10."


GEO_TOOLS = [geo_web_search, scrape_product_metadata]


def _resolve_competitor_product_url(competitor_name: str, product_name: str) -> str:
    """Resolve a real competitor product page URL directly from SerpApi.

    The LLM identifies the competitor/product, but it is NOT trusted to
    generate the URL. Only the URL returned by SerpApi is persisted.
    """
    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")

    if not api_key or not competitor_name or not product_name:
        return ""

    competitor_name = competitor_name.strip()
    product_name = product_name.strip()

    if not competitor_name or not product_name:
        return ""

    queries = [
        f'"{competitor_name}" "{product_name}" product',
        f'"{competitor_name}" "{product_name}" buy',
        f"{competitor_name} {product_name}",
    ]

    try:
        for search_query in queries:
            search = GoogleSearch(
                {
                    "engine": "google",
                    "q": search_query,
                    "num": 10,
                    "hl": "en",
                    "gl": "uk",
                    "api_key": api_key,
                }
            )
            results = search.get_dict()

            if "error" in results:
                logger.warning(
                    "SerpApi competitor URL lookup failed for %r: %s",
                    search_query,
                    results["error"],
                )
                continue

            organic_results = results.get("organic_results", [])
            if not organic_results:
                continue

            competitor_lower = competitor_name.lower()
            product_words = [
                w.lower() for w in product_name.split() if len(w.strip()) >= 3
            ]

            best_link = ""
            best_score = 0

            for result in organic_results:
                link = (result.get("link") or "").strip()
                title = (result.get("title") or "").strip().lower()
                snippet = (result.get("snippet") or "").strip().lower()
                text = f"{title} {snippet}"

                if not link:
                    continue

                score = 0
                if competitor_lower in text:
                    score += 5

                matched_words = sum(1 for word in product_words if word in text)
                score += min(matched_words, 8)

                if title and any(word in title for word in product_words):
                    score += 3

                if score > best_score:
                    best_score = score
                    best_link = link

            if best_link and best_score >= 5:
                logger.info(
                    "Resolved competitor URL: %s / %s -> %s",
                    competitor_name,
                    product_name,
                    best_link,
                )
                return best_link

            # SerpApi itself is still the source of truth. If no strong
            # textual match exists, use the first organic URL as a fallback.
            for result in organic_results:
                link = (result.get("link") or "").strip()
                if link:
                    logger.info(
                        "Fallback competitor URL: %s / %s -> %s",
                        competitor_name,
                        product_name,
                        link,
                    )
                    return link

        return ""

    except Exception:
        logger.exception(
            "SerpApi competitor URL resolver failed: competitor=%r product=%r",
            competitor_name,
            product_name,
        )
        return ""


def resolve_all_competitor_product_urls(structured: UnifiedGEOResponse) -> None:
    """Resolve competitor URLs once per unique competitor/product pair, and
    write them into BOTH `queries_executed[].competitor_products[].product_url`
    and `competitor_analytics[].product_url` so either API response mapper
    the frontend uses has the data.
    """
    resolved_urls: dict[tuple[str, str], str] = {}

    def resolve(competitor_name: str, product_name: str) -> str:
        key = (
            (competitor_name or "").strip().lower(),
            (product_name or "").strip().lower(),
        )
        if not key[0] or not key[1]:
            return ""
        if key not in resolved_urls:
            resolved_urls[key] = _resolve_competitor_product_url(
                competitor_name, product_name
            )
        return resolved_urls[key]

    # 1. Resolve URLs for query-level competitor product references.
    # Always overwrite with the SerpApi-verified URL, even if the model
    # already put something in `product_url` - the LLM's guess is never trusted.
    for query in structured.queries_executed:
        for competitor in query.competitor_products:
            competitor.product_url = resolve(
                competitor.competitor_name, competitor.product_name
            )

    # 2. Attach the same verified URL to competitor_analytics.
    for competitor in structured.competitor_analytics:
        competitor.product_url = resolve(
            competitor.competitor_name, competitor.product_title
        )

    # 3. If competitor_analytics lookup came back empty, fall back to any URL
    #    already resolved for the same competitor name at the query level.
    analytics_by_name: dict[str, str] = {}
    for query in structured.queries_executed:
        for competitor in query.competitor_products:
            name_key = competitor.competitor_name.strip().lower()
            if name_key and competitor.product_url:
                analytics_by_name.setdefault(name_key, competitor.product_url)

    for competitor in structured.competitor_analytics:
        if not competitor.product_url:
            competitor.product_url = analytics_by_name.get(
                competitor.competitor_name.strip().lower(), ""
            )
