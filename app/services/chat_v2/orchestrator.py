# """
# GEO audit orchestration.
# """

# from typing import AsyncGenerator

# from sqlalchemy.ext.asyncio import AsyncSession

# from app.core.database import (
#     SessionLocal,
# )  # <-- CHANGE THIS IMPORT TO YOUR ACTUAL SESSION FACTORY
# from app.models.base import LLMModels

# from .llm_runner import run_single_model_audit
# from .recommandation import generate_product_recommendations
# from .persistance import (
#     build_audit_record,
#     build_chat_record,
#     build_search_query_records,
# )
# from .product_service import (
#     build_lookup_filters,
#     create_new_product,
#     find_existing_product,
#     get_recent_cached_chat,
#     resolve_identifier,
# )
# from .schemas import GEOAuditRequest, build_user_instruction_v2
# from .streaming import (
#     ProgressTracker,
#     error_event,
#     failed_event,
#     model_warning_event,
#     result_event,
#     status_event,
# )
# from .tools import resolve_all_competitor_product_urls


# async def run_geo_audit_stream(
#     payload: GEOAuditRequest,
#     db: AsyncSession,
#     tenant_id: int,
#     user_id: int | None = None,
# ) -> AsyncGenerator[str, None]:

#     try:
#         if tenant_id is None:
#             yield error_event("tenant_id is required.")
#             return

#         if payload is None:
#             yield error_event("Payload cannot be empty.")
#             return

#         yield status_event("Checking product registry...", 5)

#         lookup_filters = build_lookup_filters(payload)

#         if not lookup_filters and not payload.product_url:
#             yield error_event(
#                 "One identifier is required " "(product_name/sku/mpn/upc/product_url)"
#             )
#             return

#         # ---------------------------------------------------------
#         # 1. SHORT DB SESSION: PRODUCT LOOKUP
#         # ---------------------------------------------------------

#         async with SessionLocal() as lookup_db:

#             product_record = await find_existing_product(
#                 lookup_db,
#                 tenant_id,
#                 lookup_filters,
#             )

#             if product_record:
#                 product_id = product_record.id

#                 yield status_event(
#                     "Existing product located",
#                     10,
#                 )

#                 recent_chat = await get_recent_cached_chat(
#                     lookup_db,
#                     product_id,
#                 )

#                 if recent_chat:
#                     yield result_event(
#                         "Warm cache hit",
#                         recent_chat.final_optimization_report,
#                     )
#                     return

#                 # IMPORTANT:
#                 # Don't keep this ORM object around for later writes.
#                 #
#                 # We only need the ID and basic data.
#                 product_id = product_record.id

#             else:
#                 product_record = None
#                 product_id = None

#         # ---------------------------------------------------------
#         # 2. CREATE PRODUCT IF IT DOESN'T EXIST
#         # ---------------------------------------------------------

#         if product_record is None:

#             yield status_event(
#                 "Enriching missing product metadata...",
#                 15,
#             )

#             async with SessionLocal() as create_db:

#                 product_record = await create_new_product(
#                     create_db,
#                     payload,
#                     tenant_id,
#                     user_id,
#                 )

#                 await create_db.commit()

#                 product_id = product_record.id

#         # ---------------------------------------------------------
#         # 3. PREPARE LLM INPUT
#         # ---------------------------------------------------------

#         user_prompt = build_user_instruction_v2(payload)
#         identifier = resolve_identifier(payload)

#         yield status_event(
#             "Generating GEO recommendations...",
#             20,
#         )

#         search_keyword = f"{identifier} competitors buy online"

#         # ---------------------------------------------------------
#         # 4. IMPORTANT:
#         # NO DB SESSION IS USED DURING THIS LONG LLM OPERATION
#         # ---------------------------------------------------------

#         recommendations = await generate_product_recommendations(
#             db=None,
#             product=product_record,
#             search_keyword=search_keyword,
#             user_prompt=user_prompt,
#         )

#         recommendation_json = recommendations.model_dump(mode="json")

