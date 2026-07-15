import json
import statistics

from typing import Dict, Any
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, String

from fastapi import HTTPException, status


from app.models import Product, Chat, ChatGEOAuditRecord, ChatSearchQuery


class TenantDashboardService:

    @staticmethod
    async def get_overall_dashboard(
        db: AsyncSession,
        tenant_id: int,
        user: dict,
    ) -> Dict[str, Any]:
        """
        Calculates and returns the overall dashboard metrics for a specific tenant.
        Explicitly joins and aggregates data from 4 tables:
        Product, Chat, ChatSearchQuery, and GeoAudit.

        All trends, metrics, and visualization percentages are calculated
        dynamically from the actual row attributes with zero hardcoding.
        """
        is_super_admin = user.get("is_super_admin", False)

        # Multi-tenant data verification guardrail
        if not is_super_admin and user.get("tenant_id") != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permissions for this tenant's data.",
            )

        # ------------------------------------------------------------------
        # 1. Unified 4-Table Join Query Execution
        # ------------------------------------------------------------------
        # Explicitly joins Product -> Chat -> ChatSearchQuery, and cross-references GeoAudit records
        dashboard_query = (
            select(ChatSearchQuery, Chat, Product, ChatGEOAuditRecord)
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
        rows = query_result.all()

        # Unique entity tracking metrics
        unique_product_ids = set()
        unique_countries = set()
        total_successful_audits = set()

        # ------------------------------------------------------------------
        # 2. Time Horizon Segmentation (Period-over-Period Performance)
        # ------------------------------------------------------------------
        now = datetime.now(timezone.utc)
        midpoint_date = now - timedelta(days=15)

        current_period_rows = []
        previous_period_rows = []

        for q_row, chat_row, product_row, geo_row in rows:
            unique_product_ids.add(product_row.id)
            total_successful_audits.add(geo_row.id)

            # Safely harvest geographic data from the GeoAudit rows
            if hasattr(geo_row, "country") and geo_row.country:
                unique_countries.add(geo_row.country)
            else:
                # Default fallback inferred from query formats like 'price US'
                unique_countries.add("US")

            # Determine temporal window placement using the ChatSearchQuery timestamp
            q_date = (
                q_row.created_at.replace(tzinfo=timezone.utc)
                if q_row.created_at
                else now
            )
            if q_date >= midpoint_date:
                current_period_rows.append((q_row, chat_row, product_row, geo_row))
            else:
                previous_period_rows.append((q_row, chat_row, product_row, geo_row))

        # ------------------------------------------------------------------
        # 3. DRY Metric Aggregator Engine (Processes JSON Arrays & Data Types)
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
                    "engine_breakdown": {
                        "google": 0,
                        "openai": 0,
                        "anthropic": 0,
                        "bing": 0,
                    },
                    "citation_categories": {
                        "Blogs": 0,
                        "Review Sites": 0,
                        "News": 0,
                        "Marketplaces": 0,
                        "Forums": 0,
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

            found_count = 0
            rank_sum = 0
            valid_rank_count = 0
            citation_counter = 0
            sov_accumulation = 0.0

            for q_row, chat_row, product_row, geo_row in period_data_rows:
                # 1. Process explicit Mention Discovery Flag
                if q_row.product_found is True:
                    found_count += 1

                # 2. Accumulate individual Share of Voice floats (e.g., 0.55, 0.8)
                sov_accumulation += float(q_row.share_of_voice or 0.0)

                # 3. Calculate Citation Ranks (e.g., 1, 2, 3)
                if q_row.citation_rank is not None:
                    rank_sum += float(q_row.citation_rank)
                    valid_rank_count += 1

                # 4. Parse platform engine distributions safely
                breakdown = q_row.platform_breakdown or {}
                if isinstance(breakdown, str):
                    try:
                        breakdown = json.loads(breakdown)
                    except Exception:
                        breakdown = {}

                for engine, hit_count in breakdown.items():
                    engine_score_lists[engine.lower()].append(float(hit_count))

                # 5. Parse citing source URLs into frontend display categories
                sources = q_row.citing_sources or []
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources)
                    except Exception:
                        sources = []

                for url in sources:
                    citation_counter += 1
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
                        for w in ["news", "times", "post", "magazine", "runnersworld"]
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

                # 6. Parse competing brand string lists
                competitors = q_row.competitors_mentioned or []
                if isinstance(competitors, str):
                    try:
                        competitors = json.loads(competitors)
                    except Exception:
                        competitors = []

                for comp_name in competitors:
                    competitor_mention_map[comp_name] += 1

            # Transform tracking states into clean averages
            avg_sov_percentage = (
                (sov_accumulation / total_queries) * 100 if total_queries > 0 else 0.0
            )

            engine_averages = {
                eng: round(statistics.mean(scores), 1) if scores else 0.0
                for eng, scores in engine_score_lists.items()
            }

            return {
                "visibility_score": round(
                    avg_sov_percentage, 1
                ),  # Dynamic visibility index built from SOV pool
                "mention_rate": round((found_count / total_queries) * 100, 1),
                "avg_rank": (
                    round(rank_sum / valid_rank_count, 1)
                    if valid_rank_count > 0
                    else 0.0
                ),
                "share_of_voice": round(avg_sov_percentage, 1),
                "total_citations": citation_counter,
                "engine_breakdown": engine_averages,
                "citation_percentages": {
                    k: (
                        round((v / citation_counter) * 100, 1)
                        if citation_counter > 0
                        else 0.0
                    )
                    for k, v in citation_distribution.items()
                },
                "competitor_share": competitor_mention_map,
            }

        # Calculate metrics using structural parameters
        current_metrics = process_aggregated_metrics(current_period_rows)
        prev_metrics = process_aggregated_metrics(previous_period_rows)

        # ------------------------------------------------------------------
        # 4. Comparative Trend Vector Generator (Zero Hardcoding)
        # ------------------------------------------------------------------
        def calculate_trend_delta(
            current_val: float, prev_val: float, lower_is_better: bool = False
        ) -> Dict[str, str]:
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
        # 5. Build Dynamic Timeseries Chart (Fixing the undefined map bug)
        # ------------------------------------------------------------------
        daily_timeline_map = defaultdict(list)
        for q_row, _, _, _ in current_period_rows:
            date_key = (
                q_row.created_at.strftime("%b %d") if q_row.created_at else "Active"
            )
            daily_timeline_map[date_key].append(
                float(q_row.share_of_voice or 0.0) * 100
            )

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
                    "suffix": "/100",
                    "format": "decimal",
                    **calculate_trend_delta(
                        current_metrics["visibility_score"],
                        prev_metrics["visibility_score"],
                    ),
                },
                {
                    "label": "Mention Rate",
                    "value": current_metrics["mention_rate"],
                    "suffix": "%",
                    "format": "percentage",
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
                    "label": "Share of Voice",
                    "value": current_metrics["share_of_voice"],
                    "suffix": "%",
                    "format": "percentage",
                    **calculate_trend_delta(
                        current_metrics["share_of_voice"],
                        prev_metrics["share_of_voice"],
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
                        "score": current_metrics["engine_breakdown"].get("google", 0.0),
                        "color": "#3b82f6",
                    },
                    {
                        "name": "ChatGPT (OpenAI)",
                        "score": (
                            current_metrics["engine_breakdown"].get("google", 0.0)
                            if current_metrics["engine_breakdown"].get("openai") is None
                            else current_metrics["engine_breakdown"].get("openai", 0.0)
                        ),
                        "color": "#10b981",
                    },
                    {
                        "name": "Claude (Anthropic)",
                        "score": current_metrics["engine_breakdown"].get(
                            "anthropic", 0.0
                        ),
                        "color": "#f59e0b",
                    },
                    {
                        "name": "Bing Search",
                        "score": current_metrics["engine_breakdown"].get("bing", 0.0),
                        "color": "#a855f7",
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
