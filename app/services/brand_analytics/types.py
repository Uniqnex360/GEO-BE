from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, Field


class Weights:
    """Weighted contribution of each dimension to the overall score (sums to 1.0)."""

    MENTION = 0.20
    CITATION = 0.20
    SHARE_OF_VOICE = 0.15
    PRODUCT_COVERAGE = 0.15
    CATEGORY_COVERAGE = 0.10
    KNOWLEDGE_GRAPH = 0.10
    AUTHORITY = 0.05
    SENTIMENT = 0.05


SENTIMENT_SCALE = {"positive": 100, "mixed": 60, "neutral": 50, "negative": 0}

RECOMMENDATION_THRESHOLD = 70.0


class BrandInput(BaseModel):
    """User-supplied input describing the brand to analyze."""

    brand_name: str
    country: str
    website: str
    extra_context: Optional[str] = ""

    @field_validator("website")
    @classmethod
    def _normalize_website(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("http"):
            v = "https://" + v
        return v.rstrip("/")

    @property
    def domain(self) -> str:
        return urlparse(self.website).netloc.replace("www.", "")


class BrandProfile(BaseModel):
    """LLM-inferred profile driving every downstream dynamic query."""

    industry: str
    product_categories: List[str] = Field(min_length=3, max_length=5)
    competitors: List[str] = Field(min_length=2, max_length=4)
    prompts: List[str] = Field(
        min_length=5,
        max_length=6,
        description="5-6 open shopping/recommendation prompts (no brand names)",
    )


class PromptBatteryItem(BaseModel):
    """One prompt answered + judged in a single batched call."""

    prompt: str
    answer: str = Field(description="2-3 sentence answer naming real brands")
    mentioned: bool
    rank: Optional[int] = Field(
        default=None, description="Position in a ranked list, else null"
    )
    cited_official_site: bool = False
    sentiment: str = Field(
        default="neutral", description="positive | neutral | negative | mixed"
    )


class PromptBatteryResult(BaseModel):
    """All prompt answers + judgements in one structured response."""

    results: List[PromptBatteryItem] = Field(min_length=1, max_length=6)


class PromptResult(BaseModel):
    prompt: str
    raw_response: str
    mentioned: bool
    rank: Optional[int] = None
    cited_official_site: bool = False
    sentiment: str = "neutral"


class KnowledgeGraphResult(BaseModel):
    """What an AI knows about the brand, scored in one call."""

    summary: str = Field(description="3-5 sentence factual brand summary")
    richness_score: float = Field(ge=0, le=100)
    covers_history: bool
    covers_products: bool
    covers_industry: bool
    covers_country: bool


class Recommendation(BaseModel):
    """A concrete, ready-to-use recommendation — not just an action label."""

    dimension: str = Field(
        description="Which weak dimension this recommendation targets"
    )
    what_to_do: str = Field(
        description="Short label for the action, e.g. 'Rewrite About Us page'"
    )
    why_it_helps: str = Field(
        description="One sentence tying this to the specific weak score"
    )
    suggested_content: str = Field(
        description="Concrete draft: short bullets, schema fields, or 2-3 FAQ Q&As. Keep under 120 words."
    )


class DiagnosisFactor(BaseModel):
    """One evidence-grounded root cause behind limited visibility."""

    dimension: str = Field(description="Which dimension this factor explains")
    finding: str = Field(description="What the evidence showed, one sentence")
    root_cause: str = Field(description="Likely underlying reason, one sentence")


class VisibilityDiagnosis(BaseModel):
    """Explains *why* overall visibility is limited, grounded in the run's own evidence."""

    summary: str = Field(description="1-2 sentence plain-language explanation of the overall gap")
    factors: List[DiagnosisFactor] = Field(default_factory=list, max_length=5)


class DiagnosisAndRecommendations(BaseModel):
    """Diagnosis + recommendations in a single LLM response."""

    summary: str = Field(description="1-2 sentence overall visibility gap explanation")
    factors: List[DiagnosisFactor] = Field(default_factory=list, max_length=5)
    recommendations: List[Recommendation] = Field(default_factory=list, max_length=5)


class DimensionScore(BaseModel):
    name: str
    raw_value: float  # 0-100 metric before weighting
    weight: float
    weighted_score: float


class BrandVisibilityReport(BaseModel):
    brand: str
    country: str
    website: str
    industry: str
    overall_score: float
    sentiment: str
    dimensions: List[DimensionScore]
    diagnosis: VisibilityDiagnosis
    recommendations: List[Recommendation]
    raw_responses: Dict[str, Any]

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
