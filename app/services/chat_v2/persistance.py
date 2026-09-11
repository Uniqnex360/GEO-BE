"""
Builders for the DB rows written per audit run.

IMPORTANT / MIGRATION NEEDED:
`ChatGEOAuditRecord` needs three new nullable integer columns for this to
persist token usage: `input_tokens`, `output_tokens`, `total_tokens`
(a `call_count` int column is optional but useful for debugging cost/model
call volume). Example Alembic op:

    op.add_column('chat_geo_audit_records', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_geo_audit_records', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_geo_audit_records', sa.Column('total_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_geo_audit_records', sa.Column('llm_call_count', sa.Integer(), nullable=True))

`ChatSearchQuery` also needs a `competitor_products` JSON column (this was
already noted as missing in the original code, still true here):

    op.add_column('chat_search_queries', sa.Column('competitor_products', sa.JSON(), nullable=True))
"""

import json
from typing import Optional

from app.models import Chat, ChatGEOAuditRecord, ChatSearchQuery
from app.models.base import LLMModels

from .schemas import ChatQueryBase, GEOAuditRequest, UnifiedGEOResponse
from .token_usage import TokenUsageAccumulator


def build_chat_record(
    tenant_id: int,
    product_id: int,
    payload: GEOAuditRequest,
    model_enum: LLMModels,
    structured: UnifiedGEOResponse,
    token_usage: Optional[TokenUsageAccumulator] = None,
) -> Chat:
    usage_fields = token_usage.as_dict() if token_usage else {}

    return Chat(
        tenant_id=tenant_id,
        product_id=product_id,
        product_name=payload.product_name or "",
        product_url=payload.product_url or payload.website or "",
        extra_context=payload.extra_context,
        model_choice=model_enum,
        citations=[c.model_dump(mode="json") for c in structured.citations],
        competitor_analytics=[
            c.model_dump(mode="json") for c in structured.competitor_analytics
        ],
        final_optimization_report=structured.final_optimized_tips_summary,
        input_tokens=usage_fields.get("input_tokens", 0),
        output_tokens=usage_fields.get("output_tokens", 0),
        total_tokens=usage_fields.get("total_tokens", 0),
        # llm_call_count=usage_fields.get("call_count", 0),
    )


def build_search_query_records(
    chat_id: int, queries: list[ChatQueryBase]
) -> list[ChatSearchQuery]:
    return [
        ChatSearchQuery(
            chat_id=chat_id,
            chat_context=query.chat_context,
            brand_name=query.brand,
            query_text=query.query,
            product_found=query.product_found,
            share_of_voice=min(query.share_of_voice, 100.0),
            total_websites_found=query.total_websites_found,
            citation_rank=query.citation_rank,
            platform_breakdown=query.platform_breakdown.model_dump(mode="json"),
            best_metrics_variance={},
            raw_api_response=json.dumps(query.model_dump(mode="json")),
            citing_sources=query.citing_sources,
            competitors_mentioned=query.competitors_mentioned,
            competitor_products=[
                p.model_dump(mode="json") for p in query.competitor_products
            ],
            query_optimization_tag=query.optimization_tag,
            query_optimization_tips=query.optimization_tips_for_better_result,
            solution=query.copy_pasteable_solution,
        )
        for query in queries
    ]


def build_audit_record(
    tenant_id: int,
    identifier: str,
    model_name: str,
    structured: Optional[UnifiedGEOResponse],
) -> ChatGEOAuditRecord:
    return ChatGEOAuditRecord(
        tenant_id=tenant_id,
        product_identifier=identifier,
        model_used=model_name,
        status="SUCCESS",
        audit_data=structured.model_dump(mode="json") if structured else {},
    )
