import json
import asyncio
from datetime import datetime
from typing import TypedDict, Dict, Any, List, Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# LangGraph & LangChain Core Engine Imports
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

# Assuming your actual models exist at these paths
from app.models import Product, Chat, ChatSearchQuery


# 1. State Tracking Matrix
class AgentState(TypedDict):
    product_name: str
    product_url: str
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


class ChatService:
    NUM_QUERIES_TO_GENERATE = 2
    TARGET_PERSONA = "Generative Engine Optimization (GEO) Expert"

    def __init__(self, openai_api_key: str = None, google_api_key: str = None):
        self.openai_api_key = openai_api_key
        self.google_api_key = google_api_key

    def _get_llm(self, model_name: str = "gpt-5-nano") -> BaseChatModel:
        model_lower = model_name.lower()
        if "gpt" in model_lower:
            return ChatOpenAI(
                model="gpt-5-nano", temperature=0.2, api_key=self.openai_api_key
            )
        elif "gemini" in model_lower:
            return ChatGoogleGenerativeAI(
                model=model_name, temperature=0.2, api_key=self.google_api_key
            )
        else:
            return ChatOpenAI(
                model="gpt-5-nano", temperature=0.2, api_key=self.openai_api_key
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
        """
        Node 3: Mentions trace loop. Dynamically aggregates platform citation counts
        and computes the variance against historical metrics if a product profile is linked.
        """
        idx = state["current_query_index"]
        current_query = state["generated_queries"][idx]
        llm = self._get_llm(state["model_name"])

        evaluation_prompt = f"""
        Execute an AI search visualization analysis for this search query: "{current_query}"
        Target Product Name: "{state['product_name']}"
        Target Product URL: "{state['product_url']}"

        Analyze citation matrices. Return a clean, valid JSON block matching this exact structure:
        {{
           "product_found": true,
           "share_of_voice_percentage": 40.0,
           "total_websites_found": 10,
           "citation_rank": 2,
           "platform_breakdown": {{
              "reddit": 3,
              "amazon": 5,
              "forums": 2
           }},
           "citing_sources": ["https://reddit.com/r/paint", "https://amazon.com/product"],
           "competitors_mentioned": ["Competitor Alpha", "Competitor Beta"],
           "query_optimization_tips": "Compare our product with found entities. Provide detailed content enhancements or channel recommendations."
        }}
        Return ONLY valid JSON without markdown formatting backticks.
        """

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

        # --- DYNAMIC HISTORICAL METRICS VARIANCE ENGINE ---
        variance_map = {}
        historical = state.get("historical_best_metrics")

        if historical and parsed.get("product_found"):
            # Compute variances dynamically against system benchmarks
            current_sov = parsed.get("share_of_voice_percentage", 0.0)
            best_sov = historical.get("best_share_of_voice", 0.0)
            current_rank = parsed.get("citation_rank", 0)
            best_rank = historical.get("best_citation_rank", 0)

            variance_map = {
                "sov_variance": round(current_sov - best_sov, 2),
                "is_new_sov_record": current_sov > best_sov,
                "rank_variance": current_rank
                - best_rank,  # Negative indicates improvements in search rankings
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

        # Flatten records completely, handling platform breakdowns dynamically
        record_map = {
            "query_text": current_query,
            "product_found": parsed.get("product_found", False),
            "share_of_voice": parsed.get("share_of_voice_percentage", 0.0),
            "total_websites_found": parsed.get("total_websites_found", 0),
            "citation_rank": parsed.get("citation_rank", 0),
            "platform_breakdown": parsed.get(
                "platform_breakdown", {}
            ),  # Entirely dynamic JSON block
            "best_metrics_variance": variance_map,  # Dynamic analytical comparisons
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
        """Node 4: Processes the full analytical matrix into a finalized strategic report."""
        llm = self._get_llm(state["model_name"])
        matrix_context = json.dumps(state["query_records_db_payload"], indent=2)

        summary_prompt = f"""
        Review this structured visibility datasets and variance metrics:
        {matrix_context}

        Compile a finalized, comprehensive executive-ready GEO recommendation and strategic roadmap.
        Emphasize cross-platform performance shifts and clear channel optimization directives.
        """
        response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
        return {"final_report": response.content}

    # ==========================================
    # STREAM FLOW PROCESSING & CORE PERSISTENCE
    # ==========================================

    async def start_analysis(self, db: AsyncSession, data: dict, tenant_id: int):
        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Analyzing system parameters...",
            }
        ) + "\n"
        await asyncio.sleep(0.1)

        # 1. DYNAMIC SYSTEM RECOGNITION LOOKUP FOR HISTORICAL METRICS
        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Checking product benchmark references...",
            }
        ) + "\n"

        product_id = None
        historical_best = None

        try:
            # Search product by URL or product name
            stmt = select(Product).where(
                (Product.product_url == data.get("product_url")) |
                (Product.name == data.get("product_name"))
            )

            result = await db.execute(stmt)
            product_record = result.scalar_one_or_none()

            # Product not found → stop execution immediately
            if not product_record:
                yield json.dumps(
                    {
                        "type": "error",
                        "color": "red",
                        "message": f"Given product '{data.get('product_name')}' not found in database."
                    }
                ) + "\n"

                return

            # Use actual DB product id
            product_id = product_record.id

            # Fetch previous best metrics dynamically
            stmt = (
                select(ChatSearchQuery)
                .join(Chat)
                .where(Chat.product_id == product_id)
                .order_by(ChatSearchQuery.share_of_voice.desc())
            )

            result = await db.execute(stmt)
            best_record = result.scalars().first()

            historical_best = None

            if best_record:
                historical_best = {
                    "best_share_of_voice": best_record.share_of_voice,
                    "best_citation_rank": best_record.citation_rank,
                    "last_recorded_at": datetime.now().isoformat()
                }

            yield json.dumps(
                {
                    "type": "status",
                    "color": "green",
                    "message": "Product matched successfully."
                }
            ) + "\n"

        except Exception as e:
            yield json.dumps(
                {
                    "type": "error",
                    "color": "red",
                    "message": f"Product lookup error: {str(e)}"
                }
            ) + "\n"

            return

        # 2. Build LangGraph workflow pipeline configurations
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

        system_prompt = SystemMessage(content=f"You are a {self.TARGET_PERSONA}.")
        user_prompt = HumanMessage(content=f"""
        Formulate exactly {self.NUM_QUERIES_TO_GENERATE} diverse search queries targeting search interfaces for:
        Product: {data.get('product_name')}
        URL: {data.get('product_url')}
        Context: {data.get('extra_context', '')}
        
        Return a clean JSON array of strings.
        """)

        initial_state = {
            "product_name": data.get("product_name"),
            "product_url": data.get("product_url"),
            "extra_context": data.get("extra_context", ""),
            "model_name": data.get("model", ""),
            "messages": [system_prompt, user_prompt],
            "generated_queries": [],
            "current_query_index": 0,
            "matched_product_id": product_id,
            "historical_best_metrics": historical_best,
            "query_records_db_payload": [],
            "final_report": "",
        }

        # 3. Process the LangGraph execution flow
        final_output = await agent_graph.ainvoke(initial_state)

        # 4. Atomic PostgreSQL DB Mapping Insertion Engine
        yield json.dumps(
            {
                "type": "status",
                "color": "green",
                "message": "Persisting complete data records across database schemas...",
            }
        ) + "\n"

        try:
            # Instantiate parent chat record
            chat_record = Chat(
                tenant_id=tenant_id,
                product_id=final_output["matched_product_id"],
                product_name=final_output["product_name"],
                product_url=final_output["product_url"],
                extra_context=final_output["extra_context"],
                model_used=data.get("model", "gpt-4o"),
                final_optimization_report=final_output["final_report"]
            )

            # Map child entity configurations directly into dynamic JSONB attributes
            for q_item in final_output["query_records_db_payload"]:
                child_record = ChatSearchQuery(
                    query_text=q_item["query_text"],
                    product_found=q_item["product_found"],
                    share_of_voice=q_item["share_of_voice"],
                    total_websites_found=q_item["total_websites_found"],
                    citation_rank=q_item["citation_rank"],
                    platform_breakdown=q_item["platform_breakdown"],      # Dynamic maps
                    best_metrics_variance=q_item["best_metrics_variance"], # Dynamic maps
                    raw_api_response=q_item["raw_api_response"],
                    citing_sources=q_item["citing_sources"],
                    competitors_mentioned=q_item["competitors_mentioned"],
                    query_optimization_tips=q_item["query_optimization_tips"]
                )
                chat_record.search_queries.append(child_record)

            db.add(chat_record)
            await db.commit()
            pass
        except Exception as write_err:
            yield json.dumps(
                {
                    "type": "status",
                    "color": "red",
                    "message": f"Persistence Error: {str(write_err)}",
                }
            ) + "\n"

        # Output payload validation log display block trace execution dump
        print("\n" + "=" * 70)
        print("COMPLETELY DYNAMIC PRODUCTION TRACE:")
        print("=" * 70)
        print(json.dumps(final_output["query_records_db_payload"], indent=2))
        print("=" * 70 + "\n")

        yield json.dumps(
            {
                "type": "result",
                "content": f"""
# Session Metrics Compiled Successfully

The session architecture processed references using completely dynamic breakdowns without any schema-locked fields.

## Executive GEO Roadmap Summary
{final_output['final_report']}
""",
            }
        ) + "\n"
