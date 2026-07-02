import json
from typing import Dict, Any, Optional
import openai

# import google.generativeai as gemini # Uncomment when using Gemini


class LLMAdapter:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate_json(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> Dict[str, Any]:
        """
        Swappable model gateway. Handles routing to different providers
        depending on the specified model string name.
        """
        # --- OpenAI Route ---
        if "gpt-" in model or "o1-" in model:
            client = openai.AsyncOpenAI(api_key=self.api_key)
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return json.loads(response.choices[0].message.content)

        # --- Gemini Route (Example Integration) ---
        elif "gemini-" in model:
            # gemini.configure(api_key=self.api_key)
            # model_instance = gemini.GenerativeModel(model_name=model)
            # ... process Gemini structured generation ...
            raise NotImplementedError("Gemini client integration can be toggled here.")

        else:
            raise ValueError(f"Unsupported model target: {model}")



import json
from typing import AsyncGenerator, Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

# Import your database models
from app.models import Brand, Product, Chat, ChatSearchQuery
from app.services.llm_factory import LLMAdapter

CACHE_THRESHOLD_DAYS = 7

class ChatV2Service:
    def __init__(self, openai_api_key: str):
        self.llm = LLMAdapter(api_key=openai_api_key)

    async def start_analysis(self, db: AsyncSession, body: dict, tenant_id: int) -> AsyncGenerator[str, None]:
        try:
            yield self._status("green", "Initializing validation parameters...")
            
            product_name = body.get("product_name")
            product_url = body.get("product_url")
            extra_context = body.get("extra_context")
            model_used = body.get("model", "gpt-4o")  # Defaulting back if gpt-5-nano isn't live yet
            sku = body.get("sku")
            mpn = body.get("mpn")
            upc = body.get("upc")
            ean = body.get("ean")
            countries = body.get("countries", ["United States of America"])
            country_str = ", ".join(countries)

            # -------------------------------------------------------------
            # STEP 1 & 2: Check for Existing Product & Cache Validation
            # -------------------------------------------------------------
            yield self._status("green", "Looking for matching products & looking up cache hits...")
            
            # Sub-clause query to match target product criteria
            product_stmt = select(Product).where(
                and_(
                    Product.tenant_id == tenant_id,
                    (Product.name == product_name) | (Product.product_url == product_url)
                )
            )
            product_res = await db.execute(product_stmt)
            product: Optional[Product] = product_res.scalar_one_or_none()

            if product:
                # Look for an existing chat cache generated within the specified threshold window
                cache_limit = datetime.utcnow() - timedelta(days=CACHE_THRESHOLD_DAYS)
                cache_stmt = (
                    select(Chat)
                    .where(
                        and_(
                            Chat.product_id == product.id,
                            Chat.tenant_id == tenant_id,
                            Chat.created_at >= cache_limit
                        )
                    )
                    .options(selectinload(Chat.search_queries))
                    .order_by(Chat.created_at.desc())
                    .limit(1)
                )
                cache_res = await db.execute(cache_stmt)
                cached_chat: Optional[Chat] = cache_res.scalar_one_or_none()

                if cached_chat:
                    yield self._status("blue", f"Cache hit! Found analysis session matching past {CACHE_THRESHOLD_DAYS} days.")
                    yield json.dumps({
                        "type": "result",
                        "source": "cache",
                        "chat_id": cached_chat.id,
                        "product_id": product.id,
                        "final_optimization_report": cached_chat.final_optimization_report,
                        "queries": [
                            {
                                "query_text": q.query_text,
                                "product_found": q.product_found,
                                "share_of_voice": q.share_of_voice,
                                "total_websites_found": q.total_websites_found,
                                "citation_rank": q.citation_rank,
                                "platform_breakdown": q.platform_breakdown,
                                "best_metrics_variance": q.best_metrics_variance
                            } for q in cached_chat.search_queries
                        ]
                    }) + "\n"
                    return

            # -------------------------------------------------------------
            # STEP 3: Fallback Product and Brand Discovery Generation
            # -------------------------------------------------------------
            if not product:
                yield self._status("green", f"Product missing. Discovering brand profiles via AI engine for {country_str}...")
                
                brand_sys = "You are a market research bot. Extract and return metadata as structured JSON profiles."
                brand_user = f"""
                Analyze product: "{product_name}". Context: {extra_context}. 
                Identify its Brand and primary Competitors within: {country_str}.
                Return exactly this format:
                {{
                    "brand_name": "Calculated Brand Name",
                    "industry": "Calculated Industry Type",
                    "competitors": ["Competitor A", "Competitor B"]
                }}
                """
                brand_data = await self.llm.generate_json(model_used, brand_sys, brand_user)

                # Find or save the Brand profile entity
                brand_stmt = select(Brand).where(
                    and_(Brand.name == brand_data["brand_name"], Brand.tenant_id == tenant_id)
                )
                b_res = await db.execute(brand_stmt)
                brand_obj: Optional[Brand] = b_res.scalar_one_or_none()

                if not brand_obj:
                    brand_obj = Brand(
                        tenant_id=tenant_id,
                        name=brand_data["brand_name"],
                        industry=brand_data["industry"],
                        country=country_str,
                        competitor=", ".join(brand_data["competitors"])
                    )
                    db.add(brand_obj)
                    await db.flush()  # Capture brand_obj.id

                # Provision the record in our local Product catalog table
                product = Product(
                    tenant_id=tenant_id,
                    brand_id=brand_obj.id,
                    name=product_name,
                    brand_name=brand_obj.name,
                    product_url=product_url,
                    sku=sku,
                    mpn=mpn,
                    upc=upc,
                    ean=ean,
                    short_description=extra_context
                )
                db.add(product)
                await db.flush()  # Capture product.id

            # -------------------------------------------------------------
            # STEP 4 & 5: Single-Shot Engine Optimization Simulation Run
            # -------------------------------------------------------------
            yield self._status("green", "Synthesizing dynamic platform variations and metric variances...")

            geo_sys = """
            You are an advanced GEO Engine. Generate long-tail search visibility items classified into intentions 
            (Informational, Commercial, Transactional, Comparison, Problem solving).
            For each item, simulate search metrics (Share of Voice, Citation Rank, Breakdown) and provide optimization feedback logs.
            Return ALL variations encapsulated inside a structured JSON configuration layout root object.
            """
            
            geo_user = f"""
            Generate a detailed search engine optimization visibility matrix for:
            Product: "{product.name}"
            Brand: "{product.brand_name}"
            Identifiers: MPN={product.mpn}, SKU={product.sku}
            Extra Context: "{product.short_description}"
            Target Regions: {country_str}

            Output requirements:
            Return exactly a JSON object matching this schema layout:
            {{
                "overall_report": "Comprehensive dynamic strategy guidelines detail text...",
                "queries": [
                    {{
                        "query_text": "Long tail variation search sentence...",
                        "intent_classification": "Transactional",
                        "product_found": true,
                        "share_of_voice": 40.0,
                        "total_websites_found": 10,
                        "citation_rank": 2,
                        "platform_breakdown": {{"google_search": 2, "reddit": 1}},
                        "best_metrics_variance": {{"sov_variance": 40.0, "rank_variance": 2, "is_new_sov_record": true}},
                        "citing_sources": ["https://example.com/item"],
                        "competitors_mentioned": ["Competitor X"],
                        "query_optimization_tips": "Content alignment structural tips details string."
                    }}
                ]
            }}
            """
            
            analysis_output = await self.llm.generate_json(model_used, geo_sys, geo_user)

            # -------------------------------------------------------------
            # STEP 6: Consolidated Unit of Work Persist Sequence
            # -------------------------------------------------------------
            yield self._status("green", "Persisting analytical matrix snapshots down to data-store layer...")

            # Initialize parent chat structure
            new_chat = Chat(
                tenant_id=tenant_id,
                product_id=product.id,
                product_name=product.name,
                product_url=product_url or "N/A",
                extra_context=extra_context,
                model_used=model_used,
                final_optimization_report=analysis_output["overall_report"]
            )

            # Map array references directly to the parent relationship object list
            # SQLAlchemy automatically ties foreign key dependencies during batch flushes
            new_chat.search_queries = [
                ChatSearchQuery(
                    query_text=q["query_text"],
                    product_found=q["product_found"],
                    share_of_voice=q["share_of_voice"],
                    total_websites_found=q["total_websites_found"],
                    citation_rank=q["citation_rank"],
                    platform_breakdown=q["platform_breakdown"],
                    best_metrics_variance=q["best_metrics_variance"],
                    raw_api_response=json.dumps(q),
                    citing_sources=q["citing_sources"],
                    competitors_mentioned=q["competitors_mentioned"],
                    query_optimization_tips=q["query_optimization_tips"]
                )
                for q in analysis_output["queries"]
            ]

            # Atomic transaction save window
            db.add(new_chat)
            await db.commit()

            # Broadcast final structural payload delivery
            yield self._status("green", "Analysis execution lifecycle finished successfully.")
            yield json.dumps({
                "type": "result",
                "source": "live",
                "chat_id": new_chat.id,
                "product_id": product.id,
                "final_optimization_report": new_chat.final_optimization_report,
                "queries": analysis_output["queries"]
            }) + "\n"

        except Exception as e:
            await db.rollback()
            yield self._status("red", f"Fatal exception failure caught: {str(e)}")

    def _status(self, color: str, message: str) -> str:
        """Helper to cleanly format real-time pipeline telemetry status items."""
        return json.dumps({
            "type": "status",
            "color": color,
            "message": message
        }) + "\n"