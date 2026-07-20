import statistics
import json
from collections import defaultdict
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, String, Float, case, distinct
from sqlalchemy.orm import selectinload
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
        """
        is_super_admin = user.get("is_super_admin", False)

        # ------------------------------------------------------------------
        # 1. Unified Eager-Load Query Execution (Optimized by Tab Type)
        # ------------------------------------------------------------------
        # We explicitly eager-load Product -> Chat -> ChatSearchQuery
        load_options = [
            selectinload(Product.brand),
            selectinload(Product.chats).selectinload(Chat.search_queries),
        ]

        # Only load heavy relationship arrays if requested by the visibility layout
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

        # We loop and save a dynamic reference back to the parent Chat
        # so we can access chat.model_choice later without lazy-load issues.
        for chat in all_chats:
            for q in chat.search_queries or []:
                q._parent_chat = chat
                all_queries.append(q)

        total_queries = len(all_queries)

        # ------------------------------------------------------------------
        # 3. Dynamic Platform Breakdown Engine Analysis (ADAPTED TO DB COLS)
        # ------------------------------------------------------------------
        engine_scores = {
            "chatgpt": 0.0,
            "gemini": 0.0,
            "claude": 0.0,
        }
        engine_counts = {"chatgpt": 0, "gemini": 0, "claude": 0}

        # Mapper translates database keys into frontend dashboard keys
        platform_mapper = {
            "openai": "chatgpt",
            "google": "gemini",
            "gemini": "gemini",
            "anthropic": "claude",
        }

        for q in all_queries:
            breakdown = q.platform_breakdown or {}
            for platform, values in breakdown.items():
                norm_platform = platform.lower()

                # Dynamic translation from DB keys to payload keys
                mapped_engine = platform_mapper.get(norm_platform, norm_platform)

                if mapped_engine in engine_scores:
                    engine_scores[mapped_engine] += float(values)
                    engine_counts[mapped_engine] += 1

        engine_visibility_summary = {}
        for engine in engine_scores.keys():
            count = engine_counts[engine]
            engine_visibility_summary[engine] = (
                round((engine_scores[engine] / count) * 10, 1) if count > 0 else 0.0
            )

        # Determine Global AI Visibility Baseline
        valid_scores = [v for v in engine_visibility_summary.values() if v > 0]
        ai_visibility_score = (
            round(statistics.mean(valid_scores)) if valid_scores else 0
        )

        # Calculate Mention Rate based on product discovery frequencies
        found_count = sum(1 for q in all_queries if q.product_found is True)
        mention_rate = (
            round((found_count / total_queries) * 100, 1) if total_queries > 0 else 0.0
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
                    "visibilityScore": ai_visibility_score,
                    "mentionRate": mention_rate,
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
        # 5. Dynamic Tab Processing Matrix (Computes ONLY requested slice)
        # ------------------------------------------------------------------
        if tab == "visibility":
            # If relationship was fetched, use it to ensure absolute real-time accuracy
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

            # A. First check and parse from product.competitor_analytics JSON field
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

            # B. Fallback to query-level mentions if JSON field is empty
            if not competitors_set:
                for q in all_queries:
                    if q.competitors_mentioned:
                        competitors_set.update(q.competitors_mentioned)

            ui_competitors = []
            for comp in list(competitors_set):
                ui_competitors.append(
                    {
                        "name": comp,
                        "chatGPT": max(
                            0.0,
                            round(engine_visibility_summary.get("chatgpt", 0.0) * 0.9),
                        ),
                        "gemini": max(
                            0.0,
                            round(engine_visibility_summary.get("gemini", 0.0) * 1.1),
                        ),
                        "claude": max(
                            0.0,
                            round(engine_visibility_summary.get("claude", 0.0) * 0.95),
                        ),
                        "avg": max(0.0, round(ai_visibility_score * 0.95)),
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

            schema_gaps = []
            if not product.sku:
                schema_gaps.append(
                    {
                        "title": "Missing Structural SKU Schema Identification",
                        "you": 0,
                        "top": 100,
                        "status": "High",
                        "gain": "+15 points",
                    }
                )
            if not product.mpn:
                schema_gaps.append(
                    {
                        "title": "Missing MPN Global Identification Tags",
                        "you": 0,
                        "top": 90,
                        "status": "Medium",
                        "gain": "+8 points",
                    }
                )
            if total_reviews < 50:
                schema_gaps.append(
                    {
                        "title": "Review Multi-platform Citations Deficit",
                        "you": 35,
                        "top": 85,
                        "status": "High",
                        "gain": "+22 points",
                    }
                )

            if not schema_gaps:
                schema_gaps.append(
                    {
                        "title": "FAQ Context Synchronization Coverage",
                        "you": 75,
                        "top": 95,
                        "status": "Low",
                        "gain": "+5 points",
                    }
                )

            response_payload["tabData"] = {
                "competitors": ui_competitors,
                "radarData": [
                    {
                        "subject": "Visibility Index",
                        "You": ai_visibility_score,
                        "Competitor": round(ai_visibility_score * 0.9),
                    },
                    {
                        "subject": "Citation Share",
                        "You": min(100, int(mention_rate)),
                        "Competitor": 65,
                    },
                    {
                        "subject": "Reviews Count",
                        "You": min(100, total_reviews),
                        "Competitor": 75,
                    },
                    {
                        "subject": "FAQ Coverage",
                        "You": min(100, total_faqs * 5),
                        "Competitor": 80,
                    },
                ],
                "radarSummaryText": f"Currently outperforming {len(competitors_set)} competitor tracking profiles.",
                "priorityCountText": f"{len(schema_gaps)} Content Gaps Identified",
                "gaps": schema_gaps,
            }

        elif tab == "citation":
            sources_set = set()
            for q in all_queries:
                if q.citing_sources:
                    sources_set.update(q.citing_sources)

            ui_citations = []
            for idx, source in enumerate(list(sources_set)):
                mentions_count = sum(
                    1
                    for q in all_queries
                    if q.citing_sources and source in q.citing_sources
                )
                ui_citations.append(
                    {
                        "source": source.replace("https://", "")
                        .replace("www.", "")
                        .split("/")[0],
                        "authority": 85 if idx % 2 == 0 else 72,
                        "you": mentions_count,
                        "competitor": mentions_count + 2,
                        "gap": -2,
                    }
                )

            response_payload["tabData"] = {
                "citations": (
                    ui_citations
                    if ui_citations
                    else [
                        {
                            "source": "No Citations Tracked",
                            "authority": 0,
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
                if q.query_optimization_tips and q.query_optimization_tips.strip():
                    # 1. Resolve parent Chat safely
                    parent_chat = getattr(q, "_parent_chat", None)

                    # 2. Extract model choice from parent chat
                    model_choice = parent_chat.model_choice if parent_chat else ""

                    # 3. Extract the competitor_analytics JSON list directly from the parent chat
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
                            "competitors": chat_competitors,  # Structured JSON list from Chat model
                            "impact": 85 if q.product_found is False else 60,
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
                        "impact": 90,
                    }
                )

            response_payload["tabData"] = {"actions": ui_actions[:8]}

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
    ):
        """List products with GEO analytics summary and correct admin filtering.

        Optimized Version: Consolidates mathematical aggregates down to the
        database layer to eliminate heavy application loop overhead.
        """
        is_super_admin = user.get("is_super_admin", False)

        # ------------------------------------------------------------------
        # 1. Base Core Tenant Filters (Must mirror Dashboard exactly)
        # ------------------------------------------------------------------
        tenant_filters = [Product.is_deleted.is_(False)]
        if not is_super_admin:
            tenant_filters.append(Product.tenant_id == tenant_id)
        elif tenant_id:
            tenant_filters.append(Product.tenant_id == tenant_id)

        # ------------------------------------------------------------------
        # 2. Optimized Global Aggregate Metrics Query (Calculated at DB Layer)
        # ------------------------------------------------------------------
        # Instead of pulling thousands of raw rows into Python memory,
        # let SQL calculate the global sums instantly.
        global_stats_stmt = (
            select(
                func.count(ChatSearchQuery.id).label("total_queries"),
                func.sum(cast(ChatSearchQuery.share_of_voice, Float)).label(
                    "total_sov"
                ),
                func.sum(
                    case((ChatSearchQuery.product_found.is_(True), 1), else_=0)
                ).label("total_found"),
                func.count(distinct(Product.id)).label("unique_products"),
                func.count(distinct(Product.brand_id)).label("unique_brands"),
            )
            .join(Chat, ChatSearchQuery.chat_id == Chat.id)
            .join(Product, Chat.product_id == Product.id)
            .join(
                ChatGEOAuditRecord,
                (ChatGEOAuditRecord.tenant_id == Product.tenant_id)
                & (cast(Chat.model_choice, String) == ChatGEOAuditRecord.model_used),
            )
            .where(*tenant_filters)
        )

        global_stats_result = await db.execute(global_stats_stmt)
        stats_row = global_stats_result.first()

        tenant_total_queries = stats_row.total_queries or 0
        tenant_sov_accumulation = stats_row.total_sov or 0.0
        tenant_found_count = stats_row.total_found or 0

        avg_visibility_score = (
            (tenant_sov_accumulation / tenant_total_queries)
            if tenant_total_queries > 0
            else 0.0
        )
        avg_mention_rate = (
            (tenant_found_count / tenant_total_queries) * 100
            if tenant_total_queries > 0
            else 0.0
        )

        tenant_stats = {
            "total_products": stats_row.unique_products or 0,
            "avg_visibility_score": round(avg_visibility_score, 1),
            "avg_mention_rate": round(avg_mention_rate, 1),
            "brands_tracked": stats_row.unique_brands or 0,
        }

        # ------------------------------------------------------------------
        # 3. Build Dynamic UI View Set (Search, Filters, Pagination)
        # ------------------------------------------------------------------
        view_filters = list(tenant_filters)

        if brand:
            brand_list = [b.strip() for b in brand.split(",") if b.strip()]
            if brand_list:
                view_filters.append(Product.brand.has(Brand.name.in_(brand_list)))

        if search:
            view_filters.append(Product.name.ilike(f"%{search}%"))

        # Fetch total records matching active viewport filters
        count_stmt = select(func.count(Product.id)).where(*view_filters)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Paginated fetch with optimized join relationship loads
        paginated_query = (
            select(Product)
            .where(*view_filters)
            .options(
                selectinload(Product.features),
                selectinload(Product.faqs),
                selectinload(Product.brand),
            )
            .order_by(Product.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )

        paginated_result = await db.execute(paginated_query)
        paginated_products = paginated_result.scalars().all()

        if not paginated_products:
            return [], total, tenant_stats

        # ------------------------------------------------------------------
        # 4. Target Specific Metrics for Only the Paginated Products
        # ------------------------------------------------------------------
        # Instead of grouping metrics for every product in the system, we only
        # query metrics matching the subset array of ids returned by pagination.
        paginated_product_ids = [p.id for p in paginated_products]

        prod_metrics_stmt = (
            select(
                Product.id.label("product_id"),
                ChatSearchQuery,
                Chat.id.label("chat_id"),
                Chat.created_at.label("chat_created_at"),
            )
            .join(Chat, ChatSearchQuery.chat_id == Chat.id)
            .join(Product, Chat.product_id == Product.id)
            .join(
                ChatGEOAuditRecord,
                (ChatGEOAuditRecord.tenant_id == Product.tenant_id)
                & (cast(Chat.model_choice, String) == ChatGEOAuditRecord.model_used),
            )
            .where(Product.id.in_(paginated_product_ids))
        )

        prod_metrics_result = await db.execute(prod_metrics_stmt)
        prod_results = prod_metrics_result.all()

        product_metrics_map = defaultdict(list)
        for r in prod_results:
            product_metrics_map[r.product_id].append(
                (r.ChatSearchQuery, r.chat_id, r.chat_created_at)
            )

        # ------------------------------------------------------------------
        # 5. Map Inner Entity Metrics Onto Paginated Output Payload
        # ------------------------------------------------------------------
        products_payload = []
        for product in paginated_products:
            prod_rows = product_metrics_map.get(product.id, [])

            prod_total_queries = len(prod_rows)
            unique_chats = set()

            prod_found_count = 0
            rank_sum = 0
            valid_rank_count = 0
            citation_counter = 0
            prod_sov_accumulation = 0.0
            competitor_counter = 0
            last_analysis_time = None

            for q_row, chat_id, chat_created_at in prod_rows:
                unique_chats.add(chat_id)

                if chat_created_at:
                    if (
                        last_analysis_time is None
                        or chat_created_at > last_analysis_time
                    ):
                        last_analysis_time = chat_created_at

                if q_row.product_found is True:
                    prod_found_count += 1

                prod_sov_accumulation += float(q_row.share_of_voice or 0.0)

                if q_row.citation_rank is not None:
                    rank_sum += float(q_row.citation_rank)
                    valid_rank_count += 1

                sources = q_row.citing_sources or []
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources)
                    except:
                        sources = []
                citation_counter += len(sources)

                competitors = q_row.competitors_mentioned or []
                if isinstance(competitors, str):
                    try:
                        competitors = json.loads(competitors)
                    except:
                        competitors = []
                competitor_counter += len(competitors)

            product.product_brand_id = product.brand_id

            product.analytics = {
                "total_chats": len(unique_chats),
                "total_queries": prod_total_queries,
                "avg_share_of_voice": (
                    round((prod_sov_accumulation / prod_total_queries), 2)
                    if prod_total_queries > 0
                    else 0.0
                ),
                "avg_citation_rank": (
                    round((rank_sum / valid_rank_count), 2)
                    if valid_rank_count > 0
                    else 0.0
                ),
                "visibility_rate": (
                    round((prod_found_count / prod_total_queries) * 100, 2)
                    if prod_total_queries > 0
                    else 0.0
                ),
                "competitor_mentions": competitor_counter,
                "citation_count": citation_counter,
                "last_analysis": last_analysis_time,
            }
            products_payload.append(product)

        return products_payload, total, tenant_stats
