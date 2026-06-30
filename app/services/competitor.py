from typing import Dict, Any, Optional
from sqlalchemy import (
    select,
    func,
    case,
    and_,
    distinct,
    Numeric,
    cast,
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

        if not is_super_admin:
            filters.append(Chat.tenant_id == tenant_id)

            if hasattr(Chat, "is_deleted"):
                filters.append(Chat.is_deleted == False)

        if search:
            filters.append(Chat.product_name.ilike(f"%{search}%"))

        ##########################################################
        # Shared base query
        ##########################################################

        base_query = (
            select(
                Chat.id,
                Chat.product_name,
                Brand.name.label("brand_name"),
                ChatSearchQuery.share_of_voice,
                ChatSearchQuery.citation_rank,
                ChatSearchQuery.total_websites_found,
                Chat.created_at,
            )
            .join(
                ChatSearchQuery,
                Chat.id == ChatSearchQuery.chat_id,
            )
            .join(
                Product,
                Product.id == Chat.product_id,
            )
            .join(
                Brand,
                Brand.id == Product.brand_id,
            )
            .where(and_(*filters))
        )

        ##########################################################
        # Summary metrics
        ##########################################################

        summary_query = (
            select(
                func.avg(ChatSearchQuery.share_of_voice).label("overall_sov"),
                func.sum(
                    case(
                        (
                            ChatSearchQuery.citation_rank <= 3,
                            1,
                        ),
                        else_=0,
                    )
                ).label("wins"),
                func.sum(
                    case(
                        (
                            ChatSearchQuery.citation_rank > 3,
                            1,
                        ),
                        else_=0,
                    )
                ).label("losses"),
                func.sum(
                    case(
                        (
                            ChatSearchQuery.share_of_voice < 20,
                            1,
                        ),
                        else_=0,
                    )
                ).label("gap_queries"),
            )
            .select_from(ChatSearchQuery)
            .join(
                Chat,
                Chat.id == ChatSearchQuery.chat_id,
            )
            .where(and_(*filters))
        )

        summary_result = await db.execute(summary_query)

        summary = summary_result.mappings().first()

        ##########################################################
        # Brand SOV Bar Chart
        ##########################################################

        brand_bar_query = (
            select(
                Brand.name.label("brand"),
                func.round(
                    cast(func.avg(ChatSearchQuery.share_of_voice), Numeric), 2
                ).label("sov"),
            )
            .select_from(ChatSearchQuery)
            .join(
                Chat,
                Chat.id == ChatSearchQuery.chat_id,
            )
            .join(
                Product,
                Product.id == Chat.product_id,
            )
            .join(
                Brand,
                Brand.id == Product.brand_id,
            )
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
            for r in brand_bar_result
        ]

        ##########################################################
        # Visibility Trend
        ##########################################################

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
            .join(
                Chat,
                Chat.id == ChatSearchQuery.chat_id,
            )
            .join(
                Product,
                Product.id == Chat.product_id,
            )
            .join(
                Brand,
                Brand.id == Product.brand_id,
            )
            .where(and_(*filters))
            .group_by(Brand.name, month_expr)
            .order_by(Brand.name, month_expr)
        )

        trend_result = await db.execute(trend_query)

        visibility_trend = {}

        for row in trend_result:

            visibility_trend.setdefault(row.brand, [])

            visibility_trend[row.brand].append(
                {
                    "month": row.month,
                    "visibility": float(row.visibility or 0),
                }
            )

        ##########################################################
        # Competitor Leaderboard
        ##########################################################

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
                        (
                            ChatSearchQuery.citation_rank <= 3,
                            1,
                        ),
                        else_=0,
                    )
                ).label("wins"),
                func.sum(
                    case(
                        (
                            ChatSearchQuery.citation_rank > 3,
                            1,
                        ),
                        else_=0,
                    )
                ).label("losses"),
                func.count(distinct(Chat.product_name)).label("products"),
                func.sum(ChatSearchQuery.total_websites_found).label("citations"),
            )
            .select_from(ChatSearchQuery)
            .join(
                Chat,
                Chat.id == ChatSearchQuery.chat_id,
            )
            .join(
                Product,
                Product.id == Chat.product_id,
            )
            .join(
                Brand,
                Brand.id == Product.brand_id,
            )
            .where(and_(*filters))
            .group_by(Brand.name)
            .order_by(func.avg(ChatSearchQuery.share_of_voice).desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )

        leaderboard_result = await db.execute(leaderboard_query)

        leaderboard = []

        for row in leaderboard_result:

            leaderboard.append(
                {
                    "brand_name": row.brand,
                    "sov_visibility": float(row.sov or 0),
                    "avg_position": float(row.avg_position or 0),
                    "wins": row.wins or 0,
                    "losses": row.losses or 0,
                    "products": row.products or 0,
                    "citations": row.citations or 0,
                }
            )

        ##########################################################
        # Final API response
        ##########################################################

        return {
            "summary": {
                "share_of_voice": float(
                    round(
                        summary.overall_sov or 0,
                        2,
                    )
                ),
                "query_wins": summary.wins or 0,
                "query_losses": summary.losses or 0,
                "gap_queries": summary.gap_queries or 0,
            },
            "brand_sov_bar_chart": brand_bar_chart,
            "visibility_trend": visibility_trend,
            "competitor_leaderboard": leaderboard,
        }
