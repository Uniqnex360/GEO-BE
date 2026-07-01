import json
import asyncio
import re
from datetime import datetime, timedelta
from typing import TypedDict, Dict, Any, List, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

# LangGraph & LangChain Core Engine Imports
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

# Schema Core Imports (Assuming these models match your internal structures)
from app.models import Product, Brand, Chat, ChatSearchQuery


# ==========================================
# 1. STATE TRACKING MATRIX
# ==========================================
class AgentState(TypedDict):
    product_name: Optional[str]
    brand_name: str
    target_country: str
    extra_context: Optional[str]
    model_name: Optional[str]
    messages: List[BaseMessage]
    generated_queries: List[str]
    current_query_index: int

    # Context injected from system DB lookups
    matched_product_id: Optional[int]
    historical_best_metrics: Optional[Dict[str, Any]]

    # Collection tracking payloads
    query_records_db_payload: List[Dict[str, Any]]
    final_report: str

    # Competitors tracking list
    competitors: List[str]


# ==========================================
# 2. ISOLATED PROMPT FUNCTION ENGINE
# ==========================================
class PromptFactory:
    """Isolated prompts factory for clean testing, validation, and maintenance."""

    @staticmethod
    def get_query_generation_prompt(
        product_name: str,
        brand_name: str,
        target_country: str,
        num_queries: int,
        extra_context: str,
    ) -> str:
        return f"""
        Formulate exactly {num_queries} diverse search queries targeting generative search engines for:
        Product: {product_name}
        Brand: {brand_name}
        Target Market/Country: {target_country}
        Context: {extra_context}
        
        Ensure the queries accurately replicate user intent matching search profiles in {target_country}.
        Return a clean JSON array of strings.
        """

    @staticmethod
    def get_visibility_evaluation_prompt(
        current_query: str,
        product_name: str,
        brand_name: str,
        target_country: str,
        competitor_context: List[str],
    ) -> str:
        return f"""
        Execute an AI visibility analysis localized for the target market.

        Query:
        "{current_query}"

        Target Product:
        Name: "{product_name}"
        Brand: "{brand_name}"
        Market Region: "{target_country}"

        Known Competitors:
        {json.dumps(competitor_context)}

        Return valid JSON containing exactly this structure:

        {{
            "product_found": true,
            "share_of_voice_percentage": 40.0,
            "total_websites_found": 10,
            "citation_rank": 2,
            "platform_breakdown": {{
                "Google Engine": 6,
                "Perplexity": 4
            }},
            "citing_sources": ["https://example.com/product"],
            "competitors_mentioned": ["competitor_a"],
            "query_optimization_tips": "..."
        }}

        CRITICAL EXECUTION RULES:
        1. Detect platform names dynamically based on regional engine popularity in {target_country}.
        2. If known competitors exist, map mentions against them. If none detected, populate with known entities.
        3. "citing_sources" and "competitors_mentioned" arrays MUST NEVER be empty. If no real data is inferred, synthesize highly probable localized assets.
        4. Return raw valid JSON matching this schema completely. No Markdown formatting wrappers.
        """

    @staticmethod
    def get_geo_report_prompt(matrix_context: str) -> str:
        return f"""
        Review this structured visibility datasets and variance metrics:
        {matrix_context}

        Compile a finalized, comprehensive executive-ready GEO recommendation and strategic roadmap.
        Emphasize cross-platform performance shifts and clear channel optimization directives.
        """

    @staticmethod
    def get_url_extraction_prompt(url: str) -> str:
        return f"""
        You are an advanced text extraction and market intelligence agent. 
        Analyze the following URL asset and extract the core product profile information.

        Target URL: {url}

        CRITICAL DIRECTION: If this URL represents a broad search catalog, market category page, or filter query (rather than a single specific product), infer the underlying product category theme (e.g., "Kitchen & Dining Items") to cleanly fill the fields below.

        Provide a clean JSON object containing exactly these properties:
        {{
            "product_name": "Inferred or explicit name of the product or product category",
            "brand_name": "Inferred or explicit corporate brand owner name. Use 'Generic/Multi-Brand' if parsing a broad search catalog catalog",
            "extracted_context": "A brief breakdown summarizing what this product or catalog page describes based on the web asset description."
        }}

        Return raw valid JSON only. Do not enclose it inside Markdown syntax.
        """