#         # ---------------------------------------------------------
#         # 5. FRESH DB SESSION FOR RECOMMENDATION UPDATE
#         # ---------------------------------------------------------

#         async with SessionLocal() as recommendation_db:

#             # Fetch a fresh ORM object.
#             product_record = await recommendation_db.get(
#                 type(product_record),
#                 product_id,
#             )

#             if product_record is None:
#                 raise RuntimeError(
#                     f"Product {product_id} disappeared before recommendation save."
#                 )

#             product_record.recommandation_v2 = recommendation_json

#             await recommendation_db.commit()

#             # Refresh only if you actually need DB-generated values.
#             await recommendation_db.refresh(product_record)

#         yield status_event(
#             "GEO recommendations saved.",
#             25,
#         )

#         # ---------------------------------------------------------
#         # EXISTING AUDIT LOGIC
#         # ---------------------------------------------------------

#         models = list(LLMModels)

#         progress = ProgressTracker(total_models=len(models))

#         all_reports: list[dict] = []

#         total_usage = {
#             "input_tokens": 0,
#             "output_tokens": 0,
#             "total_tokens": 0,
#         }

#         for model_index, model_enum in enumerate(models):

#             model_name = model_enum.value

#             try:

#                 yield progress.tick(
#                     f"[{model_name}] Configuring runtime pool engine..."
#                 )

#                 yield progress.tick(
#                     f"[{model_name}] Extracting payload identifier strings..."
#                 )

#                 yield progress.tick(
#                     f"[{model_name}] Invoking context analysis tracing..."
#                 )

#                 search_keyword = f"{identifier} competitors buy online"

#                 # -------------------------------------------------
#                 # LLM WORK
#                 # NO DB SESSION
#                 # -------------------------------------------------

#                 structured, token_usage = await run_single_model_audit(
#                     model_name,
#                     user_prompt,
#                     search_keyword,
#                 )

#                 if structured:

#                     structured.model_used = model_name

#                     resolve_all_competitor_product_urls(structured)

#                 yield progress.tick(f"[{model_name}] Recording PostgreSQL logs...")

#                 # -------------------------------------------------
#                 # FRESH DB SESSION FOR THIS MODEL
#                 # -------------------------------------------------

#                 async with SessionLocal() as model_db:

#                     # Re-fetch product because the old ORM object
#                     # may belong to an old/closed session.
#                     current_product = await model_db.get(
#                         type(product_record),
#                         product_id,
#                     )

#                     if current_product is None:
#                         raise RuntimeError(f"Product {product_id} not found.")

#                     if structured:

#                         # Update product statistics.
#                         if structured.product_details:

#                             current_product.no_of_faqs = structured.product_details.faqs

#                             current_product.no_of_reviews = (
#                                 structured.product_details.reviews
#                             )

#                         # Build Chat record.
#                         chat_record = build_chat_record(
#                             tenant_id,
#                             product_id,
#                             payload,
#                             model_enum,
#                             structured,
#                             token_usage=token_usage,
#                         )

#                         model_db.add(chat_record)

#                         await model_db.flush()

#                         # Search query records.
#                         search_records = build_search_query_records(
#                             chat_record.id,
#                             structured.queries_executed,
#                         )

#                         for search_record in search_records:
#                             model_db.add(search_record)

#                         # Audit record.
#                         model_db.add(
#                             build_audit_record(
#                                 tenant_id,
#                                 identifier,
#                                 model_name,
#                                 structured,
#                             )
#                         )

#                     await model_db.commit()

#                 # -------------------------------------------------
#                 # PROCESS RESULT AFTER DB COMMIT
#                 # -------------------------------------------------

#                 if structured:

#                     all_reports.append(structured.model_dump(mode="json"))

#                 usage_dict = token_usage.as_dict()

#                 total_usage["input_tokens"] += usage_dict["input_tokens"]

#                 total_usage["output_tokens"] += usage_dict["output_tokens"]

#                 total_usage["total_tokens"] += usage_dict["total_tokens"]

