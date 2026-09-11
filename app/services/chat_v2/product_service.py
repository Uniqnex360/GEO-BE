"""
Product/brand lookup, creation, and LLM-based baseline metadata enrichment
for products that don't exist in our DB yet.
"""

from datetime import datetime, timedelta
from typing import Optional

from langchain_openai import ChatOpenAI
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Brand, Chat, Product
from app.models.base import LLMModels

from .constants import RETENTION_DAYS_THRESHOLD
from .schemas import GEOAuditRequest, ProductEnrichment
from .tools import GEO_TOOLS


def build_lookup_filters(payload: GEOAuditRequest) -> list:
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


async def find_existing_product(
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


async def get_recent_cached_chat(db: AsyncSession, product_id: int) -> Optional[Chat]:
    threshold = datetime.now() - timedelta(days=RETENTION_DAYS_THRESHOLD)
    stmt = (
        select(Chat)
        .where(Chat.product_id == product_id, Chat.created_at >= threshold)
        .order_by(Chat.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def enrich_missing_product_metadata(
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


async def get_or_create_brand(
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


async def create_new_product(
    db: AsyncSession, payload: GEOAuditRequest, tenant_id: int, user_id: Optional[int]
) -> Product:
    enriched = await enrich_missing_product_metadata(payload)

    product_name = (
        payload.product_name
        or enriched.product_name
        or f"Unknown Product {datetime.now().timestamp()}"
    )
    brand_name = enriched.brand_name or product_name
    country = payload.country or enriched.country or "Unknown"

    brand_record = await get_or_create_brand(
        db, tenant_id, brand_name, country, user_id
    )

    product_record = Product(
        tenant_id=tenant_id,
        brand_id=brand_record.id,
        name=product_name,
        product_url=payload.product_url,
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


def resolve_identifier(payload: GEOAuditRequest) -> str:
    return payload.product_name or payload.sku or payload.product_url or ""
