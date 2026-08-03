from typing import Dict, Any, Optional
from sqlalchemy import (
    select,
    func,
    case,
    and_,
    distinct,
    Numeric,
    cast,
    Integer,
    String,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, ChatSearchQuery
from app.models.product import Product
from app.models.brand import Brand


class CompetitorService:

    @staticmethod
    async def get_dashboard(
        db: AsyncSession,
        user: dict,
        tenant_id: int,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:

        is_super_admin = user.get("is_super_admin", False)

        filters = []

        # ----------------------------------------------------------
        # Fix: Ensure tenant_id is explicitly an integer parameter
        # or safely casted to match DB schema types.
        # ----------------------------------------------------------
        if tenant_id is not None:
            try:
                clean_tenant_id = int(tenant_id)
            except (ValueError, TypeError):
                clean_tenant_id = tenant_id

            if not is_super_admin or tenant_id:
                # If product.tenant_id in DB is INTEGER:
                filters.append(Product.tenant_id == clean_tenant_id)

                if hasattr(Chat, "tenant_id"):
                    filters.append(Chat.tenant_id == clean_tenant_id)

        # Soft delete checks
        if hasattr(Chat, "is_deleted"):
            filters.append(Chat.is_deleted == False)
        if hasattr(Product, "is_deleted"):
            filters.append(Product.is_deleted == False)

        # Optional search query filter
        if search:
            filters.append(Chat.product_name.ilike(f"%{search}%"))

        # ----------------------------------------------------------
        # 1. Summary metrics
        # ----------------------------------------------------------
        summary_query = (
            select(
                func.avg(ChatSearchQuery.share_of_voice).label("overall_sov"),
                func.sum(
                    case(
                        (ChatSearchQuery.citation_rank <= 3, 1),
                        else_=0,
                    )
                ).label("wins"),
                func.sum(
                    case(
                        (ChatSearchQuery.citation_rank > 3, 1),
                        else_=0,
                    )
                ).label("losses"),
                func.sum(
                    case(
                        (ChatSearchQuery.share_of_voice < 20, 1),
                        else_=0,
                    )
                ).label("gap_queries"),
            )
            .select_from(ChatSearchQuery)
            .join(Chat, Chat.id == ChatSearchQuery.chat_id)
            .join(Product, Product.id == Chat.product_id)
            .where(and_(*filters))
        )

        summary_result = await db.execute(summary_query)
        summary = summary_result.mappings().first() or {}

        # ----------------------------------------------------------
        # 2. Brand SOV Bar Chart
        # ----------------------------------------------------------
        brand_bar_query = (
            select(
                Brand.name.label("brand"),
                func.round(
                    cast(func.avg(ChatSearchQuery.share_of_voice), Numeric), 2
                ).label("sov"),
            )
            .select_from(ChatSearchQuery)
            .join(Chat, Chat.id == ChatSearchQuery.chat_id)
            .join(Product, Product.id == Chat.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(and_(*filters))
            .group_by(Brand.name)
            .order_by(func.avg(ChatSearchQuery.share_of_voice).desc())
        )

        brand_bar_result = await db.execute(brand_bar_query)
        brand_bar_chart = [
            {
                "brand": r.brand,
                "share_of_voice": float(r.sov or 0),
            }
            for r in brand_bar_result.all()
        ]

        # ----------------------------------------------------------
        # 3. Visibility Trend
        # ----------------------------------------------------------
        month_expr = func.date_trunc("month", Chat.created_at)

        trend_query = (
            select(
                Brand.name.label("brand"),
                func.to_char(month_expr, "Mon").label("month"),
                func.round(
                    cast(func.avg(ChatSearchQuery.share_of_voice), Numeric), 2
                ).label("visibility"),
            )
            .select_from(ChatSearchQuery)
            .join(Chat, Chat.id == ChatSearchQuery.chat_id)
            .join(Product, Product.id == Chat.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(and_(*filters))
            .group_by(Brand.name, month_expr)
            .order_by(Brand.name, month_expr)
        )

        trend_result = await db.execute(trend_query)
        visibility_trend = {}

        for row in trend_result.all():
            visibility_trend.setdefault(row.brand, [])
            visibility_trend[row.brand].append(
                {
                    "month": row.month,
                    "visibility": float(row.visibility or 0),
                }
            )

        # ----------------------------------------------------------
        # 4. Competitor Leaderboard
        # ----------------------------------------------------------
        leaderboard_query = (
            select(
                Brand.name.label("brand"),
                func.round(
                    cast(func.avg(ChatSearchQuery.share_of_voice), Numeric), 2
                ).label("sov"),
                func.round(
                    cast(func.avg(ChatSearchQuery.citation_rank), Numeric), 2
                ).label("avg_position"),
                func.sum(
                    case(
                        (ChatSearchQuery.citation_rank <= 3, 1),
                        else_=0,
                    )
                ).label("wins"),
                func.sum(
                    case(
                        (ChatSearchQuery.citation_rank > 3, 1),
                        else_=0,
                    )
                ).label("losses"),
                func.count(distinct(Chat.product_name)).label("products"),
                func.sum(ChatSearchQuery.total_websites_found).label("citations"),
            )
            .select_from(ChatSearchQuery)
            .join(Chat, Chat.id == ChatSearchQuery.chat_id)
            .join(Product, Product.id == Chat.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(and_(*filters))
            .group_by(Brand.name)
            .order_by(func.avg(ChatSearchQuery.share_of_voice).desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )

        leaderboard_result = await db.execute(leaderboard_query)
        leaderboard = [
            {
                "brand_name": row.brand,
                "sov_visibility": float(row.sov or 0),
                "avg_position": float(row.avg_position or 0),
                "wins": row.wins or 0,
                "losses": row.losses or 0,
                "products": row.products or 0,
                "citations": row.citations or 0,
            }
            for row in leaderboard_result.all()
        ]

        # ----------------------------------------------------------
        # 5. Final Output Schema
        # ----------------------------------------------------------
        return {
            "summary": {
                "share_of_voice": float(
                    round(
                        summary.get("overall_sov") or 0,
                        2,
                    )
                ),
                "query_wins": summary.get("wins") or 0,
                "query_losses": summary.get("losses") or 0,
                "gap_queries": summary.get("gap_queries") or 0,
            },
            "brand_sov_bar_chart": brand_bar_chart,
            "visibility_trend": visibility_trend,
            "competitor_leaderboard": leaderboard,
        }