#                 yield progress.tick(
#                     f"{model_name} completed successfully "
#                     f"({usage_dict['total_tokens']} tokens used)."
#                 )

#             except Exception as model_error:

#                 # IMPORTANT:
#                 # Don't rollback the original request-level `db`.
#                 # Each model has its own session, so there is nothing
#                 # to rollback here after the context manager exits.

#                 progress.set_model_index(model_index + 1)

#                 yield model_warning_event(
#                     model_name,
#                     model_error,
#                 )

#         # ---------------------------------------------------------
#         # FINAL RESULT
#         # ---------------------------------------------------------

#         if all_reports:

#             # Use the recommendation JSON we already saved.
#             yield result_event(
#                 "GEO audit completed successfully",
#                 {
#                     "reports": all_reports,
#                     "recommendation": recommendation_json,
#                     "final_optimized_tips_summary": (
#                         all_reports[-1]["final_optimized_tips_summary"]
#                     ),
#                     "token_usage": total_usage,
#                 },
#             )

#         else:

#             yield error_event("All models failed to produce a report.")

#     except Exception as e:

#         # Don't try to rollback the request-level db here.
#         # All important DB operations use their own sessions.

#         yield failed_event(str(e))


"""
GEO audit orchestration.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import (
    SessionLocal,
)
from app.models.base import LLMModels

from .llm_runner import run_single_model_audit
from .recommandation import (
    generate_product_recommendations,
    _product_data,  # FIX: convert ORM -> plain dict
)
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
                "One identifier is required " "(product_name/sku/mpn/upc/product_url)"
            )
            return

        # ---------------------------------------------------------
        # 1. SHORT DB SESSION: PRODUCT LOOKUP
        # ---------------------------------------------------------

        async with SessionLocal() as lookup_db:

            product_record = await find_existing_product(
                lookup_db,
                tenant_id,
                lookup_filters,
            )

            if product_record:
                product_id = product_record.id

                yield status_event(
                    "Existing product located",
                    10,
                )

                recent_chat = await get_recent_cached_chat(
                    lookup_db,
                    product_id,
                )

                if recent_chat:
                    yield result_event(
                        "Warm cache hit",
                        recent_chat.final_optimization_report,
                    )
                    return

                # IMPORTANT:
                # Don't keep this ORM object around for later writes.
                #
                # We only need the ID and basic data.
                product_id = product_record.id

                # FIX:
                # Convert ORM object while its DB session is alive.
                # This prevents DetachedInstanceError later.
                product_data = _product_data(product_record)

            else:
                product_record = None
                product_id = None
                product_data = None

        # ---------------------------------------------------------
        # 2. CREATE PRODUCT IF IT DOESN'T EXIST
        # ---------------------------------------------------------

        if product_record is None:

            yield status_event(
                "Enriching missing product metadata...",
                15,
            )

            async with SessionLocal() as create_db:

                product_record = await create_new_product(
                    create_db,
                    payload,
                    tenant_id,
                    user_id,
                )

                await create_db.commit()

                # IMPORTANT:
                # Get the ID before this session closes.
                product_id = product_record.id

                # FIX:
                # Convert ORM -> plain dict while session is alive.
                product_data = _product_data(product_record)

        # ---------------------------------------------------------
        # 3. PREPARE LLM INPUT
        # ---------------------------------------------------------

        user_prompt = build_user_instruction_v2(payload)
        identifier = resolve_identifier(payload)

        yield status_event(
            "Generating GEO recommendations...",
            20,
        )

        search_keyword = f"{identifier} competitors buy online"

        # ---------------------------------------------------------
        # 4. IMPORTANT:
        # NO DB SESSION IS USED DURING THIS LONG LLM OPERATION
        # ---------------------------------------------------------

        # FIX:
        # generate_product_recommendations no longer needs DB.
        #
        # IMPORTANT:
        # Do NOT pass db=None.
        # Do NOT pass the SQLAlchemy product object.
        #
        # Pass the plain product_data dict instead.

        recommendations = await generate_product_recommendations(
            product_data=product_data,
            search_keyword=search_keyword,
            user_prompt=user_prompt,
        )

        recommendation_json = recommendations.model_dump(mode="json")

        # ---------------------------------------------------------
        # 5. FRESH DB SESSION FOR RECOMMENDATION UPDATE
        # ---------------------------------------------------------

        async with SessionLocal() as recommendation_db:

            # Fetch a fresh ORM object.
            product_record = await recommendation_db.get(
                type(product_record),
                product_id,
            )

            if product_record is None:
                raise RuntimeError(
                    f"Product {product_id} disappeared before recommendation save."
                )

            product_record.recommandation_v2 = recommendation_json

            await recommendation_db.commit()

            # Refresh only if you actually need DB-generated values.
            await recommendation_db.refresh(product_record)

        yield status_event(
            "GEO recommendations saved.",
            25,
        )

        # ---------------------------------------------------------
        # EXISTING AUDIT LOGIC
        # ---------------------------------------------------------

        models = list(LLMModels)

        progress = ProgressTracker(total_models=len(models))

        all_reports: list[dict] = []

        total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        for model_index, model_enum in enumerate(models):

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

                # -------------------------------------------------
                # LLM WORK
                # NO DB SESSION
                # -------------------------------------------------

                structured, token_usage = await run_single_model_audit(
                    model_name,
                    user_prompt,
                    search_keyword,
                )

                if structured:

                    structured.model_used = model_name

                    resolve_all_competitor_product_urls(structured)

                yield progress.tick(f"[{model_name}] Recording PostgreSQL logs...")

                # -------------------------------------------------
                # FRESH DB SESSION FOR THIS MODEL
                # -------------------------------------------------

                async with SessionLocal() as model_db:

                    # Re-fetch product because the old ORM object
                    # may belong to an old/closed session.
                    current_product = await model_db.get(
                        type(product_record),
                        product_id,
                    )

                    if current_product is None:
                        raise RuntimeError(f"Product {product_id} not found.")

                    if structured:

                        # Update product statistics.
                        if structured.product_details:

                            current_product.no_of_faqs = structured.product_details.faqs

                            current_product.no_of_reviews = (
                                structured.product_details.reviews
                            )

                        # Build Chat record.
                        chat_record = build_chat_record(
                            tenant_id,
                            product_id,
                            payload,
                            model_enum,
                            structured,
                            token_usage=token_usage,
                        )

                        model_db.add(chat_record)

                        await model_db.flush()

                        # Search query records.
                        search_records = build_search_query_records(
                            chat_record.id,
                            structured.queries_executed,
                        )

                        for search_record in search_records:
                            model_db.add(search_record)

                        # Audit record.
                        model_db.add(
                            build_audit_record(
                                tenant_id,
                                identifier,
                                model_name,
                                structured,
                            )
                        )

                    await model_db.commit()

                # -------------------------------------------------
                # PROCESS RESULT AFTER DB COMMIT
                # -------------------------------------------------

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

                # IMPORTANT:
                # Don't rollback the original request-level `db`.
                # Each model has its own session, so there is nothing
                # to rollback here after the context manager exits.

                progress.set_model_index(model_index + 1)

                yield model_warning_event(
                    model_name,
                    model_error,
                )

        # ---------------------------------------------------------
        # FINAL RESULT
        # ---------------------------------------------------------

        if all_reports:

            # Use the recommendation JSON we already saved.
            yield result_event(
                "GEO audit completed successfully",
                {
                    "reports": all_reports,
                    "recommendation": recommendation_json,
                    "final_optimized_tips_summary": (
                        all_reports[-1]["final_optimized_tips_summary"]
                    ),
                    "token_usage": total_usage,
                },
            )

        else:

            yield error_event("All models failed to produce a report.")

    except Exception as e:

        # Don't try to rollback the request-level db here.
        # All important DB operations use their own sessions.

        yield failed_event(str(e))