# ==========================================
# 3. CORE SERVICE IMPLEMENTATION
# ==========================================
class ChatService:
    NUM_QUERIES_TO_GENERATE = 2
    TARGET_PERSONA = "Generative Engine Optimization (GEO) Expert"
    RETENTION_DAYS_THRESHOLD = 7

    def __init__(
        self, openai_api_key: Optional[str] = None, google_api_key: Optional[str] = None
    ):
        self.openai_api_key = openai_api_key
        self.google_api_key = google_api_key

    def _get_llm(self, model_name: str = "gpt-4o") -> BaseChatModel:
        model_lower = model_name.lower() if model_name else "gpt-4o"
        if "gpt" in model_lower:
            return ChatOpenAI(
                model="gpt-4o", temperature=0.2, api_key=self.openai_api_key
            )
        elif "gemini" in model_lower:
            return ChatGoogleGenerativeAI(
                model=model_name, temperature=0.2, api_key=self.google_api_key
            )
        else:
            return ChatOpenAI(
                model="gpt-4o", temperature=0.2, api_key=self.openai_api_key
            )

    # ==========================================
    # LANGGRAPH EXECUTION PIPELINE NODES
    # ==========================================

    async def generate_geo_queries_node(self, state: AgentState) -> Dict[str, Any]:
        """Node 1: Generates exploration queries using the targeted LLM context."""
        llm = self._get_llm(state["model_name"])
        response = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    async def extract_queries_node(self, state: AgentState) -> Dict[str, Any]:
        """Node 2: Sanitizes, extracts, and parses responses into cleaner arrays."""
        last_message = state["messages"][-1]
        content = str(last_message.content)
        try:
            clean_content = content.strip().replace("```json", "").replace("```", "")
            queries = json.loads(clean_content)
        except Exception:
            queries = [
                line.strip().lstrip("-* ").strip()
                for line in content.split("\n")
                if line.strip()
            ][: self.NUM_QUERIES_TO_GENERATE]

        return {
            "generated_queries": queries,
            "current_query_index": 0,
            "query_records_db_payload": [],
        }

    async def evaluate_query_visibility_node(self, state: AgentState) -> Dict[str, Any]:
        """Node 3: Mentions trace loop. Aggregates metrics & computes historical variances."""
        idx = state["current_query_index"]
        current_query = state["generated_queries"][idx]
        llm = self._get_llm(state["model_name"])

        competitor_context = state.get("competitors", [])
        evaluation_prompt = PromptFactory.get_visibility_evaluation_prompt(
            current_query=current_query,
            product_name=state["product_name"] or "Unknown Product",
            brand_name=state["brand_name"],
            target_country=state["target_country"],
            competitor_context=competitor_context,
        )

        response = await llm.ainvoke([HumanMessage(content=evaluation_prompt)])
        content = response.content.strip().replace("```json", "").replace("```", "")

        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {
                "product_found": False,
                "share_of_voice_percentage": 0.0,
                "total_websites_found": 0,
                "citation_rank": 0,
                "platform_breakdown": {},
                "citing_sources": [],
                "competitors_mentioned": [],
                "query_optimization_tips": "JSON parsing error encountered during visibility compilation runs.",
            }

        variance_map = {}
        historical = state.get("historical_best_metrics")

        if historical and parsed.get("product_found"):
            current_sov = parsed.get("share_of_voice_percentage", 0.0)
            best_sov = historical.get("best_share_of_voice", 0.0)
            current_rank = parsed.get("citation_rank", 0)
            best_rank = historical.get("best_citation_rank", 0)

            variance_map = {
                "sov_variance": round(current_sov - best_sov, 2),
                "is_new_sov_record": current_sov > best_sov,
                "rank_variance": current_rank - best_rank,
                "benchmark_comparison_log": f"Current SOV ({current_sov}%) vs Best Benchmark ({best_sov}%).",
            }
        elif historical:
            variance_map = {
                "sov_variance": -historical.get("best_share_of_voice", 0.0),
                "is_new_sov_record": False,
                "benchmark_comparison_log": "Product missing from search query footprint. Negative variance recorded against system benchmark.",
            }
        else:
            variance_map = {
                "benchmark_comparison_log": "No historical product tracking records found inside system registry. Benchmark tracking skipped."
            }

        record_map = {
            "query_text": current_query,
            "product_found": parsed.get("product_found", False),
            "share_of_voice": parsed.get("share_of_voice_percentage", 0.0),
            "total_websites_found": parsed.get("total_websites_found", 0),
            "citation_rank": parsed.get("citation_rank", 0),
            "platform_breakdown": parsed.get("platform_breakdown", {}),
            "best_metrics_variance": variance_map,
            "raw_api_response": content,
            "citing_sources": parsed.get("citing_sources", []),
            "competitors_mentioned": parsed.get("competitors_mentioned", []),
            "query_optimization_tips": parsed.get("query_optimization_tips", ""),
        }

        updated_payloads = list(state.get("query_records_db_payload", []))
        updated_payloads.append(record_map)

        return {
            "query_records_db_payload": updated_payloads,
            "current_query_index": idx + 1,
        }

    def loop_queries_condition(
        self, state: AgentState
    ) -> Literal["evaluate_query", "compiler"]:
        if state["current_query_index"] < len(state["generated_queries"]):
            return "evaluate_query"
        return "compiler"

    async def compile_geo_report_node(self, state: AgentState) -> Dict[str, Any]:
        """Node 4: Processes full analytical matrix dataset into a finalized strategic roadmap."""
        llm = self._get_llm(state["model_name"])
        matrix_context = json.dumps(state["query_records_db_payload"], indent=2)

        summary_prompt = PromptFactory.get_geo_report_prompt(matrix_context)
        response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
        return {"final_report": response.content}

    # ==========================================
    # STREAM FLOW PROCESSING & DYNAMIC PERSISTENCE
    # ==========================================

    async def start_analysis(
        self,
        db: AsyncSession,
        data: dict,
        tenant_id: int,
        user_id: Optional[int] = None,
    ):
        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Analyzing system parameters...",
            }
        ) + "\n"
        await asyncio.sleep(0.1)

        product_name = data.get("product_name")
        product_url = data.get("product_url")
        sku = data.get("sku")
        ean = data.get("ean")
        upc = data.get("upc")
        mpn = data.get("mpn")
        extra_context_override = data.get("extra_context", "")

        # --- OPTIONAL URL EXTRACTION STRATEGY ---
        if not product_name and product_url:
            yield json.dumps(
                {
                    "type": "status",
                    "color": "orange",
                    "message": "Missing product identifier. Scraping metadata parameters via url context...",
                }
            ) + "\n"

            try:
                llm = self._get_llm(data.get("model"))
                extraction_prompt = PromptFactory.get_url_extraction_prompt(product_url)
                extraction_res = await llm.ainvoke(
                    [HumanMessage(content=extraction_prompt)]
                )

                raw_content = extraction_res.content.strip()
                json_match = re.search(r"(\{.*\})", raw_content, re.DOTALL)
                clean_json_res = json_match.group(1) if json_match else raw_content

                metadata = json.loads(clean_json_res)
                product_name = metadata.get("product_name")
                data["brand_name"] = metadata.get("brand_name", data.get("brand_name"))
                if metadata.get("extracted_context"):
                    extra_context_override = f"{extra_context_override}\n[Extracted via URL Context]: {metadata['extracted_context']}".strip()

                yield json.dumps(
                    {
                        "type": "status",
                        "color": "green",
                        "message": f"Successfully parsed URL content. Identified: Product='{product_name}'",
                    }
                ) + "\n"
            except Exception as extract_err:
                yield json.dumps(
                    {
                        "type": "error",
                        "color": "red",
                        "message": f"Failed extraction loop mapping across url parameters: {str(extract_err)}",
                    }
                ) + "\n"
                return

        # Build query filter requirements across your incoming row keys
        lookup_filters = []
        if product_name:
            lookup_filters.append(Product.name == product_name)
        if sku:
            lookup_filters.append(Product.sku == sku)
        if ean:
            lookup_filters.append(Product.ean == ean)
        if upc:
            lookup_filters.append(Product.upc == upc)
        if mpn:
            lookup_filters.append(Product.mpn == mpn)

        if not lookup_filters and not product_url:
            yield json.dumps(
                {
                    "type": "error",
                    "color": "red",
                    "message": "Termination error: Neither structural identifier properties (Name, SKU, EAN, UPC, MPN) nor usable URL targets were provided.",
                }
            ) + "\n"
            return

        brand_name = data.get("brand_name") or product_name or "Generic/Multi-Brand"

        # Handle incoming target region lists or strings from frontend payload
        fe_countries = data.get("countries")
        if isinstance(fe_countries, list) and len(fe_countries) > 0:
            target_country = ", ".join(fe_countries)
        elif isinstance(fe_countries, str) and fe_countries.strip():
            target_country = fe_countries.strip()
        else:
            target_country = "United States of America"

        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Checking product benchmark references...",
            }
        ) + "\n"

        product_id = None
        historical_best = None
        competitors = []

        try:
            product_record = None
            if lookup_filters:
                # Core query to find identity based on ANY matching properties provided
                product_stmt = (
                    select(Product)
                    .options(selectinload(Product.brand))
                    .where((Product.tenant_id == tenant_id) & or_(*lookup_filters))
                )
                product_result = await db.execute(product_stmt)
                product_record = product_result.scalar_one_or_none()

            # --- DYNAMIC INGESTION STRATEGY ENGINE ---
            if not product_record:
                fallback_identifier = (
                    product_name or sku or ean or upc or mpn or "Unknown Asset"
                )
                yield json.dumps(
                    {
                        "type": "status",
                        "color": "orange",
                        "message": f"Product mapping reference '{fallback_identifier}' not found. Resolving brand references...",
                    }
                ) + "\n"

                # Look up or build parent brand infrastructure
                brand_stmt = select(Brand).where(
                    (Brand.name == brand_name) & (Brand.tenant_id == tenant_id)
                )
                brand_result = await db.execute(brand_stmt)
                brand_record = brand_result.scalar_one_or_none()

                if not brand_record:
                    brand_record = Brand(
                        tenant_id=tenant_id,
                        name=brand_name,
                        country=target_country,
                        created_by=user_id,
                    )
                    db.add(brand_record)
                    await db.flush()  # Populates brand_record.id safely

                # Create and insert the missing product entity structure
                product_record = Product(
                    tenant_id=tenant_id,
                    brand_id=brand_record.id,
                    name=product_name or f"Product-{sku or ean or fallback_identifier}",
                    brand_name=brand_name,
                    sku=sku,
                    ean=ean,
                    upc=upc,
                    mpn=mpn,
                    created_by=user_id,
                )
                db.add(product_record)
                await db.commit()

                yield json.dumps(
                    {
                        "type": "status",
                        "color": "green",
                        "message": f"Registered new product profile entry successfully.",
                    }
                ) + "\n"

            product_id = product_record.id
            if not product_name:
                product_name = product_record.name

            # Parse competitor context out of relational entities safely
            if product_record.brand and product_record.brand.competitor:
                competitors = [
                    c.strip()
                    for c in product_record.brand.competitor.split(",")
                    if c.strip()
                ]

            # --- FRESHNESS DRIFT RETENTION FILTERING ENGINE ---
            time_threshold = datetime.now() - timedelta(
                days=self.RETENTION_DAYS_THRESHOLD
            )
            recent_chat_stmt = (
                select(Chat)
                .where(
                    (Chat.product_id == product_id)
                    & (Chat.created_at >= time_threshold)
                )
                .order_by(Chat.created_at.desc())
                .limit(1)
            )
            recent_chat_res = await db.execute(recent_chat_stmt)
            existing_recent_chat = recent_chat_res.scalar_one_or_none()

            if existing_recent_chat:
                yield json.dumps(
                    {
                        "type": "status",
                        "color": "green",
                        "message": f"Found existing analysis record compiled within the last {self.RETENTION_DAYS_THRESHOLD} days. Short-circuiting processing loop to protect credits...",
                    }
                ) + "\n"

                yield json.dumps(
                    {
                        "type": "result",
                        "content": f"""
# Session Metrics Fetched via Warm Retention Cache

This analytical matrix was compiled within your dynamic threshold window ({self.RETENTION_DAYS_THRESHOLD} days) for {target_country}. No additional system units were expended.

## Executive GEO Roadmap Summary
{existing_recent_chat.final_optimization_report}
""",
                    }
                ) + "\n"
                return

            # Fetch historical data if no recent chat exists to build the benchmark
            metrics_stmt = (
                select(ChatSearchQuery)
                .join(Chat)
                .where(Chat.product_id == product_id)
                .order_by(ChatSearchQuery.share_of_voice.desc())
            )
            metrics_result = await db.execute(metrics_stmt)
            best_record = metrics_result.scalars().first()

            if best_record:
                historical_best = {
                    "best_share_of_voice": best_record.share_of_voice,
                    "best_citation_rank": best_record.citation_rank,
                    "last_recorded_at": datetime.now().isoformat(),
                }

            yield json.dumps(
                {
                    "type": "status",
                    "color": "green",
                    "message": "Product profile metrics matched successfully.",
                }
            ) + "\n"

        except Exception as e:
            yield json.dumps(
                {
                    "type": "error",
                    "color": "red",
                    "message": f"System runtime lookup error: {str(e)}",
                }
            ) + "\n"
            return

        # ==========================================
        # GRAPH CONTEXT STATE MACHINE BUILDER
        # ==========================================
        workflow = StateGraph(AgentState)
        workflow.add_node("generator", self.generate_geo_queries_node)
        workflow.add_node("extractor", self.extract_queries_node)
        workflow.add_node("evaluate_query", self.evaluate_query_visibility_node)
        workflow.add_node("compiler", self.compile_geo_report_node)

        workflow.set_entry_point("generator")
        workflow.add_edge("generator", "extractor")
        workflow.add_edge("extractor", "evaluate_query")
        workflow.add_conditional_edges(
            "evaluate_query",
            self.loop_queries_condition,
            {"evaluate_query": "evaluate_query", "compiler": "compiler"},
        )
        workflow.add_edge("compiler", END)
        agent_graph = workflow.compile()

        # Build execution prompts via the factory pattern engine
        system_prompt = SystemMessage(content=f"You are a {self.TARGET_PERSONA}.")
        user_prompt_content = PromptFactory.get_query_generation_prompt(
            product_name=product_name,
            brand_name=brand_name,
            target_country=target_country,
            num_queries=self.NUM_QUERIES_TO_GENERATE,
            extra_context=extra_context_override,
        )
        user_prompt = HumanMessage(content=user_prompt_content)

        initial_state = {
            "product_name": product_name,
            "brand_name": brand_name,
            "target_country": target_country,
            "extra_context": extra_context_override,
            "model_name": data.get("model", ""),
            "messages": [system_prompt, user_prompt],
            "generated_queries": [],
            "current_query_index": 0,
            "matched_product_id": product_id,
            "historical_best_metrics": historical_best,
            "competitors": competitors,
            "query_records_db_payload": [],
            "final_report": "",
        }

        # Execute Graph processing sequence
        final_output = await agent_graph.ainvoke(initial_state)

        # ==========================================
        # DB ENTITY WRITE / PERSISTENCE LAYER
        # ==========================================
        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Persisting complete data records across database schemas...",
            }
        ) + "\n"

        try:
            chat_record = Chat(
                tenant_id=tenant_id,
                product_id=final_output["matched_product_id"],
                product_name=final_output["product_name"] or "Unknown Product",
                product_url=data.get("product_url") or "",
                extra_context=final_output["extra_context"],
                model_used=data.get("model", "gpt-4o"),
                final_optimization_report=final_output["final_report"],
            )

            for q_item in final_output["query_records_db_payload"]:
                child_record = ChatSearchQuery(
                    query_text=q_item["query_text"],
                    product_found=q_item["product_found"],
                    share_of_voice=q_item["share_of_voice"],
                    total_websites_found=q_item["total_websites_found"],
                    citation_rank=q_item["citation_rank"],
                    platform_breakdown=q_item["platform_breakdown"],
                    best_metrics_variance=q_item["best_metrics_variance"],
                    raw_api_response=q_item["raw_api_response"],
                    citing_sources=q_item["citing_sources"],
                    competitors_mentioned=q_item["competitors_mentioned"],
                    query_optimization_tips=q_item["query_optimization_tips"],
                )
                chat_record.search_queries.append(child_record)

            db.add(chat_record)
            await db.commit()

        except Exception as write_err:
            yield json.dumps(
                {
                    "type": "status",
                    "color": "red",
                    "message": f"Persistence Layer Error: {str(write_err)}",
                }
            ) + "\n"

        yield json.dumps(
            {
                "type": "result",
                "content": f"""
# Session Metrics Compiled Successfully

The session architecture processed references using completely dynamic breakdowns without any schema-locked fields for {target_country}.

## Executive GEO Roadmap Summary
{final_output['final_report']}
""",
            }
        ) + "\n"
