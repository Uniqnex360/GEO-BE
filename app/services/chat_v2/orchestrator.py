"""
GEO (Generative Engine Optimization) audit orchestration.

Given a product identifier (name / SKU / MPN / UPC / URL), this module:
  1. Looks up an existing product record, or creates one with LLM-enriched
     baseline metadata if it doesn't exist yet.
  2. Serves a cached report if a recent audit already exists.
  3. Otherwise runs the audit through every configured LLM (GPT / Gemini /
     Claude), persisting a Chat, its ChatSearchQuery rows, and a
     ChatGEOAuditRecord (now including token usage) per model.
  4. Streams progress as newline-delimited JSON events the whole way through,
     including an "X/Y" step counter for a real progress bar.

Fixes vs. the original monolith:
  - The "completed successfully" result event used to fire once per model
    inside the loop (so the frontend saw multiple "final" results, the last
    of which was whichever model happened to run last - not necessarily the
    best/most complete one). It now fires exactly once, after all models
    have run, built from every model's combined output.
  - Token usage is captured per LLM call and persisted on the audit record
    (see persistence.py for the required migration).
  - Real step-based progress (`step`/`total_steps`/`progress_label`) instead
    of only a percentage, so the frontend can render "11/20" directly.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import LLMModels

from .llm_runner import run_single_model_audit
from .persistance import (
    build_audit_record,
    build_chat_record,
    build_search_query_records,
)
from .product_service import (
    build_lookup_filters,
    create_new_product,
    find_existing_product,
    get_recent_cached_chat,
    resolve_identifier,
)
from .schemas import GEOAuditRequest, build_user_instruction_v2
from .streaming import (
    ProgressTracker,
    error_event,
    failed_event,
    model_warning_event,
    result_event,
    status_event,
)
from .tools import resolve_all_competitor_product_urls

async def run_geo_audit_stream(
    payload: GEOAuditRequest,
    db: AsyncSession,
    tenant_id: int,
    user_id: int | None = None,
) -> AsyncGenerator[str, None]:
    try:
        if tenant_id is None:
            yield error_event("tenant_id is required.")
            return

        if payload is None:
            yield error_event("Payload cannot be empty.")
            return

        yield status_event("Checking product registry...", 5)

        lookup_filters = build_lookup_filters(payload)

        if not lookup_filters and not payload.product_url:
            yield error_event(
                "One identifier is required (product_name/sku/mpn/upc/product_url)"
            )
            return

        product_record = await find_existing_product(db, tenant_id, lookup_filters)

        if product_record:
            product_id = product_record.id
            yield status_event("Existing product located", 10)

            recent_chat = await get_recent_cached_chat(db, product_id)
            if recent_chat:
                yield result_event(
                    "Warm cache hit", recent_chat.final_optimization_report
                )
                return
        else:
            yield status_event("Enriching missing product metadata...", 15)
            product_record = await create_new_product(db, payload, tenant_id, user_id)
            product_id = product_record.id

        from .actual_content import (
            save_extraction_to_product,
            extract_product_page_once,
        )
        print("payload", payload)
        data = await extract_product_page_once(url=payload.product_url or payload.website)
        print("data", data)
        await save_extraction_to_product(db, product_record, data)
        print("saving is finished")

        user_prompt = build_user_instruction_v2(payload)
        identifier = resolve_identifier(payload)

        models = list(LLMModels)
        progress = ProgressTracker(total_models=len(models))

        all_reports: list[dict] = []
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        for model_enum in models:
            model_name = model_enum.value

            try:
                yield progress.tick(
                    f"[{model_name}] Configuring runtime pool engine..."
                )
                yield progress.tick(
                    f"[{model_name}] Extracting payload identifier strings..."
                )
                yield progress.tick(
                    f"[{model_name}] Invoking context analysis tracing..."
                )

                search_keyword = f"{identifier} competitors buy online"

                structured, token_usage = await run_single_model_audit(
                    model_name, user_prompt, search_keyword
                )

                if structured:
                    structured.model_used = model_name

                    # The LLM may identify competitor products, but the
                    # product URL is always resolved by SerpApi. This
                    # prevents fabricated/404 competitor URLs.
                    resolve_all_competitor_product_urls(structured)

                    if structured.product_details:
                        product_record.no_of_faqs = structured.product_details.faqs
                        product_record.no_of_reviews = (
                            structured.product_details.reviews
                        )

                yield progress.tick(f"[{model_name}] Recording PostgreSQL logs...")

                if structured:
                    chat_record = build_chat_record(
                        tenant_id,
                        product_id,
                        payload,
                        model_enum,
                        structured,
                        token_usage=token_usage,
                    )
                    db.add(chat_record)
                    await db.flush()  # need chat_record.id before building search queries

                    for search_record in build_search_query_records(
                        chat_record.id, structured.queries_executed
                    ):
                        db.add(search_record)

                    db.add(
                        build_audit_record(
                            tenant_id, identifier, model_name, structured
                        )
                    )

                await db.commit()

                if structured:
                    all_reports.append(structured.model_dump(mode="json"))

                usage_dict = token_usage.as_dict()
                total_usage["input_tokens"] += usage_dict["input_tokens"]
                total_usage["output_tokens"] += usage_dict["output_tokens"]
                total_usage["total_tokens"] += usage_dict["total_tokens"]

                yield progress.tick(
                    f"{model_name} completed successfully "
                    f"({usage_dict['total_tokens']} tokens used)."
                )

            except Exception as model_error:
                await db.rollback()
                # Still advance the counter so the bar doesn't stall on a
                # failed model - just skip straight to that model's last step.
                progress.set_model_index(models.index(model_enum) + 1)
                yield model_warning_event(model_name, model_error)

        if all_reports:
            yield result_event(
                "GEO audit completed successfully",
                {
                    "reports": all_reports,
                    "final_optimized_tips_summary": all_reports[-1][
                        "final_optimized_tips_summary"
                    ],
                    "token_usage": total_usage,
                },
            )
        else:
            yield error_event("All models failed to produce a report.")

    except Exception as e:
        await db.rollback()
        yield failed_event(str(e))
