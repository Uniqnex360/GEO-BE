import asyncio
import re

from typing import Dict, Any, AsyncIterator, List
from collections import Counter
from urllib.parse import urlparse
from pydantic import BaseModel

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SerpAPIWrapper

from app.core.config import settings

from .types import (
    Weights,
    SENTIMENT_SCALE,
    RECOMMENDATION_THRESHOLD,
    BrandInput,
    BrandProfile,
    BrandVisibilityReport,
    PromptBatteryResult,
    PromptResult,
    KnowledgeGraphResult,
    DiagnosisAndRecommendations,
    Recommendation,
    VisibilityDiagnosis,
    DimensionScore,
)

# Cheap domain-authority heuristic — avoids an extra LLM call on SerpAPI results.
_TRUST_MARKERS = (
    ".gov",
    ".edu",
    ".ac.",
    "wikipedia.org",
    "bbc.",
    "reuters.",
    "nytimes.",
    "theguardian.",
    "forbes.",
    "bloomberg.",
    "wsj.",
    "ft.com",
    "nature.com",
    "ieee.org",
    "who.int",
    "techcrunch.",
    "wired.",
    "cnet.",
    "pcmag.",
    "consumerreports.",
)


def get_llm(provider: str) -> BaseChatModel:
    """Provider-agnostic LLM factory."""

    if provider == "openai":
        return ChatOpenAI(model="gpt-5-nano", temperature=0)

    elif provider == "anthropic":
        return ChatAnthropic(model="claude-haiku-4-5", temperature=0)

    elif provider == "google":
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    else:
        raise ValueError(f"Unsupported provider: {provider}")


