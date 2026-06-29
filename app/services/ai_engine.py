from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chat, ChatSearchQuery


class AIEngineService:

    @staticmethod
    async def get_detail(
        db: AsyncSession,
        tenant_id: int,
        user: dict,
    ):
        is_super_admin: bool = user.get("is_super_admin", False)

        # ------------------------------------
        # Base filter
        # ------------------------------------

        base_query = select(Chat)

        if not is_super_admin:
            base_query = base_query.where(Chat.tenant_id == tenant_id)

        # ------------------------------------
        # Engine aggregation
        # ------------------------------------

        engine_query = select(
            Chat.model_used, func.count(Chat.id).label("queries")
        ).group_by(Chat.model_used)

        if not is_super_admin:
            engine_query = engine_query.where(Chat.tenant_id == tenant_id)

        engine_result = await db.execute(engine_query)

        engine_rows = engine_result.all()

        engines_data = []

        for row in engine_rows:
            engines_data.append(
                {"name": row.model_used or "Unknown", "queries": row.queries or 0}
            )

        # ------------------------------------
        # Get latest chats with search queries
        # ------------------------------------

        latest_query = (
            base_query.options(selectinload(Chat.search_queries))
            .order_by(Chat.created_at.desc())
            .limit(5)
        )

        result = await db.execute(latest_query)

        chats = result.scalars().all()

        latest_prompts = []

        for chat in chats:

            latest_prompts.append(
                {
                    "chat_id": chat.id,
                    "product_name": chat.product_name or "",
                    "product_url": chat.product_url or "",
                    "extra_context": chat.extra_context or "",
                    "engine": chat.model_used or "Unknown",
                    "created_at": (
                        chat.created_at.isoformat() if chat.created_at else None
                    ),
                    "prompt_queries": [
                        {
                            "id": q.id,
                            "query_text": q.query_text or "",
                            "product_found": (
                                q.product_found
                                if q.product_found is not None
                                else False
                            ),
                            "share_of_voice": q.share_of_voice or 0,
                            "total_websites_found": q.total_websites_found or 0,
                            "citation_rank": q.citation_rank or 0,
                            "platform_breakdown": q.platform_breakdown or {},
                            "best_metrics_variance": q.best_metrics_variance or {},
                            "citing_sources": q.citing_sources or [],
                            "competitors_mentioned": q.competitors_mentioned or [],
                            "query_optimization_tips": q.query_optimization_tips or "",
                            "raw_api_response": q.raw_api_response or "",
                            "created_at": (
                                q.created_at.isoformat() if q.created_at else None
                            ),
                        }
                        for q in (chat.search_queries or [])
                    ],
                }
            )

        # ------------------------------------
        # Latest prompt detail
        # ------------------------------------

        latest_chat = latest_prompts[0] if latest_prompts else {}

        return {
            "enginesData": engines_data,
            "latest_5_prompts": latest_prompts,
            "latest_prompt_detail": latest_chat,
        }
