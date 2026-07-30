import statistics
import json
import time
from collections import defaultdict
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import (
    exists,
    select,
    func,
    cast,
    String,
    Float,
    case,
    distinct,
    desc,
    asc,
)
from sqlalchemy.orm import selectinload, joinedload
from statistics import mean
from fastapi import HTTPException, status

from app.models import (
    User,
    Product,
    ProductFAQ,
    ProductFeature,
    Brand,
    Chat,
    ChatSearchQuery,
    ChatGEOAuditRecord,
)


class DynamicRow:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ProductService:
    """Service class for product operations"""

    @staticmethod
    async def _save(db: AsyncSession):
        """commit helper"""

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def _get_product(
        db: AsyncSession,
        product_id: int,
    ):
        """fetch product"""

        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.features),
                selectinload(Product.faqs),
                selectinload(Product.brand),
            )
            .where(
                Product.id == product_id,
                Product.is_deleted == False,
            )
        )

        product = result.scalar_one_or_none()

        if not product:
            raise ValueError("Product not found")

        return product

    @staticmethod
    async def _validate_fk(
        db: AsyncSession,
        tenant_id: int,
        brand_id: int,
    ):
        """validate foreign keys"""

        result = await db.execute(
            select(Brand).where(
                Brand.id == brand_id,
                Brand.is_deleted == False,
            )
        )

        brand = result.scalar_one_or_none()

        if not brand:
            raise ValueError("Brand not found")

        if brand.tenant_id != tenant_id:
            raise ValueError("Brand does not belong to this tenant")

        return brand

    @staticmethod
    async def _product_duplication_validation(
        db: AsyncSession,
        tenant_id: int,
        name: str,
        sku: str = None,
        product_id: int = None,
    ):
        """duplicate validation"""

        query = select(Product).where(
            Product.tenant_id == tenant_id,
            Product.name == name,
            Product.is_deleted == False,
        )

        if product_id:
            query = query.where(Product.id != product_id)

        result = await db.execute(query)

        if result.scalar_one_or_none():
            raise ValueError("Product name already exists")

        if sku:
            sku_query = select(Product).where(
                Product.tenant_id == tenant_id,
                Product.sku == sku,
                Product.is_deleted == False,
            )

            if product_id:
                sku_query = sku_query.where(Product.id != product_id)

            sku_result = await db.execute(sku_query)

            if sku_result.scalar_one_or_none():
                raise ValueError("SKU already exists")

    @staticmethod
    async def create_product(
        db: AsyncSession,
        data: dict,
        user: dict,
        tenant_id: int,
    ):
        """create product"""

        print("product data", data)

        name = data.get("name")
        brand_id = data.get("brand_id")

        if not tenant_id:
            raise ValueError("tenant_id required")

        if not name:
            raise ValueError("name required")

        if not brand_id:
            raise ValueError("brand_id required")

        brand = await ProductService._validate_fk(
            db=db,
            tenant_id=tenant_id,
            brand_id=brand_id,
        )

        await ProductService._product_duplication_validation(
            db=db,
            tenant_id=tenant_id,
            name=name,
            sku=data.get("sku"),
        )

        product = Product(
            tenant_id=tenant_id,
            brand_id=brand.id,
            brand_name=brand.name,
            created_by=int(user.get("sub")),
            name=name,
            manufacturer=data.get("manufacturer"),
            model_number=data.get("model_number"),
            product_type=data.get("product_type"),
            category=data.get("category"),
            sku=data.get("sku"),
            mpn=data.get("mpn"),
            upc=data.get("upc"),
            gtin=data.get("gtin"),
            ean=data.get("ean"),
            product_url=data.get("product_url"),
            texonomy=data.get("texonomy"),
            short_description=data.get("short_description"),
            long_description=data.get("long_description"),
            specifications=data.get("specifications"),
            regular_price=data.get("regular_price"),
            sale_price=data.get("sale_price"),
            currency=data.get("currency"),
            rating=data.get("rating"),
            rating_count=data.get("rating_count"),
            meta_title=data.get("meta_title"),
            meta_description=data.get("meta_description"),
            meta_keywords=data.get("meta_keywords"),
        )

        features = data.get("features", [])

        for item in features:
            product.features.append(ProductFeature(value=item["value"]))

        faqs = data.get("faqs", [])

        for item in faqs:
            product.faqs.append(
                ProductFAQ(
                    question=item["question"],
                    answer=item["answer"],
                    sort_order=item.get(
                        "sort_order",
                        0,
                    ),
                )
            )

        db.add(product)

        await ProductService._save(db)
        await db.refresh(product)

        return await ProductService._get_product(
            db,
            product.id,
        )

    @staticmethod
    async def update_product(
        db: AsyncSession,
        product_id: int,
        data: dict,
        user: dict,
    ):
        """update product"""

        product = await ProductService._get_product(
            db,
            product_id,
        )

        name = data.get(
            "name",
            product.name,
        )

        sku = data.get(
            "sku",
            product.sku,
        )

        await ProductService._product_duplication_validation(
            db=db,
            tenant_id=product.tenant_id,
            name=name,
            sku=sku,
            product_id=product.id,
        )

        brand_id = data.get(
            "brand_id",
            product.brand_id,
        )

        if brand_id != product.brand_id:

            brand = await ProductService._validate_fk(
                db=db,
                tenant_id=product.tenant_id,
                brand_id=brand_id,
            )

            product.brand_id = brand.id
            product.brand_name = brand.name

        fields = [
            "name",
            "manufacturer",
            "model_number",
            "product_type",
            "category",
            "sku",
            "mpn",
            "upc",
            "gtin",
            "ean",
            "product_url",
            "texonomy",
            "short_description",
            "long_description",
            "specifications",
            "regular_price",
            "sale_price",
            "currency",
            "rating",
            "rating_count",
            "meta_title",
            "meta_description",
            "meta_keywords",
        ]

        for field in fields:

            value = data.get(field)

            if value is not None:
                setattr(
                    product,
                    field,
                    value,
                )

        # Replace features
        if "features" in data:

            product.features.clear()

            for item in data["features"]:
                product.features.append(ProductFeature(value=item["value"]))

        # Replace FAQs
        if "faqs" in data:

            product.faqs.clear()

            for item in data["faqs"]:
                product.faqs.append(
                    ProductFAQ(
                        question=item["question"],
                        answer=item["answer"],
                        sort_order=item.get(
                            "sort_order",
                            0,
                        ),
                    )
                )

        product.last_updated_by = int(user.get("sub"))

        await ProductService._save(db)

        await db.refresh(product)

        return await ProductService._get_product(
            db,
            product.id,
        )

    @staticmethod
    async def soft_delete_product(
        db: AsyncSession,
        product_id: int,
        user: User,
    ):
        """activate/deactivate"""

        product = await ProductService._get_product(
            db,
            product_id,
        )

        product.is_active = not product.is_active

        product.last_updated_by = user.id

        await ProductService._save(db)

        return product

    @staticmethod
    async def delete_product(
        db: AsyncSession,
        product_id: int,
        user: dict,
    ):
        """logical delete"""

        product = await ProductService._get_product(
            db,
            product_id,
        )

        product.is_deleted = True
        product.deleted_by = int(user.get("sub"))

        await ProductService._save(db)

        return True

    @staticmethod
    async def detail(
        db: AsyncSession,
        product_id: int,
        tenant_id: int,
        user: dict,
    ):
        is_super_admin = user.get("is_super_admin", False)

        # ------------------------------------------------------------------
        # 1. Fetch EVERYTHING in ONE single transaction using selectinload
        # ------------------------------------------------------------------
        product_query = (
            select(Product)
            .where(Product.id == product_id, Product.is_deleted.is_(False))
            .options(
                selectinload(Product.features),
                selectinload(Product.faqs),
                selectinload(Product.brand),
                # Deeply load chats and their related search queries together
                selectinload(Product.chats).selectinload(Chat.search_queries),
            )
        )

        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()

        # Generic Not Found
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )

        # Strict Tenant Verification
        if not is_super_admin and product.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: This product does not belong to your tenant.",
            )

        # ------------------------------------------------------------------
        # 2. Extract and Process Analytics Directly via Python
        # ------------------------------------------------------------------
        all_chats = product.chats or []
        total_sessions = len(all_chats)

        # Flatten all child queries across all chats for this product
        all_queries = [q for chat in all_chats for q in (chat.search_queries or [])]
        total_queries = len(all_queries)

        # Calculate Math Safely
        avg_sov = (
            round(mean([q.share_of_voice for q in all_queries]), 2)
            if all_queries
            else 0.0
        )
        avg_rank = (
            round(mean([q.citation_rank for q in all_queries]), 2)
            if all_queries
            else 0.0
        )

        # Visibility Rate calculation
        found_count = sum(1 for q in all_queries if q.product_found is True)
        visibility_rate = (
            round((found_count / total_queries) * 100, 2) if total_queries > 0 else 0.0
        )

        # Last Analysis Timestamp
        last_analysis = max([c.created_at for c in all_chats]) if all_chats else None

        # ------------------------------------------------------------------
        # 3. Find Best Performing Query
        # ------------------------------------------------------------------
        best_query_obj = max(
            all_queries, key=lambda q: q.share_of_voice or 0.0, default=None
        )

        # ------------------------------------------------------------------
        # 4. Extract Competitors and Sources (De-duplicated)
        # ------------------------------------------------------------------
        competitors_set = set()
        sources_set = set()

        for q in all_queries:
            if q.competitors_mentioned:
                competitors_set.update(q.competitors_mentioned)
            if q.citing_sources:
                sources_set.update(q.citing_sources)

        # ------------------------------------------------------------------
        # 5. Format Latest 5 Chat Sessions
        # ------------------------------------------------------------------
        sorted_chats = sorted(all_chats, key=lambda c: c.created_at, reverse=True)[:5]
        latest_sessions = []

        for session in sorted_chats:
            latest_sessions.append(
                {
                    "chat_id": session.id,
                    "model_used": session.model_used or "",
                    "extra_context": session.extra_context or "",
                    "created_at": session.created_at,
                    "final_report": session.final_optimization_report or "",
                    "queries": [
                        {
                            "id": q.id,
                            "query": q.query_text or "",
                            "share_of_voice": q.share_of_voice or 0,
                            "citation_rank": q.citation_rank or 0,
                            "product_found": q.product_found,
                            "platform_breakdown": q.platform_breakdown or {},
                            "competitors": q.competitors_mentioned or [],
                            "sources": q.citing_sources or [],
                            "optimization_tips": q.query_optimization_tips or "",
                        }
                        for q in (session.search_queries or [])
                    ],
                }
            )

        # ------------------------------------------------------------------
        # Final Unified Response
        # ------------------------------------------------------------------
        return {
            "product": product,
            "analytics": {
                "total_sessions": total_sessions,
                "total_queries": total_queries,
                "avg_share_of_voice": float(avg_sov),
                "avg_citation_rank": float(avg_rank),
                "visibility_rate": float(visibility_rate),
                "last_analysis": last_analysis,
            },
            "best_query": {
                "query": best_query_obj.query_text if best_query_obj else "",
                "share_of_voice": (
                    best_query_obj.share_of_voice if best_query_obj else 0.0
                ),
                "citation_rank": best_query_obj.citation_rank if best_query_obj else 0,
            },
            "competitors": list(competitors_set),
            "citation_sources": list(sources_set),
            "latest_sessions": latest_sessions,
        }

    @staticmethod
    async def product_detail_v2(
        db: AsyncSession,
        product_id: int,
        tenant_id: int,
        user: dict,
        tab: str,
    ) -> Dict[str, Any]:
        """
        V2 Detail endpoint tailored exactly to frontend dashboard specifications.
        Optimized to extract competitor listings from JSON fields and map model choices
        to dynamic recommendation actions.

        Note: All performance, visibility, and impact metrics are normalized to a 0-10 scale.
        """
        is_super_admin = user.get("is_super_admin", False)

        # ------------------------------------------------------------------
        # 1. Unified Eager-Load Query Execution (Optimized by Tab Type)
        # ------------------------------------------------------------------
        load_options = [
            selectinload(Product.brand),
            selectinload(Product.chats).selectinload(Chat.search_queries),
        ]

        if tab == "visibility":
            load_options.append(selectinload(Product.features))
            load_options.append(selectinload(Product.faqs))

        product_query = (
            select(Product)
            .where(Product.id == product_id, Product.is_deleted.is_(False))
            .options(*load_options)
        )

        product_result = await db.execute(product_query)
        product = product_result.scalar_one_or_none()

        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )

        if not is_super_admin and product.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: This product does not belong to your tenant.",
            )

        # ------------------------------------------------------------------
        # 2. Extract and Flatten Associated Analytics Records (Link Parents)
        # ------------------------------------------------------------------
        all_chats: List[Chat] = product.chats or []
        all_queries: List[ChatSearchQuery] = []

        for chat in all_chats:
            for q in chat.search_queries or []:
                q._parent_chat = chat
                all_queries.append(q)

        total_queries = len(all_queries)

        # ------------------------------------------------------------------
        # 3. Dynamic Platform Breakdown Engine Analysis (SCALE 0 - 10)
        #    Aligned with list_products logic
        # ------------------------------------------------------------------
        ENGINE_LABEL_MAP = {
            "GPT": "chatgpt",
            "GEMINI": "gemini",
            "CLAUDE": "claude",
        }

        # Initialize tracking accumulators per engine
        engine_accum = {
            "chatgpt": {"total_queries": 0, "found_count": 0},
            "gemini": {"total_queries": 0, "found_count": 0},
            "claude": {"total_queries": 0, "found_count": 0},
        }

        # Aggregate query statistics grouped by Chat.model_choice
        for q in all_queries:
            parent_chat = getattr(q, "_parent_chat", None)
            raw_model = parent_chat.model_choice if parent_chat else None

            # Map raw model string to standardized key
            engine_key = ENGINE_LABEL_MAP.get(
                raw_model, str(raw_model).lower() if raw_model else None
            )

            if engine_key in engine_accum:
                engine_accum[engine_key]["total_queries"] += 1
                if q.product_found is True:
                    engine_accum[engine_key]["found_count"] += 1

        # Calculate Visibility Rate (0 - 10 scale) per engine
        engine_visibility_summary = {}
        for engine, bucket in engine_accum.items():
            tot_q = bucket["total_queries"]
            found_cnt = bucket["found_count"]
            engine_visibility_summary[engine] = (
                round((found_cnt / tot_q) * 10, 1) if tot_q > 0 else 0.0
            )

        # Global AI Visibility Score: Mean of active engine visibility rates
        active_engine_scores = [
            rate
            for engine, rate in engine_visibility_summary.items()
            if engine_accum[engine]["total_queries"] > 0
        ]
        ai_visibility_score = (
            round(statistics.mean(active_engine_scores), 1)
            if active_engine_scores
            else 0.0
        )

        # Global Mention Rate across all queries (0 - 10 scale)
        found_count = sum(1 for q in all_queries if q.product_found is True)
        mention_rate = (
            round((found_count / total_queries) * 10, 1) if total_queries > 0 else 0.0
        )

        total_reviews = (
            product.no_of_reviews if product.no_of_reviews is not None else 0
        )
        total_faqs = product.no_of_faqs if product.no_of_faqs is not None else 0

        # ------------------------------------------------------------------
        # 4. Construct Shared Product Identity Header Schema Block
        # ------------------------------------------------------------------
        response_payload = {
            "productInfo": {
                "icon": (
                    "📺"
                    if product.category and "tv" in product.category.lower()
                    else "📦"
                ),
                "title": product.name,
                "brand": (
                    product.brand.name
                    if product.brand
                    else (product.brand_name or "Unknown Brand")
                ),
                "retailer": "Croma",
                "category": product.category or "General Electronics",
                "sku": product.sku or "N/A",
                "mpn": product.mpn or "N/A",
                "globalScores": {
                    "visibilityScore": ai_visibility_score,  # 0 - 10
                    "mentionRate": mention_rate,  # 0 - 10
                    "reviewsCount": total_reviews,
                },
                "engineBreakdown": [
                    {
                        "name": "ChatGPT",
                        "score": engine_visibility_summary.get("chatgpt", 0.0),
                    },
                    {
                        "name": "Gemini",
                        "score": engine_visibility_summary.get("gemini", 0.0),
                    },
                    {
                        "name": "Claude",
                        "score": engine_visibility_summary.get("claude", 0.0),
                    },
                ],
            },
            "tabData": {},
        }

        # ------------------------------------------------------------------
        # 5. Dynamic Tab Processing Matrix
        # ------------------------------------------------------------------
        if tab == "visibility":
            calculated_faqs = (
                len(product.faqs or [])
                if hasattr(product, "faqs") and product.faqs is not None
                else total_faqs
            )
            response_payload["tabData"] = {
                "chartData": [
                    {
                        "name": "ChatGPT",
                        "score": engine_visibility_summary.get("chatgpt", 0.0),
                        "color": "#10b981",
                    },
                    {
                        "name": "Gemini",
                        "score": engine_visibility_summary.get("gemini", 0.0),
                        "color": "#3b82f6",
                    },
                    {
                        "name": "Claude",
                        "score": engine_visibility_summary.get("claude", 0.0),
                        "color": "#f59e0b",
                    },
                ],
                "faqCount": calculated_faqs,
                "reviewCount": total_reviews,
                "productUrl": product.product_url or "#",
            }

        elif tab == "competitor":
            competitors_set = set()

            if (
                hasattr(product, "competitor_analytics")
                and product.competitor_analytics
            ):
                if isinstance(product.competitor_analytics, list):
                    for comp_entry in product.competitor_analytics:
                        if (
                            isinstance(comp_entry, dict)
                            and "competitor_name" in comp_entry
                        ):
                            competitors_set.add(comp_entry["competitor_name"])

            if not competitors_set:
                for q in all_queries:
                    if q.competitors_mentioned:
                        competitors_set.update(q.competitors_mentioned)

            ui_competitors = []
            for comp in list(competitors_set):
                ui_competitors.append(
                    {
                        "name": comp,
                        "chatGPT": min(
                            10.0,
                            max(
                                0.0,
                                round(
                                    engine_visibility_summary.get("chatgpt", 0.0) * 0.9,
                                    1,
                                ),
                            ),
                        ),
                        "gemini": min(
                            10.0,
                            max(
                                0.0,
                                round(
                                    engine_visibility_summary.get("gemini", 0.0) * 1.1,
                                    1,
                                ),
                            ),
                        ),
                        "claude": min(
                            10.0,
                            max(
                                0.0,
                                round(
                                    engine_visibility_summary.get("claude", 0.0) * 0.95,
                                    1,
                                ),
                            ),
                        ),
                        "avg": min(
                            10.0, max(0.0, round(ai_visibility_score * 0.95, 1))
                        ),
                        "active": False,
                    }
                )

            ui_competitors.insert(
                0,
                {
                    "name": f"{product.name} (You)",
                    "chatGPT": engine_visibility_summary.get("chatgpt", 0.0),
                    "gemini": engine_visibility_summary.get("gemini", 0.0),
                    "claude": engine_visibility_summary.get("claude", 0.0),
                    "avg": ai_visibility_score,
                    "active": True,
                },
            )

            # Content gaps scaled to 0-10 format
            schema_gaps = []
            if not product.sku:
                schema_gaps.append(
                    {
                        "title": "Missing Structural SKU Schema Identification",
                        "you": 0.0,
                        "top": 10.0,
                        "status": "High",
                        "gain": "+1.5 points",
                    }
                )
            if not product.mpn:
                schema_gaps.append(
                    {
                        "title": "Missing MPN Global Identification Tags",
                        "you": 0.0,
                        "top": 9.0,
                        "status": "Medium",
                        "gain": "+0.8 points",
                    }
                )
            if total_reviews < 50:
                schema_gaps.append(
                    {
                        "title": "Review Multi-platform Citations Deficit",
                        "you": 3.5,
                        "top": 8.5,
                        "status": "High",
                        "gain": "+2.2 points",
                    }
                )

            if not schema_gaps:
                schema_gaps.append(
                    {
                        "title": "FAQ Context Synchronization Coverage",
                        "you": 7.5,
                        "top": 9.5,
                        "status": "Low",
                        "gain": "+0.5 points",
                    }
                )

            # Radar data scaled to 0-10 format
            response_payload["tabData"] = {
                "competitors": ui_competitors,
                "radarData": [
                    {
                        "subject": "Visibility Index",
                        "You": ai_visibility_score,
                        "Competitor": round(ai_visibility_score * 0.9, 1),
                    },
                    {
                        "subject": "Citation Share",
                        "You": min(10.0, round(mention_rate, 1)),
                        "Competitor": 6.5,
                    },
                    {
                        "subject": "Reviews Count",
                        "You": min(10.0, round(total_reviews / 10, 1)),
                        "Competitor": 7.5,
                    },
                    {
                        "subject": "FAQ Coverage",
                        "You": min(10.0, round((total_faqs * 5) / 10, 1)),
                        "Competitor": 8.0,
                    },
                ],
                "radarSummaryText": f"Currently outperforming {len(competitors_set)} competitor tracking profiles.",
                "priorityCountText": f"{len(schema_gaps)} Content Gaps Identified",
                "gaps": schema_gaps,
            }

        elif tab == "citation":
            source_stats: Dict[str, Dict[str, Any]] = {}

            for q in all_queries:
                citing = q.citing_sources or []
                competitors = q.competitors_mentioned or []

                # Get source authority from the query if available
                auth = getattr(q, "source_authority", None)

                for source in citing:
                    # 1. Normalize/Clean source to extract domain FIRST
                    if "://" not in source:
                        source = "http://" + source

                    parsed = urlparse(source)
                    clean_source = parsed.netloc.lower()
                    if clean_source.startswith("www."):
                        clean_source = clean_source[4:]

                    if not clean_source:
                        continue

                    # 2. Aggregate stats under the cleaned domain name
                    if clean_source not in source_stats:
                        source_stats[clean_source] = {
                            "you_count": 0,
                            "competitor_count": 0,
                            "authorities": [],
                        }

                    source_stats[clean_source]["you_count"] += 1
                    source_stats[clean_source]["competitor_count"] += len(competitors)

                    if auth is not None:
                        source_stats[clean_source]["authorities"].append(auth)

            ui_citations = []
            for source, stats in source_stats.items():
                you_count = stats["you_count"]
                comp_count = stats["competitor_count"]
                gap_count = you_count - comp_count

                # 3. Calculate authority score per aggregated domain
                if stats["authorities"]:
                    # Average the authority across occurrences and scale to 0-10
                    avg_auth = sum(stats["authorities"]) / len(stats["authorities"])
                    calculated_authority = round(avg_auth / 10.0, 1)
                else:
                    calculated_authority = min(10.0, round(5.0 + (you_count * 0.5), 1))

                ui_citations.append(
                    {
                        "source": source,
                        "authority": calculated_authority,  # Scale: 0.0 - 10.0
                        "you": you_count,
                        "competitor": comp_count,
                        "gap": gap_count,
                    }
                )

            response_payload["tabData"] = {
                "citations": (
                    ui_citations
                    if ui_citations
                    else [
                        {
                            "source": "No Citations Tracked",
                            "authority": 0.0,
                            "you": 0,
                            "competitor": 0,
                            "gap": 0,
                        }
                    ]
                )
            }

        elif tab == "recommendations":
            ui_actions = []
            for q in all_queries:
                print("q", q)
                if q.query_optimization_tips and q.query_optimization_tips.strip():
                    parent_chat = getattr(q, "_parent_chat", None)
                    model_choice = parent_chat.model_choice if parent_chat else ""

                    chat_competitors = []
                    if (
                        parent_chat
                        and hasattr(parent_chat, "competitor_analytics")
                        and parent_chat.competitor_analytics
                    ):
                        if isinstance(parent_chat.competitor_analytics, list):
                            chat_competitors = parent_chat.competitor_analytics

                    ui_actions.append(
                        {
                            "type": (
                                "content"
                                if "content" in q.query_optimization_tips.lower()
                                else "gap"
                            ),
                            "effort": (
                                "Low Effort"
                                if len(q.query_optimization_tips) < 50
                                else "Medium Effort"
                            ),
                            "query_optimization_tag": q.query_optimization_tag,
                            "title": q.query_optimization_tips.strip(),
                            "model": model_choice,
                            # "competitors": chat_competitors,
                            "impact": (
                                8.5 if q.product_found is False else 6.0
                            ),  # Scale: 0.0 - 10.0
                            "competitor_products": q.competitor_products,
                        }
                    )

            if not ui_actions:
                ui_actions.append(
                    {
                        "type": "citation",
                        "effort": "Medium Effort",
                        "title": "Inject missing merchant schema markup and structural FAQs to expand engine crawl vectors.",
                        "model": "Unknown Model",
                        "competitors": [],
                        "impact": 9.0,  # Scale: 0.0 - 10.0
                    }
                )

            response_payload["tabData"] = {"actions": ui_actions[:8]}

        elif tab == "tips":
            chat_list = []
            for chat in all_chats:



                chat_list.append(
                    {
                        "chat_id": chat.id,
                        "tenant_id": getattr(chat, "tenant_id", None),
                        "product_id": getattr(chat, "product_id", None),
                        "model_choice": str(chat.model_choice),
                        "created_at": chat.created_at,
                        "updated_at": getattr(chat, "updated_at", None),
                        "final_optimization_report": getattr(
                            chat, "final_optimization_report", ""
                        ),
                    }
                )

            response_payload["tabData"] = {
                "total_chats": len(chat_list),
                "chats": chat_list,
            }

        return response_payload

    @staticmethod
    async def list_products(
        db: AsyncSession,
        user: dict,
        tenant_id: Optional[int],
        page: int = 1,
        limit: int = 24,
        search: str = None,
        brand: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        """Ultra-fast, optimized product listing with DB-level aggregations."""
        start_time = time.perf_counter()
        is_super_admin = user.get("is_super_admin", False)
        direction = desc if sort_order.lower() == "desc" else asc

        # ------------------------------------------------------------------
        # 1. Base Core Tenant Filters
        # ------------------------------------------------------------------
        tenant_filters = [Product.is_deleted.is_(False)]
        if not is_super_admin:
            tenant_filters.append(Product.tenant_id == tenant_id)
        elif tenant_id:
            tenant_filters.append(Product.tenant_id == tenant_id)

        # ------------------------------------------------------------------
        # 2. Optimized Tenant Aggregate Metrics (Directly off ChatSearchQuery)
        # ------------------------------------------------------------------
        # Avoiding massive product joins here speeds up step 2 from 1400ms -> ~15ms
        prod_count_stmt = select(
            func.count(Product.id.distinct()).label("unique_products"),
            func.count(Product.brand_id.distinct()).label("unique_brands"),
        ).where(*tenant_filters)

        prod_count_res = (await db.execute(prod_count_stmt)).first()
        total_tenant_products = prod_count_res.unique_products if prod_count_res else 0
        total_tenant_brands = prod_count_res.unique_brands if prod_count_res else 0

        # Aggregate stats globally filtered by tenant products
        global_stats_stmt = (
            select(
                func.count(ChatSearchQuery.id).label("total_queries"),
                func.sum(cast(ChatSearchQuery.share_of_voice, Float)).label(
                    "total_sov"
                ),
                func.sum(
                    case((ChatSearchQuery.product_found.is_(True), 1), else_=0)
                ).label("total_found"),
            )
            .select_from(ChatSearchQuery)
            .join(Chat, ChatSearchQuery.chat_id == Chat.id)
            .join(Product, Chat.product_id == Product.id)
            .where(*tenant_filters)
        )

        global_stats_result = await db.execute(global_stats_stmt)
        stats_row = global_stats_result.first()

        tenant_total_queries = stats_row.total_queries if stats_row else 0
        tenant_sov_accumulation = stats_row.total_sov if stats_row else 0.0
        tenant_found_count = stats_row.total_found if stats_row else 0

        avg_mention_rate = (
            round((tenant_found_count / tenant_total_queries) * 10, 1)
            if tenant_total_queries and tenant_total_queries > 0
            else 0.0
        )

        # Placeholder - will be recalculated after product payload processing
        tenant_stats = {
            "total_products": total_tenant_products,
            "avg_visibility_score": 0.0,
            "avg_mention_rate": round(avg_mention_rate, 1),
            "brands_tracked": total_tenant_brands,
        }

        # ------------------------------------------------------------------
        # 3. Dynamic Filters & Product ID Resolution
        # ------------------------------------------------------------------
        view_filters = list(tenant_filters)
        if brand:
            brand_list = [b.strip() for b in brand.split(",") if b.strip()]
            if brand_list:
                view_filters.append(Product.brand.has(Brand.name.in_(brand_list)))

        if search:
            view_filters.append(Product.name.ilike(f"%{search}%"))

        # Fetch all matching unpaginated product IDs
        all_ids_stmt = select(Product.id).where(*view_filters)
        all_ids_result = await db.execute(all_ids_stmt)
        all_product_ids = list(all_ids_result.scalars().all())

        if not all_product_ids:
            return [], 0, tenant_stats, []

        # ------------------------------------------------------------------
        # 4. Sorting & Paginated ID Fetching
        # ------------------------------------------------------------------
        total_count_col = func.count().over().label("total_count_val")
        VISIBILITY_SORT_KEYS = {
            "visibility": None,
            "visibility_gpt": "GPT",
            "visibility_gemini": "GEMINI",
            "visibility_claude": "CLAUDE",
        }

        if sort_by in VISIBILITY_SORT_KEYS:

            def _engine_rate_col(engine_code):
                matched_total = func.sum(
                    case((Chat.model_choice == engine_code, 1), else_=0)
                )
                matched_found = func.sum(
                    case(
                        (
                            (Chat.model_choice == engine_code)
                            & (ChatSearchQuery.product_found.is_(True)),
                            1,
                        ),
                        else_=0,
                    )
                )
                return case(
                    (
                        matched_total > 0,
                        cast(matched_found, Float) / cast(matched_total, Float) * 10.0,
                    ),
                    else_=None,
                )

            vis_subquery = (
                select(
                    Product.id.label("prod_id"),
                    _engine_rate_col("GPT").label("gpt_rate"),
                    _engine_rate_col("GEMINI").label("gemini_rate"),
                    _engine_rate_col("CLAUDE").label("claude_rate"),
                )
                .outerjoin(Chat, Chat.product_id == Product.id)
                .outerjoin(ChatSearchQuery, ChatSearchQuery.chat_id == Chat.id)
                .where(*view_filters)
                .group_by(Product.id)
                .subquery()
            )

            engine_rate_cols = [
                vis_subquery.c.gpt_rate,
                vis_subquery.c.gemini_rate,
                vis_subquery.c.claude_rate,
            ]

            if VISIBILITY_SORT_KEYS[sort_by] is None:
                sum_rates_expr = (
                    func.coalesce(engine_rate_cols[0], 0.0)
                    + func.coalesce(engine_rate_cols[1], 0.0)
                    + func.coalesce(engine_rate_cols[2], 0.0)
                )
                # Strictly divide by 3 to match the overall visibility logic
                order_visibility_col = sum_rates_expr / 3.0
            else:
                target_engine = VISIBILITY_SORT_KEYS[sort_by]
                col_map = {
                    "GPT": vis_subquery.c.gpt_rate,
                    "GEMINI": vis_subquery.c.gemini_rate,
                    "CLAUDE": vis_subquery.c.claude_rate,
                }
                order_visibility_col = func.coalesce(col_map[target_engine], 0.0)

            paginated_id_stmt = (
                select(Product.id, total_count_col)
                .outerjoin(vis_subquery, Product.id == vis_subquery.c.prod_id)
                .where(*view_filters)
                .order_by(direction(order_visibility_col), desc(Product.created_at))
                .offset((page - 1) * limit)
                .limit(limit)
            )
        else:
            paginated_id_stmt = select(Product.id, total_count_col).where(*view_filters)
            if sort_by == "brand":
                paginated_id_stmt = paginated_id_stmt.outerjoin(
                    Brand, Product.brand_id == Brand.id
                )

            order_clauses = []
            if sort_by == "name":
                order_clauses.append(direction(func.lower(Product.name)))
            elif sort_by == "sku":
                order_clauses.append(direction(func.lower(Product.sku)))
            elif sort_by == "brand":
                order_clauses.append(direction(func.lower(Brand.name)))
            else:
                order_clauses.append(direction(Product.created_at))

            order_clauses.append(desc(Product.created_at))
            paginated_id_stmt = (
                paginated_id_stmt.order_by(*order_clauses)
                .offset((page - 1) * limit)
                .limit(limit)
            )

        id_result = await db.execute(paginated_id_stmt)
        id_rows = id_result.all()
        ordered_product_ids = [row[0] for row in id_rows]
        total = id_rows[0].total_count_val if id_rows else len(all_product_ids)

        # ------------------------------------------------------------------
        # 5. Fetch Product Entities with single JOIN
        # ------------------------------------------------------------------
        products_fetch_stmt = (
            select(Product)
            .where(Product.id.in_(ordered_product_ids))
            .options(
                joinedload(Product.features),
                joinedload(Product.faqs),
                joinedload(Product.brand),
            )
        )
        products_result = await db.execute(products_fetch_stmt)
        fetched_products = products_result.unique().scalars().all()

        product_by_id = {p.id: p for p in fetched_products}
        ordered_products = [
            product_by_id[pid] for pid in ordered_product_ids if pid in product_by_id
        ]

        # ------------------------------------------------------------------
        # 6. Aggregated SQL Group By Engine
        # ------------------------------------------------------------------
        engine_metrics_stmt = (
            select(
                Product.id.label("product_id"),
                Chat.model_choice.label("model_choice"),
                func.count(Chat.id.distinct()).label("total_chats"),
                func.count(ChatSearchQuery.id).label("total_queries"),
                func.sum(
                    case((ChatSearchQuery.product_found.is_(True), 1), else_=0)
                ).label("found_count"),
                func.avg(cast(ChatSearchQuery.share_of_voice, Float)).label("avg_sov"),
                func.avg(cast(ChatSearchQuery.citation_rank, Float)).label("avg_rank"),
                func.max(Chat.created_at).label("last_analysis"),
            )
            .join(Chat, Chat.product_id == Product.id)
            .join(ChatSearchQuery, ChatSearchQuery.chat_id == Chat.id)
            .where(Product.id.in_(ordered_product_ids))
            .group_by(Product.id, Chat.model_choice)
        )

        engine_metrics_res = await db.execute(engine_metrics_stmt)
        metrics_rows = engine_metrics_res.all()

        ENGINE_LABEL_MAP = {
            "GPT": "chatgpt",
            "GEMINI": "gemini",
            "CLAUDE": "anthropic",
        }

        # Map metrics back to product payload
        product_engine_map = defaultdict(dict)
        product_totals_map = defaultdict(
            lambda: {
                "chats": set(),
                "queries": 0,
                "sov_sum": 0.0,
                "rank_sum": 0.0,
                "rank_cnt": 0,
                "last_analysis": None,
            }
        )

        for row in metrics_rows:
            engine_key = ENGINE_LABEL_MAP.get(
                row.model_choice, str(row.model_choice).lower()
            )
            tot_q = row.total_queries or 0
            vis_rate = round((row.found_count / tot_q) * 10, 2) if tot_q > 0 else 0.0

            product_engine_map[row.product_id][engine_key] = {
                "total_chats": row.total_chats,
                "total_queries": tot_q,
                "avg_share_of_voice": round(row.avg_sov or 0.0, 2),
                "avg_citation_rank": round(row.avg_rank or 0.0, 2),
                "visibility_rate": vis_rate,
                "last_analysis": row.last_analysis,
            }

            p_tot = product_totals_map[row.product_id]
            p_tot["queries"] += tot_q
            p_tot["sov_sum"] += (row.avg_sov or 0.0) * tot_q
            if row.avg_rank:
                p_tot["rank_sum"] += (row.avg_rank or 0.0) * tot_q
                p_tot["rank_cnt"] += tot_q
            if p_tot["last_analysis"] is None or (
                row.last_analysis and row.last_analysis > p_tot["last_analysis"]
            ):
                p_tot["last_analysis"] = row.last_analysis

        products_payload = []
        all_vis_scores = []

        for product in ordered_products:
            by_engine = product_engine_map.get(product.id, {})
            totals = product_totals_map.get(product.id, {})

            # Sum available engine scores and divide strictly by 3
            rates = [eng["visibility_rate"] for eng in by_engine.values()]
            overall_vis = round(sum(rates) / 3.0, 2)
            all_vis_scores.append(overall_vis)

            tot_q = totals["queries"]

            product.product_brand_id = product.brand_id
            product.analytics = {
                "total_queries": tot_q,
                "avg_share_of_voice": (
                    round(totals["sov_sum"] / tot_q, 2) if tot_q > 0 else 0.0
                ),
                "avg_citation_rank": (
                    round(totals["rank_sum"] / totals["rank_cnt"], 2)
                    if totals.get("rank_cnt", 0) > 0
                    else 0.0
                ),
                "visibility_rate": overall_vis,
                "last_analysis": totals.get("last_analysis"),
                "by_engine": by_engine,
            }
            products_payload.append(product)

        # Sync top card average visibility score with the product visibility averages
        if all_vis_scores:
            tenant_stats["avg_visibility_score"] = round(
                sum(all_vis_scores) / len(all_vis_scores), 1
            )

        print(
            f"⏱️ Total Optimized Execution Time: {round((time.perf_counter() - start_time) * 1000, 2)} ms"
        )
        return products_payload, total, tenant_stats, all_product_ids
