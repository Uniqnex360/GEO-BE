"""
product_page_extractor.py
==========================

One-time product page extraction for the GEO audit pipeline.

Drop this file in next to your existing GEO audit code and call
`extract_product_page_once(url)` ONCE per product, near the start of the
audit flow. Reuse the returned dict for GPT / Gemini / Claude audits,
content-gap analysis, and recommendations. Do NOT re-scrape per model.

Pipeline
--------
Product URL
    -> fetch HTML (httpx, Playwright fallback for JS-heavy pages)
    -> extract JSON-LD (before stripping scripts)
    -> strip script/style/nav/footer/header/aside/svg/etc.
    -> extract semantic DOM blocks (tag/class/id/style are SIGNALS, not rules)
    -> dedupe lines
    -> priority-ranked compaction to a char budget (~16k-20k)
    -> ONE OpenAI call with structured output (Pydantic) -> ProductPageContent
    -> deterministic analytics + content gaps computed locally, never by the LLM
    -> (optional) DuckDuckGo fallback lookup for a couple of missing signals
    -> final dict, ready to store in Product.actual_content (JSONB) and reuse

Requirements
------------
pip install httpx beautifulsoup4 pydantic openai duckduckgo-search
# Optional, only if you truly need JS-rendered pages:
pip install playwright && playwright install chromium

Environment
-----------
OPENAI_API_KEY must be set for the extraction call.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from pydantic import BaseModel, Field

logger = logging.getLogger("product_page_extractor")
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

MAX_LLM_PAGE_CHARS = 18000  # upper limit, not a target
MIN_BLOCK_TEXT_LEN = 10
REQUEST_TIMEOUT_SECONDS = 150.0
OPENAI_MODEL = "gpt-4o-mini"  # cheap + supports structured outputs; swap as needed

REMOVE_TAGS = [
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "template",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
]

SEMANTIC_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "div",
    "span",
    "li",
    "table",
    "tr",
    "td",
    "th",
    "dt",
    "dd",
    "section",
    "article",
]

# Rough per-tag base priority used when we must drop content to fit budget.
# Lower number = kept first.
TAG_PRIORITY = {
    "h1": 1,
    "h2": 1,
    "h3": 2,
    "h4": 2,
    "table": 2,
    "tr": 2,
    "td": 2,
    "th": 2,
    "dt": 2,
    "dd": 2,
    "li": 2,
    "p": 3,
    "article": 3,
    "section": 3,
    "div": 4,
    "span": 4,
}

VIDEO_HOST_PATTERN = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _classes_str(tag: Tag) -> str:
    return " ".join(tag.get("class", []) or [])


def _visual_hint(tag: Tag) -> str:
    style = (tag.get("style") or "").lower().replace(" ", "")
    hints = []
    if "font-size" in style:
        # crude "large" detection: anything >= ~20px or expressed in em/rem >= 1.25
        size_match = re.search(r"font-size:(\d+(\.\d+)?)(px|em|rem|pt)", style)
        if size_match:
            value, _, unit = size_match.groups()
            value = float(value)
            if (
                (unit == "px" and value >= 20)
                or (unit in ("em", "rem") and value >= 1.25)
                or (unit == "pt" and value >= 16)
            ):
                hints.append("large")
    if (
        "font-weight:bold" in style
        or "font-weight:700" in style
        or "font-weight:800" in style
        or "font-weight:900" in style
    ):
        hints.append("bold")
    return "/".join(hints)


# --------------------------------------------------------------------------
# JSON-LD extraction (must happen BEFORE scripts are stripped)
# --------------------------------------------------------------------------


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    json_ld: list[dict] = []

    for script in soup.find_all(
        "script", attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        try:
            content = script.string or script.get_text()
            if not content:
                continue
            data = json.loads(content)
            if isinstance(data, list):
                json_ld.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                # some sites nest an @graph array
                if "@graph" in data and isinstance(data["@graph"], list):
                    json_ld.extend(d for d in data["@graph"] if isinstance(d, dict))
                else:
                    json_ld.append(data)
        except Exception:
            continue

    return json_ld


def json_ld_schema_types(json_ld: list[dict]) -> list[str]:
    types = set()
    for item in json_ld:
        t = item.get("@type")
        if isinstance(t, list):
            types.update(str(x) for x in t)
        elif t:
            types.add(str(t))
    return sorted(types)


# --------------------------------------------------------------------------
# Video detection (before removing iframes)
# --------------------------------------------------------------------------


def detect_video_count(html: str, soup: BeautifulSoup) -> int:
    iframe_matches = len(VIDEO_HOST_PATTERN.findall(html))
    video_tags = len(soup.find_all("video"))
    return iframe_matches + video_tags


# --------------------------------------------------------------------------
# Boilerplate removal
# --------------------------------------------------------------------------


def strip_boilerplate(soup: BeautifulSoup) -> None:
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # drop obviously hidden elements
    for tag in soup.find_all(
        style=re.compile(r"display:\s*none|visibility:\s*hidden", re.I)
    ):
        tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        tag.decompose()


# --------------------------------------------------------------------------
# Semantic DOM block extraction — tags/classes/ids/style are SIGNALS ONLY
# --------------------------------------------------------------------------


def extract_semantic_blocks(soup: BeautifulSoup) -> list[dict]:
    """
    Returns a list of dicts:
        {"tag": str, "classes": str, "id": str, "visual": str,
         "text": str, "priority": int}
    Deliberately does NOT assume h1=title, p=description, li=feature.
    That mapping is left to the LLM, which sees tag/class/id/visual as hints.
    """
    blocks: list[dict] = []

    for tag in soup.find_all(SEMANTIC_TAGS):
        # skip if a descendant of an already-captured larger block of the same
        # kind to reduce duplication (crude containment check for div/span)
        text = clean_text(tag.get_text(" ", strip=True))
        if not text or len(text) < MIN_BLOCK_TEXT_LEN:
            continue

        blocks.append(
            {
                "tag": tag.name,
                "classes": _classes_str(tag),
                "id": tag.get("id", "") or "",
                "visual": _visual_hint(tag),
                "text": text,
                "priority": TAG_PRIORITY.get(tag.name, 4),
            }
        )

    return blocks


def remove_duplicate_blocks(blocks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for b in blocks:
        key = b["text"].lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(b)
    return result


def _looks_boosted(block: dict) -> bool:
    """Give a small priority boost to blocks whose class/id hints at product info."""
    hint_words = (
        "product",
        "title",
        "name",
        "price",
        "sku",
        "mpn",
        "gtin",
        "brand",
        "feature",
        "spec",
        "description",
        "review",
        "rating",
        "faq",
        "availability",
        "stock",
    )
    haystack = f"{block['classes']} {block['id']}".lower()
    return any(w in haystack for w in hint_words)


def build_compact_input(
    blocks: list[dict], max_chars: int = MAX_LLM_PAGE_CHARS
) -> tuple[str, int]:
    """
    Priority-ranked compaction. Returns (compact_text, blocks_used_count).
    Priority 1 always wins ties; class/id hints get a boost so e.g.
    <div class="product-name"> beats a same-priority random <div>.
    """

    def sort_key(b: dict):
        boosted = 0 if _looks_boosted(b) else 1
        return (b["priority"], boosted)

    ordered = sorted(blocks, key=sort_key)

    lines: list[str] = []
    used = 0
    total_len = 0

    for b in ordered:
        entry = (
            f"ELEMENT: {b['tag']}"
            f"{' CLASS: ' + b['classes'] if b['classes'] else ''}"
            f"{' ID: ' + b['id'] if b['id'] else ''}"
            f"{' VISUAL: ' + b['visual'] if b['visual'] else ''}"
            f" TEXT: {b['text']}"
        )
        entry_len = len(entry) + 1  # newline
        if total_len + entry_len > max_chars:
            continue  # skip lower priority overflow items, keep scanning smaller ones
        lines.append(entry)
        total_len += entry_len
        used += 1

    return "\n".join(lines), used


# --------------------------------------------------------------------------
# Deterministic page analytics (LLM never touches these numbers)
# --------------------------------------------------------------------------


def compute_analytics(
    soup_original: BeautifulSoup, html: str, json_ld: list[dict]
) -> dict:
    title_tag = soup_original.find("title")
    page_title = clean_text(title_tag.get_text()) if title_tag else None

    meta_desc_tag = soup_original.find(
        "meta", attrs={"name": re.compile("^description$", re.I)}
    )
    meta_description = (
        clean_text(meta_desc_tag.get("content", "")) if meta_desc_tag else None
    )

    h1_tags = [
        clean_text(t.get_text())
        for t in soup_original.find_all("h1")
        if clean_text(t.get_text())
    ]
    h2_tags = [
        clean_text(t.get_text())
        for t in soup_original.find_all("h2")
        if clean_text(t.get_text())
    ]

    image_count = len(soup_original.find_all("img"))
    video_count = detect_video_count(html, soup_original)

    body_text = clean_text(soup_original.get_text(" ", strip=True))
    word_count = len(body_text.split()) if body_text else 0

    schema_types = json_ld_schema_types(json_ld)

    faq_present = bool(
        soup_original.find(string=re.compile(r"frequently asked questions", re.I))
        or "FAQPage" in schema_types
    )

    return {
        "page_title": page_title,
        "meta_description": meta_description,
        "word_count": word_count,
        "h1_count": len(h1_tags),
        "h2_count": len(h2_tags),
        "h1_tags": h1_tags,
        "h2_tags": h2_tags,
        "image_count": image_count,
        "video_count": video_count,
        "schema_types": schema_types,
        "faq_present": faq_present,
    }


def compute_content_gaps(analytics: dict) -> list[dict]:
    gaps: list[dict] = []

    if not analytics.get("faq_present"):
        gaps.append({"type": "faq", "message": "Missing FAQ section"})

    if analytics.get("word_count", 0) < 500:
        gaps.append(
            {"type": "word_count", "message": "Word count is low (under 500 words)"}
        )

    if analytics.get("video_count", 0) == 0:
        gaps.append({"type": "video", "message": "No video content on page"})

    if analytics.get("h1_count", 0) == 0:
        gaps.append({"type": "h1", "message": "No H1 heading found on page"})

    if not analytics.get("schema_types"):
        gaps.append({"type": "schema", "message": "No structured data (JSON-LD) found"})

    return gaps


# --------------------------------------------------------------------------
# Structured output schema
# --------------------------------------------------------------------------


class ProductPageContent(BaseModel):
    url: str

    page_title: Optional[str] = None
    meta_description: Optional[str] = None

    product_title: Optional[str] = None
    brand: Optional[str] = None

    sku: Optional[str] = None
    mpn: Optional[str] = None
    gtin: Optional[str] = None

    description: Optional[str] = None

    features: list[str] = Field(default_factory=list)
    specifications: dict = Field(default_factory=dict)

    price: Optional[str] = None
    currency: Optional[str] = None
    availability: Optional[str] = None

    images: list[str] = Field(default_factory=list)
    videos: Optional[list[str]] = None

    reviews_present: bool = False
    review_count: Optional[int] = None
    rating: Optional[float] = None

    faq_present: bool = False
    faqs: list[dict] = Field(default_factory=list)

    schema_types: list[str] = Field(default_factory=list)
    breadcrumbs: list[str] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You extract structured product data from partially-processed webpage content.

IMPORTANT RULES:
- Do not invent information. If something is not present, return null / false / an empty list.
- Preserve the actual wording where possible (do not rephrase product titles/descriptions).
- HTML tags, classes, ids, and VISUAL hints are signals only, never guaranteed rules.
- Do NOT assume H1 means product title, P means description, or LI means a feature.
- Product information may be represented by div, span, p, custom components, CSS classes, or JSON-LD.
- Use surrounding context (nearby elements, class names, JSON-LD) to decide meaning.
- The PAGE ANALYTICS block is deterministic ground truth. Never override or contradict those numbers;
  just use them as context (e.g. faq_present, schema_types).
- Return ONLY the structured fields you were asked for.
"""