class BrandVisibilityAnalyzer:
    """Runs the full 8-dimension brand visibility pipeline for one brand.

    Optimized for speed/tokens: ~3 LLM calls + 2 SerpAPI searches per run
    (was previously 30–40+ sequential LLM calls).
    """

    def __init__(
        self,
        brand_input: BrandInput,
        model: BaseChatModel,
        product_search_terms: int = 3,
    ) -> None:
        self.input = brand_input
        self.llm = model
        self.search = SerpAPIWrapper(serpapi_api_key=settings.SERPAPI_KEY)
        self.product_search_terms = product_search_terms
        self._raw: Dict[str, Any] = {}

    # -- generic DRY helpers -------------------------------------------------

    async def _ask_llm_text(self, system: str, user: str) -> str:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        response = await self.llm.ainvoke(messages)
        content = response.content
        if isinstance(content, list):
            return "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return content if isinstance(content, str) else str(content)

    async def _ask_llm_structured(
        self, model_cls: type[BaseModel], system: str, user: str
    ) -> BaseModel:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        chain = self.llm.with_structured_output(model_cls)
        return await chain.ainvoke(messages)

    async def _search(self, query: str) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.search.results, query)
        except Exception as exc:
            return {"error": str(exc), "query": query}

    @staticmethod
    def _pct(numerator: float, denominator: float) -> float:
        return round((numerator / denominator) * 100, 2) if denominator else 0.0

    def _brand_appears_in(self, search_payload: Dict[str, Any]) -> bool:
        organic = (
            search_payload.get("organic_results", [])
            if isinstance(search_payload, dict)
            else []
        )
        name_lower = self.input.brand_name.lower()
        domain_lower = self.input.domain.lower()
        for item in organic:
            haystack = " ".join(
                str(item.get(field, "")) for field in ("title", "snippet", "link")
            ).lower()
            if name_lower in haystack or domain_lower in haystack:
                return True
        return False

    @staticmethod
    def _is_trusted_domain(domain: str) -> bool:
        d = domain.lower()
        return any(marker in d for marker in _TRUST_MARKERS)

    @staticmethod
    def _status(message: str) -> Dict[str, Any]:
        return {"type": "status", "color": "green", "message": message}

    # -- step 0: profile + prompts in ONE call --------------------------------

    async def _infer_brand_profile(self) -> BrandProfile:
        system = "Market analyst. Be concise. Infer brand profile and shopping prompts."
        user = (
            f"Brand: {self.input.brand_name}\n"
            f"Country: {self.input.country}\n"
            f"Website: {self.input.website}\n"
            f"Extra: {self.input.extra_context or 'none'}\n\n"
            "Return: industry, 3-5 product categories, 2-4 competitors, and "
            "exactly 5-6 open shopping/recommendation prompts for this country "
            "(no brand names in prompts)."
        )
        profile = await self._ask_llm_structured(BrandProfile, system, user)
        self._raw["brand_profile"] = profile.model_dump()
        self._raw["generated_prompts"] = profile.prompts
        return profile  # type: ignore[return-value]

    # -- step 1: ALL prompts answered + judged in ONE call -------------------

    async def _run_prompt_battery(self, prompts: List[str]) -> List[PromptResult]:
        numbered = "\n".join(f"{i+1}. {p}" for i, p in enumerate(prompts))
        system = (
            "You are an AI shopping assistant. For EACH prompt: write a short 2-3 "
            "sentence answer naming real brands, then judge whether the target brand "
            "is mentioned, its rank if listed, whether its official site is cited, "
            "and sentiment toward it. Keep answers brief."
        )
        user = (
            f"Target brand: {self.input.brand_name} (site: {self.input.domain})\n"
            f"Country: {self.input.country}\n\n"
            f"Prompts:\n{numbered}\n\n"
            "Return one result object per prompt, in the same order."
        )
        battery: PromptBatteryResult = await self._ask_llm_structured(  # type: ignore[assignment]
            PromptBatteryResult, system, user
        )

        results: List[PromptResult] = []
        for i, item in enumerate(battery.results):
            prompt = prompts[i] if i < len(prompts) else item.prompt
            results.append(
                PromptResult(
                    prompt=prompt,
                    raw_response=item.answer,
                    mentioned=item.mentioned,
                    rank=item.rank,
                    cited_official_site=item.cited_official_site,
                    sentiment=item.sentiment,
                )
            )
        # If model returned fewer items than prompts, pad with not-mentioned
        for prompt in prompts[len(results) :]:
            results.append(
                PromptResult(
                    prompt=prompt,
                    raw_response="",
                    mentioned=False,
                    sentiment="neutral",
                )
            )

        self._raw["prompt_battery"] = [r.model_dump() for r in results]
        return results

    @staticmethod
    def _mention_score(results: List[PromptResult]) -> float:
        if not results:
            return 0.0
        mentioned = sum(1 for r in results if r.mentioned)
        return BrandVisibilityAnalyzer._pct(mentioned, len(results))

    @staticmethod
    def _citation_score(results: List[PromptResult]) -> float:
        mentioned = [r for r in results if r.mentioned]
        if not mentioned:
            return 0.0
        cited = sum(1 for r in mentioned if r.cited_official_site)
        return BrandVisibilityAnalyzer._pct(cited, len(mentioned))

    @staticmethod
    def _sentiment_score(results: List[PromptResult]) -> tuple[float, str]:
        mentioned = [r for r in results if r.mentioned]
        if not mentioned:
            return 0.0, "neutral"
        scores = [SENTIMENT_SCALE.get(r.sentiment.lower(), 50) for r in mentioned]
        avg = round(sum(scores) / len(scores), 2)
        majority = Counter(r.sentiment.lower() for r in mentioned).most_common(1)[0][0]
        return avg, majority

    # -- share of voice: free, derived from battery answers ------------------

    def _share_of_voice(
        self, profile: BrandProfile, prompt_results: List[PromptResult]
    ) -> Dict[str, Any]:
        all_brands = [self.input.brand_name] + profile.competitors
        combined = " ".join(r.raw_response for r in prompt_results)
        counts = {
            b: len(re.findall(re.escape(b), combined, flags=re.IGNORECASE))
            for b in all_brands
        }
        total = sum(counts.values())
        brand_mentions = counts.get(self.input.brand_name, 0)
        share_pct = self._pct(brand_mentions, total)
        payload = {
            "raw_response": combined,
            "mention_counts": counts,
            "total_mentions": total,
            "brand_mentions": brand_mentions,
            "share_pct": share_pct,
            "source": "prompt_battery",
        }
        self._raw["share_of_voice"] = payload
        return payload

    # -- product coverage: no LLM — search terms from categories -------------

    async def _product_coverage(self, profile: BrandProfile) -> Dict[str, Any]:
        combined_terms = [
            f"best {cat} {self.input.country}" for cat in profile.product_categories
        ][: self.product_search_terms]
        combined_query = " OR ".join(f'"{term}"' for term in combined_terms)
        search_payload = await self._search(combined_query)
        organic = (
            search_payload.get("organic_results", [])
            if isinstance(search_payload, dict)
            else []
        )

        hits = [
            item
            for item in organic
            if self._brand_appears_in({"organic_results": [item]})
        ]
        matched_terms = self._match_terms_to_hits(hits, combined_terms)

        payload = {
            "generated_queries": combined_terms,
            "combined_query_terms": combined_terms,
            "combined_query": combined_query,
            "brand_appeared": bool(hits),
            "matched_terms": matched_terms,
            "coverage_pct": 100.0 if hits else 0.0,
            "raw_search": search_payload,
        }
        self._raw["product_coverage"] = payload
        return payload

    @staticmethod
    def _match_terms_to_hits(hits: List[Dict[str, Any]], terms: List[str]) -> List[str]:
        matched = set()
        for item in hits:
            haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            for term in terms:
                keywords = [
                    w for w in re.findall(r"[a-z0-9]+", term.lower()) if len(w) > 3
                ]
                if keywords and any(kw in haystack for kw in keywords):
                    matched.add(term)
        return sorted(matched)

    # -- category coverage: free from battery --------------------------------

    def _category_coverage(
        self, profile: BrandProfile, prompt_results: List[PromptResult]
    ) -> Dict[str, Any]:
        visible = set()
        for category in profile.product_categories:
            for result in prompt_results:
                if category.lower() in result.prompt.lower() and result.mentioned:
                    visible.add(category)
                    break
        coverage_pct = self._pct(len(visible), len(profile.product_categories))
        payload = {
            "categories_checked": profile.product_categories,
            "categories_visible": sorted(visible),
            "coverage_pct": coverage_pct,
        }
        self._raw["category_coverage"] = payload
        return payload

    # -- knowledge graph: answer + score in ONE call -------------------------

    async def _knowledge_graph_score(self) -> Dict[str, Any]:
        system = "Score how richly an AI can describe this brand. Be concise."
        user = (
            f"Brand: {self.input.brand_name}\n"
            f"Expected country: {self.input.country}\n"
            f"Website: {self.input.website}\n\n"
            "Write a short factual summary, score richness 0-100, and flag whether "
            "history, products, industry, and country are each covered."
        )
        result: KnowledgeGraphResult = await self._ask_llm_structured(  # type: ignore[assignment]
            KnowledgeGraphResult, system, user
        )
        payload = {"raw_response": result.summary, **result.model_dump()}
        self._raw["knowledge_graph"] = payload
        return payload

    # -- authority: SerpAPI + heuristic (no LLM) -----------------------------

    async def _authority_score(self) -> Dict[str, Any]:
        results = await self._search(
            f'"{self.input.brand_name}" review OR mentioned OR profile'
        )
        organic = (
            results.get("organic_results", []) if isinstance(results, dict) else []
        )
        domains = sorted(
            {
                urlparse(item.get("link", "")).netloc
                for item in organic
                if item.get("link")
            }
        )
        trusted = [d for d in domains if self._is_trusted_domain(d)]
        payload = {
            "raw_search": results,
            "domains_found": domains,
            "trusted_domains": trusted,
            "trusted_citation_count": len(trusted),
            "results_checked": len(organic),
        }
        self._raw["authority"] = payload
        return payload

    # -- diagnosis + recommendations in ONE call -----------------------------

    async def _diagnose_and_recommend(
        self, profile: BrandProfile, dimensions: List[DimensionScore]
    ) -> tuple[VisibilityDiagnosis, List[Recommendation]]:
        weak_dimensions = [
            d for d in dimensions if d.raw_value < RECOMMENDATION_THRESHOLD
        ]
        if not weak_dimensions:
            diagnosis = VisibilityDiagnosis(
                summary="Visibility is strong across all measured dimensions — no significant gaps found.",
                factors=[],
            )
            self._raw["diagnosis"] = diagnosis.model_dump()
            return diagnosis, []

        evidence_by_dimension = {
            "mention": (
                f"Mentioned in {sum(1 for r in self._raw.get('prompt_battery', []) if r['mentioned'])}/"
                f"{len(self._raw.get('prompt_battery', []))} queries."
            ),
            "citation": (
                f"Official site cited in "
                f"{sum(1 for r in self._raw.get('prompt_battery', []) if r['mentioned'] and r['cited_official_site'])}/"
                f"{sum(1 for r in self._raw.get('prompt_battery', []) if r['mentioned'])} mentions."
            ),
            "share_of_voice": (
                "Mentions: "
                + ", ".join(
                    f"{b}:{c}"
                    for b, c in self._raw.get("share_of_voice", {})
                    .get("mention_counts", {})
                    .items()
                )
            ),
            "product_coverage": (
                f"Appeared={self._raw.get('product_coverage', {}).get('brand_appeared')}; "
                f"terms={self._raw.get('product_coverage', {}).get('combined_query_terms')}"
            ),
            "category_coverage": (
                f"Visible {self._raw.get('category_coverage', {}).get('categories_visible')} "
                f"of {self._raw.get('category_coverage', {}).get('categories_checked')}"
            ),
            "knowledge_graph": (
                f"history={self._raw.get('knowledge_graph', {}).get('covers_history')}, "
                f"products={self._raw.get('knowledge_graph', {}).get('covers_products')}, "
                f"industry={self._raw.get('knowledge_graph', {}).get('covers_industry')}, "
                f"country={self._raw.get('knowledge_graph', {}).get('covers_country')}"
            ),
            "authority": (
                f"Trusted={self._raw.get('authority', {}).get('trusted_citation_count')}/"
                f"{self._raw.get('authority', {}).get('results_checked')}"
            ),
            "sentiment": "See prompt battery sentiment distribution.",
        }

        evidence_block = "\n".join(
            f"- {d.name} ({d.raw_value}/100): {evidence_by_dimension.get(d.name, 'n/a')}"
            for d in weak_dimensions
        )
        knowledge_context = self._raw.get("knowledge_graph", {}).get("raw_response", "")

        system = (
            "Brand visibility analyst. Be concise. Use only given evidence. "
            "Diagnose gaps and give up to 5 concrete, short recommendations."
        )
        user = (
            f"Brand: {self.input.brand_name} | {self.input.country} | {self.input.website}\n"
            f"Industry: {profile.industry}\n"
            f"Categories: {', '.join(profile.product_categories)}\n"
            f"Known about brand: {knowledge_context or 'little'}\n\n"
            f"Weak dimensions:\n{evidence_block}\n\n"
            "Return: short summary, one factor per weak dimension, and up to 5 "
            "recommendations (dimension, action label, why, short suggested content)."
        )
        combined: DiagnosisAndRecommendations = await self._ask_llm_structured(  # type: ignore[assignment]
            DiagnosisAndRecommendations, system, user
        )
        diagnosis = VisibilityDiagnosis(
            summary=combined.summary, factors=combined.factors
        )
        self._raw["diagnosis"] = diagnosis.model_dump()
        return diagnosis, combined.recommendations

    # -- orchestration -----------------------------------------------------

    async def analyze_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """~3 LLM calls + 2 searches. Yields status events then final report."""

        yield self._status("Inferring brand profile + prompts...")
        profile = await self._infer_brand_profile()
        prompts = profile.prompts

        yield self._status(
            f"Running prompt battery ({len(prompts)} prompts, single call)..."
        )
        prompt_results = await self._run_prompt_battery(prompts)

        yield self._status(
            "Scoring mentions / citations / sentiment / share of voice..."
        )
        mention_val = self._mention_score(prompt_results)
        citation_val = self._citation_score(prompt_results)
        sentiment_val, sentiment_label = self._sentiment_score(prompt_results)
        sov = self._share_of_voice(profile, prompt_results)
        category_cov = self._category_coverage(profile, prompt_results)

        yield self._status("Running search + knowledge graph in parallel...")
        product_cov, knowledge, authority = await asyncio.gather(
            self._product_coverage(profile),
            self._knowledge_graph_score(),
            self._authority_score(),
        )
        authority_val = min(self._pct(authority["trusted_citation_count"], 5), 100.0)

        raw_dimension_values = {
            "mention": mention_val,
            "citation": citation_val,
            "share_of_voice": sov["share_pct"],
            "product_coverage": product_cov["coverage_pct"],
            "category_coverage": category_cov["coverage_pct"],
            "knowledge_graph": knowledge["richness_score"],
            "authority": authority_val,
            "sentiment": sentiment_val,
        }
        weight_map = {
            "mention": Weights.MENTION,
            "citation": Weights.CITATION,
            "share_of_voice": Weights.SHARE_OF_VOICE,
            "product_coverage": Weights.PRODUCT_COVERAGE,
            "category_coverage": Weights.CATEGORY_COVERAGE,
            "knowledge_graph": Weights.KNOWLEDGE_GRAPH,
            "authority": Weights.AUTHORITY,
            "sentiment": Weights.SENTIMENT,
        }

        dimensions = [
            DimensionScore(
                name=name,
                raw_value=value,
                weight=weight_map[name],
                weighted_score=round(value * weight_map[name], 2),
            )
            for name, value in raw_dimension_values.items()
        ]
        overall_score = round(sum(d.weighted_score for d in dimensions), 2)

        yield self._status("Diagnosing gaps + drafting recommendations...")
        diagnosis, recommendations = await self._diagnose_and_recommend(
            profile, dimensions
        )

        for recommendation in recommendations:
            yield {
                "type": "recommendation",
                "recommendation": recommendation if isinstance(recommendation, dict) else recommendation.model_dump()
            }

        report = BrandVisibilityReport(
            brand=self.input.brand_name,
            country=self.input.country,
            website=self.input.website,
            industry=profile.industry,
            overall_score=overall_score,
            sentiment=sentiment_label,
            dimensions=dimensions,
            diagnosis=diagnosis,
            recommendations=recommendations,
            raw_responses=self._raw,
        )
        yield {"type": "result", "report": report}

    async def analyze(self) -> BrandVisibilityReport:
        report = None
        async for event in self.analyze_stream():
            if event["type"] == "result":
                report = event["report"]
        if report is None:
            raise RuntimeError("analyze_stream() ended without producing a report")
        return report


async def run_brand_analytics(
    brand_name: str,
    country: str,
    website: str,
    extra_context: str,
    model: BaseChatModel,
) -> BrandVisibilityReport:
    brand_input = BrandInput(
        brand_name=brand_name,
        country=country,
        website=website,
        extra_context=extra_context,
    )
    analyzer = BrandVisibilityAnalyzer(brand_input, model)
    return await analyzer.analyze()
