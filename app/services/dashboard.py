import json
import statistics

from typing import Dict, Any
from datetime import datetime, timezone
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, String

from fastapi import HTTPException, status

from app.models import Product, Chat, ChatGEOAuditRecord, ChatSearchQuery


class DynamicRow:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TenantDashboardService:

    @staticmethod
    async def get_overall_dashboard(
        db: AsyncSession,
        tenant_id: int,
        user: dict,
    ) -> Dict[str, Any]:
        """
        Calculates and returns ALL TIME dashboard metrics for a specific tenant.
        """
        is_super_admin = user.get("is_super_admin", False)

        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # ------------------------------------------------------------------
        # 1. Optimized 4-Table Join Query Execution
        # ------------------------------------------------------------------
        dashboard_query = (
            select(
                ChatSearchQuery.id,
                ChatSearchQuery.created_at,
                ChatSearchQuery.product_found,
                ChatSearchQuery.share_of_voice,
                ChatSearchQuery.citation_rank,
                ChatSearchQuery.platform_breakdown,
                ChatSearchQuery.citing_sources,
                ChatSearchQuery.competitors_mentioned,
                Product.id.label("product_table_id"),
                ChatGEOAuditRecord.id.label("geo_table_id"),
                (
                    ChatGEOAuditRecord.country
                    if hasattr(ChatGEOAuditRecord, "country")
                    else ChatGEOAuditRecord.id.label("no_country")
                ),
            )
            .join(Chat, ChatSearchQuery.chat_id == Chat.id)
            .join(Product, Chat.product_id == Product.id)
            .join(
                ChatGEOAuditRecord,
                (ChatGEOAuditRecord.tenant_id == Product.tenant_id)
                & (ChatGEOAuditRecord.model_used == cast(Chat.model_choice, String)),
            )
            .where(Product.tenant_id == tenant_id, Product.is_deleted.is_(False))
        )

        query_result = await db.execute(dashboard_query)
        results = query_result.all()

        rows = []
        has_country_col = hasattr(ChatGEOAuditRecord, "country")

        for r in results:
            q_row = DynamicRow(
                id=r.id,
                created_at=r.created_at,
                product_found=r.product_found,
                share_of_voice=r.share_of_voice,
                citation_rank=r.citation_rank,
                platform_breakdown=r.platform_breakdown,
                citing_sources=r.citing_sources,
                competitors_mentioned=r.competitors_mentioned,
            )
            chat_row = DynamicRow()
            product_row = DynamicRow(id=r.product_table_id)

            geo_init = {"id": r.geo_table_id}
            if has_country_col:
                geo_init["country"] = getattr(r, "country", None)

            geo_row = DynamicRow(**geo_init)

            rows.append((q_row, chat_row, product_row, geo_row))

        unique_product_ids = set()
        unique_countries = set()
        total_successful_audits = set()

        # ------------------------------------------------------------------
        # 2. All Time Data Collection (No Date Filtering/Segmentation)
        # ------------------------------------------------------------------
        current_period_rows = []
        previous_period_rows = []  # Remains empty for All-Time mode

        for q_row, chat_row, product_row, geo_row in rows:
            unique_product_ids.add(product_row.id)
            total_successful_audits.add(geo_row.id)

            if hasattr(geo_row, "country") and geo_row.country:
                unique_countries.add(geo_row.country)
            else:
                unique_countries.add("US")

            # Push all rows directly into current period for All-Time calculation
            current_period_rows.append((q_row, chat_row, product_row, geo_row))

        # ------------------------------------------------------------------
        # 3. DRY Metric Aggregator Engine
        # ------------------------------------------------------------------
        def process_aggregated_metrics(period_data_rows) -> Dict[str, Any]:
            total_queries = len(period_data_rows)
            if total_queries == 0:
                return {
                    "visibility_score": 0.0,
                    "mention_rate": 0.0,
                    "avg_rank": 0.0,
                    "share_of_voice": 0.0,
                    "total_citations": 0,
                    "unique_competitors": 0,
                    "engine_breakdown": {
                        "google": 0.0,
                        "openai": 0.0,
                        "anthropic": 0.0,
                    },
                    "citation_categories": {
                        "Blogs": 0,
                        "Review Sites": 0,
                        "News": 0,
                        "Marketplaces": 0,
                        "Forums": 0,
                    },
                    "citation_percentages": {
                        "Blogs": 0.0,
                        "Review Sites": 0.0,
                        "News": 0.0,
                        "Marketplaces": 0.0,
                        "Forums": 0.0,
                    },
                    "competitor_share": defaultdict(int),
                }

            engine_score_lists = defaultdict(list)
            citation_distribution = {
                "Blogs": 0,
                "Review Sites": 0,
                "News": 0,
                "Marketplaces": 0,
                "Forums": 0,
            }
            competitor_mention_map = defaultdict(int)
            unique_sources_set = set()

            found_count = 0
            rank_sum = 0
            valid_rank_count = 0
            sov_accumulation = 0.0

            for q_row, chat_row, product_row, geo_row in period_data_rows:
                if q_row.product_found is True:
                    found_count += 1

                sov_accumulation += float(q_row.share_of_voice or 0.0)

                if q_row.citation_rank is not None:
                    rank_sum += float(q_row.citation_rank)
                    valid_rank_count += 1

                # Safe platform_breakdown parsing
                breakdown = q_row.platform_breakdown or {}
                if isinstance(breakdown, str):
                    try:
                        breakdown = json.loads(breakdown) or {}
                    except Exception:
                        breakdown = {}

                if isinstance(breakdown, dict):
                    for engine, hit_count in breakdown.items():
                        if engine and hit_count is not None:
                            engine_score_lists[engine.lower()].append(float(hit_count))

                # Safe citing_sources parsing (Tracking UNIQUE URLs)
                sources = q_row.citing_sources or []
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources) or []
                    except Exception:
                        sources = []

                if isinstance(sources, list):
                    for url in sources:
                        if not url or not isinstance(url, str):
                            continue

                        if url not in unique_sources_set:
                            unique_sources_set.add(url)
                            url_lower = url.lower()
                            if "blog" in url_lower or "wp-" in url_lower:
                                citation_distribution["Blogs"] += 1
                            elif any(
                                w in url_lower
                                for w in [
                                    "review",
                                    "guru",
                                    "advisor",
                                    "trustpilot",
                                    "runrepeat",
                                ]
                            ):
                                citation_distribution["Review Sites"] += 1
                            elif any(
                                w in url_lower
                                for w in [
                                    "news",
                                    "times",
                                    "post",
                                    "magazine",
                                    "runnersworld",
                                ]
                            ):
                                citation_distribution["News"] += 1
                            elif any(
                                w in url_lower
                                for w in [
                                    "amazon",
                                    "shop",
                                    "dickssportinggoods",
                                    "ebay",
                                    "marketplace",
                                    "fleetfeet",
                                ]
                            ):
                                citation_distribution["Marketplaces"] += 1
                            else:
                                citation_distribution["Forums"] += 1

                # Safe competitors_mentioned parsing
                competitors = q_row.competitors_mentioned or []
                if isinstance(competitors, str):
                    try:
                        competitors = json.loads(competitors) or []
                    except Exception:
                        competitors = []

                if isinstance(competitors, list):
                    for comp_name in competitors:
                        if comp_name:
                            competitor_mention_map[comp_name] += 1

            avg_sov_percentage = (
                (sov_accumulation / total_queries) if total_queries > 0 else 0.0
            )

            engine_averages = {
                eng: round(statistics.mean(scores), 1) if scores else 0.0
                for eng, scores in engine_score_lists.items()
            }

            total_unique_citations = len(unique_sources_set)

            return {
                "visibility_score": round(avg_sov_percentage, 1),
                "mention_rate": round((found_count / total_queries) * 10, 1),
                "avg_rank": (
                    round(rank_sum / valid_rank_count, 1)
                    if valid_rank_count > 0
                    else 0.0
                ),
                "share_of_voice": round(avg_sov_percentage, 1),
                "total_citations": total_unique_citations,
                "unique_competitors": len(competitor_mention_map),
                "engine_breakdown": engine_averages,
                "citation_percentages": {
                    k: (
                        round((v / total_unique_citations) * 100, 1)
                        if total_unique_citations > 0
                        else 0.0
                    )
                    for k, v in citation_distribution.items()
                },
                "competitor_share": competitor_mention_map,
            }

        current_metrics = process_aggregated_metrics(current_period_rows)
        prev_metrics = process_aggregated_metrics(previous_period_rows)

        # ------------------------------------------------------------------
        # 4. Comparative Trend Vector Generator
        # ------------------------------------------------------------------
        def calculate_trend_delta(
            current_val: float, prev_val: float, lower_is_better: bool = False
        ) -> Dict[str, str]:
            # For All-Time dashboard mode, default to neutral 0.0% trend
            if not prev_val or prev_val == 0.0:
                return {"trend": "0.0%", "trendType": "neutral"}

            raw_diff = ((current_val - prev_val) / prev_val) * 100
            is_improving = -raw_diff > 0 if lower_is_better else raw_diff > 0

            sign_prefix = "+" if raw_diff > 0 else ""
            return {
                "trend": f"{sign_prefix}{round(raw_diff, 1)}%",
                "trendType": (
                    "positive"
                    if is_improving
                    else ("negative" if raw_diff != 0 else "neutral")
                ),
            }

        # ------------------------------------------------------------------
        # 5. Build Dynamic Timeseries Chart (Entire Timeline)
        # ------------------------------------------------------------------
        daily_timeline_map = defaultdict(list)
        for q_row, _, _, _ in current_period_rows:
            date_key = (
                q_row.created_at.strftime("%b %d") if q_row.created_at else "Active"
            )
            daily_timeline_map[date_key].append(float(q_row.share_of_voice or 0.0))

        visibility_trend_chart = (
            [
                {"date": day_label, "score": round(statistics.mean(values), 1)}
                for day_label, values in sorted(daily_timeline_map.items())
            ]
            if daily_timeline_map
            else [{"date": "Active", "score": current_metrics["visibility_score"]}]
        )

        # ------------------------------------------------------------------
        # 6. Normalize Competitor Share of Voice Data Output
        # ------------------------------------------------------------------
        formatted_sov_chart = [
            {
                "brand": "Your Brand",
                "score": current_metrics["share_of_voice"],
                "isPrimary": True,
                "color": "#3b82f6",
            }
        ]

        total_comp_pool = sum(current_metrics["competitor_share"].values())
        sorted_comps = sorted(
            current_metrics["competitor_share"].items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for name, frequency in sorted_comps[:3]:
            comp_percentage = (
                (frequency / total_comp_pool) * 100 if total_comp_pool > 0 else 0.0
            )
            formatted_sov_chart.append(
                {
                    "brand": name,
                    "score": round(comp_percentage, 1),
                    "isPrimary": False,
                    "color": "#94a3b8",
                }
            )

        # ------------------------------------------------------------------
        # 7. Construct Unified Output Payload Schema
        # ------------------------------------------------------------------
        return {
            "metaContext": {
                "countriesCount": len(unique_countries) if unique_countries else 1,
                "productsCount": len(unique_product_ids),
                "queriesTrackedCount": len(current_period_rows),
                "competitorsCount": max(0, len(current_metrics["competitor_share"])),
            },
            "kpiCards": [
                {
                    "label": "Visibility Score",
                    "value": current_metrics["visibility_score"],
                    "suffix": "/10",
                    "format": "decimal",
                    **calculate_trend_delta(
                        current_metrics["visibility_score"],
                        prev_metrics["visibility_score"],
                    ),
                },
                {
                    "label": "Mention Rate",
                    "value": current_metrics["mention_rate"],
                    "suffix": "",
                    "format": "decimal",
                    **calculate_trend_delta(
                        current_metrics["mention_rate"], prev_metrics["mention_rate"]
                    ),
                },
                {
                    "label": "Avg. Rank",
                    "value": current_metrics["avg_rank"],
                    "suffix": "",
                    "format": "decimal",
                    **calculate_trend_delta(
                        current_metrics["avg_rank"],
                        prev_metrics["avg_rank"],
                        lower_is_better=True,
                    ),
                },
                {
                    "label": "Competitors Mentioned",
                    "value": current_metrics["unique_competitors"],
                    "suffix": "",
                    "format": "number",
                    **calculate_trend_delta(
                        current_metrics["unique_competitors"],
                        prev_metrics["unique_competitors"],
                    ),
                },
                {
                    "label": "Citations Added",
                    "value": current_metrics["total_citations"],
                    "suffix": "",
                    "format": "number",
                    **calculate_trend_delta(
                        current_metrics["total_citations"],
                        prev_metrics["total_citations"],
                    ),
                },
                {
                    "label": "Tracked Products",
                    "value": len(unique_product_ids),
                    "suffix": "",
                    "format": "number",
                    "trend": "0.0%",
                    "trendType": "neutral",
                },
                {
                    "label": "Total Queries",
                    "value": len(current_period_rows),
                    "suffix": "",
                    "format": "number",
                    **calculate_trend_delta(
                        len(current_period_rows), len(previous_period_rows)
                    ),
                },
            ],
            "visualizations": {
                "visibilityTrendTimeline": visibility_trend_chart,
                "visibilityByAIEngine": [
                    {
                        "name": "Gemini (Google)",
                        "score": current_metrics["engine_breakdown"].get("google")
                        or 0.0,
                        "color": "#3b82f6",
                    },
                    {
                        "name": "ChatGPT (OpenAI)",
                        "score": current_metrics["engine_breakdown"].get("openai")
                        or 0.0,
                        "color": "#10b981",
                    },
                    {
                        "name": "Claude (Anthropic)",
                        "score": current_metrics["engine_breakdown"].get("anthropic")
                        or 0.0,
                        "color": "#f59e0b",
                    },
                ],
                "citationSourcesPie": [
                    {"source": k, "percentage": v}
                    for k, v in current_metrics["citation_percentages"].items()
                    if v > 0
                ],
                "competitorShareOfVoiceBar": formatted_sov_chart,
            },
        }