# --------------------------------------------------------------------------
# One OpenAI call, with token usage captured
# --------------------------------------------------------------------------

from app.core.config import settings


def call_openai_extraction(
    url: str,
    compact_text: str,
    json_ld: list[dict],
    analytics: dict,
) -> tuple[ProductPageContent, dict]:
    """
    Single LLM call. Returns (structured_result, token_usage_dict).
    token_usage_dict looks like:
        {"model": "...", "prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
    """
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    user_prompt = f"""
URL: {url}

PAGE CONTENT (semantic DOM blocks, priority-ranked, tags/classes are signals only):
{compact_text}

JSON-LD:
{json.dumps(json_ld, ensure_ascii=False)[:6000]}

PAGE ANALYTICS (deterministic, do not contradict):
{json.dumps(analytics, ensure_ascii=False)}
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ProductPageContent",
                "schema": ProductPageContent.model_json_schema(),
                "strict": False,
            },
        },
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    parsed.setdefault("url", url)

    result = ProductPageContent(**parsed)

    usage = response.usage
    token_usage = {
        "model": OPENAI_MODEL,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }

    return result, token_usage


# --------------------------------------------------------------------------
# Optional: DuckDuckGo fallback enrichment (no API key needed)
# Only used to fill a SMALL number of still-missing signals (e.g. brand),
# never to overwrite anything the LLM already found from the page itself.
# --------------------------------------------------------------------------


def duckduckgo_fallback_lookup(query: str, max_results: int = 3) -> list[str]:
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("duckduckgo_search not installed; skipping fallback lookup")
        return []

    snippets: list[str] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                body = r.get("body") or r.get("snippet")
                if body:
                    snippets.append(clean_text(body))
    except Exception as exc:
        logger.warning("DuckDuckGo fallback lookup failed: %s", exc)
    return snippets


def enrich_missing_brand(
    product: ProductPageContent, page_title: Optional[str]
) -> ProductPageContent:
    """Only called if brand is still missing after the LLM extraction."""
    if product.brand or not (product.product_title or page_title):
        return product

    query = f"{product.product_title or page_title} brand manufacturer"
    snippets = duckduckgo_fallback_lookup(query, max_results=3)
    if snippets:
        # store as a low-confidence hint rather than silently overwriting a
        # structured field; callers can decide whether to promote it.
        product.specifications.setdefault(
            "_brand_hint_from_web_search", snippets[0][:200]
        )

    return product


# --------------------------------------------------------------------------
# Fetching (httpx first, Playwright fallback for JS-rendered pages)
# --------------------------------------------------------------------------

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Cache-Control": "max-age=0",
}

# Status codes that usually mean bot-detection rather than "page truly missing".
# Worth retrying / falling back to a real browser for these.
BOT_BLOCK_STATUS_CODES = {403, 429, 503}

FETCH_RETRIES = 2
FETCH_RETRY_BACKOFF_SECONDS = 1.5


class BotBlockedError(Exception):
    """Raised when the plain HTTP fetch is blocked by bot/WAF protection."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"Blocked with status {status_code}")


