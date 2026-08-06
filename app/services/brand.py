import math
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, case, desc, cast, Numeric, asc


from fastapi import HTTPException, status

from app.models import Brand, User, Product, Chat, ChatSearchQuery, BrandAnalytic


class BrandService:
    """Service class for brand related operations"""

    @staticmethod
    async def _save(db: AsyncSession):
        """commit helper"""

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def _get_brand(
        db: AsyncSession,
        brand_id: int,
    ):
        """fetch brand"""

        result = await db.execute(
            select(Brand).where(Brand.id == brand_id, Brand.is_deleted == False)
        )

        brand = result.scalar_one_or_none()

        if not brand:
            raise ValueError("Brand not found")

        return brand

    @staticmethod
    async def _brand_duplication_validation(
        db: AsyncSession,
        tenant_id: int,
        name: str,
        brand_id: int = None,
    ):
        """duplicate validation"""

        query = select(Brand).where(
            Brand.tenant_id == tenant_id,
            Brand.name == name,
            Brand.is_deleted == False,
        )

        if brand_id:
            query = query.where(Brand.id != brand_id)

        result = await db.execute(query)

        if result.scalar_one_or_none():
            raise ValueError("Brand already exists")

    @staticmethod
    async def create_brand(
        db: AsyncSession,
        data: dict,
        user: dict,
        tenant_id: int,
    ):
        """create brand"""

        name = data.get("name")

        if not tenant_id:
            raise ValueError("tenant_id is required")

        if not name:
            raise ValueError("name is required")

        await BrandService._brand_duplication_validation(
            db=db, tenant_id=tenant_id, name=name
        )

        brand_obj = Brand(
            tenant_id=tenant_id,
            name=name,
            domain=data.get("domain"),
            industry=data.get("industry"),
            country=data.get("country"),
            competitor=data.get("competitor"),
            created_by=int(user.get("sub")),
        )

        db.add(brand_obj)

        await BrandService._save(db)
        await db.refresh(brand_obj)

        return brand_obj

    @staticmethod
    async def update_brand(
        db: AsyncSession,
        brand_id: int,
        data: dict,
        user: dict,
    ):
        """update brand"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        new_name = data.get("name", brand.name)

        await BrandService._brand_duplication_validation(
            db=db, tenant_id=brand.tenant_id, name=new_name, brand_id=brand.id
        )

        fields = ["name", "domain", "industry", "country"]

        for field in fields:
            value = data.get(field)

            if value is not None:
                setattr(brand, field, value)

        brand.last_updated_by = int(user.get("sub"))

        await BrandService._save(db)

        await db.refresh(brand)

        return brand

    @staticmethod
    async def soft_delete_brand(
        db: AsyncSession,
        brand_id: int,
        user: User,
    ):
        """activate / deactivate"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        brand.is_active = not brand.is_active

        brand.last_updated_by = user.id

        await BrandService._save(db)

        return brand

    @staticmethod
    async def delete_brand(
        db: AsyncSession,
        brand_id: int,
        user: dict,
    ):
        """logical delete"""

        brand = await BrandService._get_brand(db=db, brand_id=brand_id)

        brand.is_deleted = True
        brand.deleted_by = int(user.get("sub"))

        await BrandService._save(db)

        return True

    @staticmethod
    async def meta_list(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
    ):
        """Return brands metadata for dropdowns"""

        query = select(Brand.id, Brand.name).order_by(Brand.name.asc())

        query = query.where(
            Brand.tenant_id == tenant_id,
            Brand.is_deleted == False,
        )

        result = await db.execute(query)

        brands = result.all()

        return [{"id": brand.id, "value": brand.name} for brand in brands]

    @staticmethod
    async def list_brands(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
        page: int = 1,
        limit: int = 24,
        search: Optional[str] = None,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        List brands with aggregated GEO visibility and mention rates.
        Aligned with list_products calculation logic (0.0 to 10.0 scale based on product_found rate).
        """

        # ------------------------------------------------------------------
        # 1. Permission Check
        # ------------------------------------------------------------------
        is_super_admin = user.get("is_super_admin", False)
        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # ------------------------------------------------------------------
        # 2. Metric Aggregations (Aligned with list_products logic)
        # ------------------------------------------------------------------
        # Convert product_found boolean to numeric float (1.0 or 0.0)
        found_numeric = case((ChatSearchQuery.product_found.is_(True), 1.0), else_=0.0)

        # Visibility / Mention Rate: Scale 0.0 - 10.0
        # Formula: (total_found_queries / total_queries) * 10.0
        visibility_expr = func.round(
            cast(
                func.coalesce(
                    (
                        func.sum(found_numeric)
                        / func.nullif(func.count(ChatSearchQuery.id), 0)
                    )
                    * 10.0,
                    0.0,
                ),
                Numeric,
            ),
            1,
        )

        mention_rate_expr = visibility_expr
        products_count_expr = func.count(func.distinct(Product.id))

        # ------------------------------------------------------------------
        # 3. Create Aggregation Subquery
        # ------------------------------------------------------------------
        agg_subquery = (
            select(
                Brand.id.label("brand_id"),
                visibility_expr.label("visibility_score"),
                mention_rate_expr.label("mention_rate"),
                products_count_expr.label("products_count"),
            )
            .outerjoin(
                Product,
                (Product.brand_id == Brand.id) & (Product.is_deleted.is_(False)),
            )
            .outerjoin(Chat, Chat.product_id == Product.id)
            .outerjoin(ChatSearchQuery, ChatSearchQuery.chat_id == Chat.id)
            .where(Brand.tenant_id == tenant_id, Brand.is_deleted.is_(False))
            .group_by(Brand.id)
        ).subquery("agg")

        # ------------------------------------------------------------------
        # 4. Main Query: Join Brand with Calculated Aggregates
        # ------------------------------------------------------------------
        stmt = select(
            Brand,
            agg_subquery.c.visibility_score,
            agg_subquery.c.mention_rate,
            agg_subquery.c.products_count,
        ).join(agg_subquery, Brand.id == agg_subquery.c.brand_id)

        # ------------------------------------------------------------------
        # 5. Apply Search Filter
        # ------------------------------------------------------------------
        if search and search.strip():
            clean_search = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Brand.name.ilike(clean_search),
                    Brand.industry.ilike(clean_search),
                )
            )

        # ------------------------------------------------------------------
        # 6. Apply Dynamic Outer Sorting
        # ------------------------------------------------------------------
        is_desc = (sort_order or "").lower() == "desc"

        if sort_by == "name":
            sort_col = func.lower(Brand.name)
        elif sort_by == "country":
            sort_col = func.lower(func.coalesce(Brand.countries[0], ""))
        elif sort_by == "industry":
            sort_col = func.lower(func.coalesce(Brand.industry, ""))
        elif sort_by in ["visibility", "visibility_score"]:
            sort_col = agg_subquery.c.visibility_score
        elif sort_by in ["mention_rate", "mentionRate"]:
            sort_col = agg_subquery.c.mention_rate
        elif sort_by in ["products_count", "productsCount"]:
            sort_col = agg_subquery.c.products_count
        else:
            sort_col = Brand.created_at

        if is_desc:
            stmt = stmt.order_by(sort_col.desc().nulls_last())
        else:
            stmt = stmt.order_by(sort_col.asc().nulls_last())

        # ------------------------------------------------------------------
        # 7. Total Count Query for Pagination
        # ------------------------------------------------------------------
        count_query = select(func.count(func.distinct(Brand.id))).where(
            Brand.tenant_id == tenant_id, Brand.is_deleted.is_(False)
        )
        if search and search.strip():
            clean_search = f"%{search.strip()}%"
            count_query = count_query.where(
                or_(
                    Brand.name.ilike(clean_search),
                    Brand.industry.ilike(clean_search),
                )
            )

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # ------------------------------------------------------------------
        # 8. Pagination Execution
        # ------------------------------------------------------------------
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        result = await db.execute(stmt)
        rows = result.all()

        # ------------------------------------------------------------------
        # 9. Format Output Payload
        # ------------------------------------------------------------------
        brand_list = []
        for brand, visibility_score, mention_rate, products_count in rows:
            country_val = "-"
            if hasattr(brand, "countries") and brand.countries:
                if isinstance(brand.countries, list):
                    country_val = ", ".join(brand.countries)
                else:
                    country_val = str(brand.countries)

            brand_dict = {
                "id": brand.id,
                "name": brand.name,
                "website_url": getattr(brand, "website_url", None),
                "industry": getattr(brand, "industry", None),
                "country": country_val,
                "countries": getattr(brand, "countries", []),
                "description": getattr(brand, "description", None),
                "created_at": brand.created_at,
                "updated_at": getattr(brand, "updated_at", None),
                "productsCount": products_count or 0,
                "visibilityScore": float(visibility_score or 0.0),
                "mentionRate": float(mention_rate or 0.0),
            }
            brand_list.append(brand_dict)

        pagination = {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": math.ceil(total / limit) if limit > 0 else 1,
        }

        return brand_list, pagination

    @staticmethod
    async def get_brands_analytics_summary(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
        page: int = 1,
        limit: int = 24,
        search: Optional[str] = None,
        model_filter: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = "desc",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Groups analytics data by Brand and returns each brand along with its
        aggregated average metrics, run stats, with search, pagination, and sorting.
        """
        # 1. Permission Check
        is_super_admin = user.get("is_super_admin", False)
        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # Reusable Expressions for Aggregates
        total_runs_expr = func.count(BrandAnalytic.id)
        avg_overall_expr = func.avg(BrandAnalytic.overall_score)
        avg_mention_expr = func.avg(BrandAnalytic.mention_score)
        avg_citation_expr = func.avg(BrandAnalytic.citation_score)
        avg_sov_expr = func.avg(BrandAnalytic.share_of_voice_score)
        avg_product_expr = func.avg(BrandAnalytic.product_coverage_score)
        avg_category_expr = func.avg(BrandAnalytic.category_coverage_score)
        avg_knowledge_expr = func.avg(BrandAnalytic.knowledge_graph_score)
        avg_authority_expr = func.avg(BrandAnalytic.authority_score)
        avg_sentiment_expr = func.avg(BrandAnalytic.sentiment_score)
        latest_run_expr = func.max(BrandAnalytic.created_at)

        # 2. Build Base Aggregation Query
        stmt = select(
            Brand.id.label("brand_id"),
            Brand.name.label("brand_name"),
            Brand.domain.label("domain"),
            Brand.industry.label("industry"),
            Brand.country.label("country"),
            Brand.competitor.label("is_competitor"),
            total_runs_expr.label("total_analytic_runs"),
            avg_overall_expr.label("avg_overall_score"),
            avg_mention_expr.label("avg_mention_score"),
            avg_citation_expr.label("avg_citation_score"),
            avg_sov_expr.label("avg_share_of_voice_score"),
            avg_product_expr.label("avg_product_coverage_score"),
            avg_category_expr.label("avg_category_coverage_score"),
            avg_knowledge_expr.label("avg_knowledge_graph_score"),
            avg_authority_expr.label("avg_authority_score"),
            avg_sentiment_expr.label("avg_sentiment_score"),
            latest_run_expr.label("latest_run_at"),
        ).outerjoin(BrandAnalytic, Brand.id == BrandAnalytic.brand_id)

        stmt = stmt.where(Brand.tenant_id == tenant_id)

        # Optional Model Filter (e.g., GPT, CLAUDE, GEMINI)
        if model_filter:
            stmt = stmt.where(BrandAnalytic.model_choice == model_filter)

        # Search filter (by brand name or domain)
        if search and search.strip():
            search_term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Brand.name).like(search_term),
                    func.lower(Brand.domain).like(search_term),
                )
            )

        # Group by Brand fields
        stmt = stmt.group_by(
            Brand.id,
            Brand.name,
            Brand.domain,
            Brand.industry,
            Brand.country,
            Brand.competitor,
        )

        # Get Total Count for Pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_records = (await db.execute(count_stmt)).scalar() or 0

        # Dynamic Sorting Map
        sort_columns_map = {
            "brand_name": Brand.name,
            "domain": Brand.domain,
            "industry": Brand.industry,
            "country": Brand.country,
            "total_runs": total_runs_expr,
            "total_analytic_runs": total_runs_expr,
            "overall_score": avg_overall_expr,
            "mention_score": avg_mention_expr,
            "citation_score": avg_citation_expr,
            "share_of_voice_score": avg_sov_expr,
            "product_coverage_score": avg_product_expr,
            "category_coverage_score": avg_category_expr,
            "knowledge_graph_score": avg_knowledge_expr,
            "authority_score": avg_authority_expr,
            "sentiment_score": avg_sentiment_expr,
            "latest_run_at": latest_run_expr,
        }

        # Apply Sort Order
        if sort_by and sort_by in sort_columns_map:
            target_expr = sort_columns_map[sort_by]
            order_fn = asc if sort_order and sort_order.lower() == "asc" else desc
            stmt = stmt.order_by(order_fn(target_expr), Brand.name.asc())
        else:
            # Default sorting fallback
            stmt = stmt.order_by(desc(latest_run_expr), Brand.name.asc())

        # Paginate
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        result = await db.execute(stmt)
        rows = result.all()

        # 3. Format Output Payload
        formatted_list = []
        for row in rows:
            formatted_list.append(
                {
                    "brand_id": row.brand_id,
                    "brand_name": row.brand_name,
                    "domain": row.domain,
                    "industry": row.industry,
                    "country": row.country,
                    "is_competitor": row.is_competitor,
                    "total_runs": row.total_analytic_runs or 0,
                    "latest_run_at": row.latest_run_at,
                    "averages": {
                        "overall_score": (
                            round(row.avg_overall_score, 2)
                            if row.avg_overall_score is not None
                            else 0.0
                        ),
                        "mention_score": (
                            round(row.avg_mention_score, 2)
                            if row.avg_mention_score is not None
                            else 0.0
                        ),
                        "citation_score": (
                            round(row.avg_citation_score, 2)
                            if row.avg_citation_score is not None
                            else 0.0
                        ),
                        "share_of_voice_score": (
                            round(row.avg_share_of_voice_score, 2)
                            if row.avg_share_of_voice_score is not None
                            else 0.0
                        ),
                        "product_coverage_score": (
                            round(row.avg_product_coverage_score, 2)
                            if row.avg_product_coverage_score is not None
                            else 0.0
                        ),
                        "category_coverage_score": (
                            round(row.avg_category_coverage_score, 2)
                            if row.avg_category_coverage_score is not None
                            else 0.0
                        ),
                        "knowledge_graph_score": (
                            round(row.avg_knowledge_graph_score, 2)
                            if row.avg_knowledge_graph_score is not None
                            else 0.0
                        ),
                        "authority_score": (
                            round(row.avg_authority_score, 2)
                            if row.avg_authority_score is not None
                            else 0.0
                        ),
                        "sentiment_score": (
                            round(row.avg_sentiment_score, 2)
                            if row.avg_sentiment_score is not None
                            else 0.0
                        ),
                    },
                }
            )

        pagination = {
            "page": page,
            "limit": limit,
            "total": total_records,
            "total_pages": math.ceil(total_records / limit) if limit > 0 else 1,
        }

        return formatted_list, pagination

    @staticmethod
    async def get_brand_analytics_detail(
        db: AsyncSession,
        brand_id: int,
        user: dict,
        tenant_id: int,
        model_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves detailed, brand-centric analytics overview including:
        - Overall averaged scores across all runs.
        - Performance breakdown grouped by AI Model (GPT, CLAUDE, GEMINI).
        - Latest AI Diagnosis & Recommendations.
        - Chronological history of all analytic runs for this brand.
        """
        # 1. Permission Check
        is_super_admin = user.get("is_super_admin", False)
        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # 2. Fetch Brand
        brand = await BrandService._get_brand(db=db, brand_id=brand_id)
        if brand.tenant_id != tenant_id and not is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Brand does not belong to your tenant.",
            )

        # 3. Query all BrandAnalytic runs for this brand
        stmt = (
            select(BrandAnalytic)
            .where(
                BrandAnalytic.brand_id == brand_id,
            )
            .order_by(desc(BrandAnalytic.created_at))
        )

        if model_filter:
            stmt = stmt.where(BrandAnalytic.model_choice == model_filter)

        result = await db.execute(stmt)
        analytics = result.scalars().all()

        if not analytics:
            # Return baseline brand info if no analytics runs exist yet
            return {
                "brand": {
                    "id": brand.id,
                    "name": brand.name,
                    "domain": brand.domain,
                    "industry": brand.industry,
                    "country": brand.country,
                    "is_competitor": brand.competitor,
                },
                "total_runs": 0,
                "overall_averages": {},
                "model_breakdown": {},
                "latest_diagnosis": {},
                "latest_recommendations": [],
                "run_history": [],
            }

        # 4. Calculate Overall Aggregated Averages across all runs
        total_runs = len(analytics)
        metrics_keys = [
            "overall_score",
            "mention_score",
            "citation_score",
            "share_of_voice_score",
            "product_coverage_score",
            "category_coverage_score",
            "knowledge_graph_score",
            "authority_score",
            "sentiment_score",
        ]

        overall_totals = {key: 0.0 for key in metrics_keys}
        metrics_counts = {key: 0 for key in metrics_keys}

        # Model breakdown container: { "GPT": { "count": X, "scores": {...} } }
        model_groups: Dict[str, Dict[str, Any]] = {}

        for run in analytics:
            model_key = (
                run.model_choice.value
                if hasattr(run.model_choice, "value")
                else str(run.model_choice)
            )

            if model_key not in model_groups:
                model_groups[model_key] = {
                    "total_runs": 0,
                    "totals": {key: 0.0 for key in metrics_keys},
                    "counts": {key: 0 for key in metrics_keys},
                    "sentiments": set(),
                }

            model_groups[model_key]["total_runs"] += 1
            if run.sentiment:
                model_groups[model_key]["sentiments"].add(run.sentiment)

            # Sum metrics for global & model-specific averages
            for key in metrics_keys:
                val = getattr(run, key, None)
                if val is not None:
                    overall_totals[key] += float(val)
                    metrics_counts[key] += 1
                    model_groups[model_key]["totals"][key] += float(val)
                    model_groups[model_key]["counts"][key] += 1

        # Format global overall averages
        overall_averages = {
            key: (
                round(overall_totals[key] / metrics_counts[key], 2)
                if metrics_counts[key] > 0
                else 0.0
            )
            for key in metrics_keys
        }

        # Format per-model averages
        formatted_model_breakdown = {}
        for model_name, data in model_groups.items():
            formatted_model_breakdown[model_name] = {
                "total_runs": data["total_runs"],
                "sentiments": list(data["sentiments"]),
                "averages": {
                    key: (
                        round(data["totals"][key] / data["counts"][key], 2)
                        if data["counts"][key] > 0
                        else 0.0
                    )
                    for key in metrics_keys
                },
            }

        # 5. Extract Latest Run Highlights
        latest_run = analytics[0]
        latest_diagnosis = latest_run.diagnosis or {}
        latest_recommendations = latest_run.recommendations or []
        latest_dimensions = latest_run.dimensions or []
        latest_competitors = latest_run.competitors or []
        latest_categories = latest_run.categories or []

        # 6. Format Chronological Run History
        run_history = []
        for run in analytics:
            model_key = (
                run.model_choice.value
                if hasattr(run.model_choice, "value")
                else str(run.model_choice)
            )

            # Count prompts run during this batch
            prompts_count = 0
            if isinstance(run.prompt_factory, list):
                prompts_count = len(run.prompt_factory)
            elif isinstance(run.generated_prompts, list):
                prompts_count = len(run.generated_prompts)

            run_history.append(
                {
                    "analytic_id": run.id,
                    "model_choice": model_key,
                    "created_at": run.created_at,
                    "prompts_tested_count": prompts_count,
                    "overall_score": run.overall_score,
                    "sentiment": run.sentiment,
                    "scores": {
                        "mention_score": run.mention_score,
                        "citation_score": run.citation_score,
                        "share_of_voice_score": run.share_of_voice_score,
                        "product_coverage_score": run.product_coverage_score,
                        "category_coverage_score": run.category_coverage_score,
                        "knowledge_graph_score": run.knowledge_graph_score,
                        "authority_score": run.authority_score,
                        "sentiment_score": run.sentiment_score,
                    },
                    "raw_values": {
                        "share_of_voice_value": run.share_of_voice_value,
                        "product_coverage_value": run.product_coverage_value,
                        "category_coverage_value": run.category_coverage_value,
                        "knowledge_graph_value": run.knowledge_graph_value,
                        "authority_value": run.authority_value,
                    },
                }
            )

        # 7. Build Output Payload
        return {
            "brand": {
                "id": brand.id,
                "name": brand.name,
                "domain": brand.domain,
                "industry": brand.industry,
                "country": brand.country,
                "is_competitor": brand.competitor,
            },
            "total_analytic_runs": total_runs,
            "overall_averages": overall_averages,
            "model_breakdown": formatted_model_breakdown,
            "latest_insights": {
                "run_at": latest_run.created_at,
                "diagnosis": latest_diagnosis,
                "recommendations": latest_recommendations,
                "dimensions": latest_dimensions,
                "categories": latest_categories,
                "competitors": latest_competitors,
            },
            "run_history": run_history,
        }