def fetch_html_httpx(url: str, referer: Optional[str] = None) -> str:
    """
    Fetches HTML with full browser-like headers and a small retry/backoff
    loop. Raises BotBlockedError on 403/429/503 so the caller can decide to
    fall back to a real browser (Playwright) instead of giving up.
    """
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    else:
        # A bare same-origin referer is more convincing than none at all for
        # sites that check for it (some WAFs reject direct/no-referer hits).
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            headers["Referer"] = f"{parts.scheme}://{parts.netloc}/"
        except Exception:
            pass

    last_exc: Optional[Exception] = None

    with httpx.Client(
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers=headers,
        http2=True,
    ) as client:
        for attempt in range(FETCH_RETRIES + 1):
            try:
                resp = client.get(url)

                if resp.status_code in BOT_BLOCK_STATUS_CODES:
                    logger.warning(
                        "Fetch got status %s (attempt %d/%d) for %s",
                        resp.status_code,
                        attempt + 1,
                        FETCH_RETRIES + 1,
                        url,
                    )
                    if attempt < FETCH_RETRIES:
                        time.sleep(FETCH_RETRY_BACKOFF_SECONDS * (attempt + 1))
                        continue
                    raise BotBlockedError(resp.status_code, resp.text[:200])

                resp.raise_for_status()
                return resp.text

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < FETCH_RETRIES:
                    time.sleep(FETCH_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise
            except httpx.RequestError as exc:
                # network-level issue (timeout, DNS, connection reset) — retry
                last_exc = exc
                logger.warning(
                    "Network error fetching %s (attempt %d): %s", url, attempt + 1, exc
                )
                if attempt < FETCH_RETRIES:
                    time.sleep(FETCH_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise

    # Should not reach here, but keep type-checkers happy.
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url} for an unknown reason")


def looks_content_poor(soup: BeautifulSoup) -> bool:
    """Heuristic: if there's almost no text, the page is probably JS-rendered."""
    text = clean_text(soup.get_text(" ", strip=True))
    return len(text) < 200


async def fetch_html_playwright(url: str) -> str:
    """Fetch page HTML using Playwright Async API."""

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. "
            "Run: pip install playwright && playwright install chromium"
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = await browser.new_context(
            user_agent=BROWSER_HEADERS["User-Agent"],
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        page = await context.new_page()

        await page.goto(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
            wait_until="networkidle",
        )

        html = await page.content()

        await browser.close()

        return html


async def fetch_html(url: str) -> str:
    """
    Fetches the page using Playwright browser.
    """
    return await fetch_html_playwright(url)


# --------------------------------------------------------------------------
# Orchestrator — call this ONCE per product URL
# --------------------------------------------------------------------------


async def extract_product_page_once(
    url: str, use_web_fallback: bool = True
) -> dict[str, Any]:
    """
    Fetches and processes a product page exactly once, returning a single
    dict ready to be stored in Product.actual_content and reused across
    GPT / Gemini / Claude audits.
    """
    started_at = time.time()

    html = await fetch_html(url)
    original_html_chars = len(html)

    # Parse once to pull JSON-LD before anything is stripped.
    soup_original = BeautifulSoup(html, "html.parser")
    json_ld = extract_json_ld(soup_original)

    # Parse a second time for the working copy and strip nav/header/footer/
    # script/style/hidden elements BEFORE computing analytics, so word_count,
    # h1/h2 counts etc. reflect actual page content, not menus/footers/raw JS.
    soup_working = BeautifulSoup(html, "html.parser")
    strip_boilerplate(soup_working)

    analytics = compute_analytics(soup_working, html, json_ld)
    content_gaps = compute_content_gaps(analytics)

    blocks = extract_semantic_blocks(soup_working)
    blocks = remove_duplicate_blocks(blocks)

    compact_text, blocks_used = build_compact_input(blocks, MAX_LLM_PAGE_CHARS)
    compact_input_chars = len(compact_text)

    compression = {
        "original_html_chars": original_html_chars,
        "compact_input_chars": compact_input_chars,
        "blocks_extracted": len(blocks),
        "blocks_used": blocks_used,
        "reduction_percent": round(
            (1 - (compact_input_chars / max(original_html_chars, 1))) * 100, 2
        ),
    }

    product_content, token_usage = call_openai_extraction(
        url=url,
        compact_text=compact_text,
        json_ld=json_ld,
        analytics=analytics,
    )

    if use_web_fallback:
        product_content = enrich_missing_brand(
            product_content, analytics.get("page_title")
        )

    elapsed_seconds = round(time.time() - started_at, 2)

    return {
        "url": url,
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": elapsed_seconds,
        # Deterministic, never touched by the LLM:
        "analytics": analytics,
        "content_gaps": content_gaps,
        "json_ld": json_ld,
        "compression": compression,
        # LLM understanding of the product:
        "product_content": product_content.model_dump(),
        # Token accounting for this one call:
        "token_usage": token_usage,
    }


# --------------------------------------------------------------------------
# Persisting into the Product model
# --------------------------------------------------------------------------
#
# Add these two JSONB columns to your existing Product model (in addition to
# what you already have — no need to rewrite the rest of the model):
#
#     actual_content: Mapped[dict] = mapped_column(
#         JSONB, nullable=True
#     )
#     extraction_token_usage: Mapped[dict] = mapped_column(
#         JSONB, nullable=True, default=dict, server_default="{}"
#     )
#
# Then generate a migration (Alembic: `alembic revision --autogenerate -m
# "add actual_content and extraction_token_usage to products"`) and apply it.
#
# `actual_content` stores the FULL dict returned by extract_product_page_once
# (analytics, content_gaps, json_ld, compression stats, product_content).
# `extraction_token_usage` stores just the token_usage sub-dict so you can
# query/aggregate spend without unpacking the whole JSON blob.


async def save_extraction_to_product(
    session: AsyncSession, product, extraction_result: dict
) -> None:
    """
    Persists a one-time extraction result onto an existing Product row.
    """

    product.actual_content = extraction_result
    product.extraction_token_usage = extraction_result.get("token_usage", {})

    session.add(product)
    await session.commit()
