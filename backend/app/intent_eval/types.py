"""Intent eval 框架的所有 dataclass + 类常量定义。"""
from dataclasses import dataclass
from typing import Optional, Literal

INTENT_CLASSES: list[str] = ["deep_research", "web_search", "simple_qa", "out_of_scope"]
RESEARCH_TYPE_CLASSES: list[str] = ["industry_analysis", "company_research", "comparative_analysis"]
ERROR_LABEL: str = "<error>"

Intent = Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
ResearchType = Literal["industry_analysis", "company_research", "comparative_analysis"]


@dataclass(frozen=True)
class EvalCase:
    id: str
    query: str
    true_intent: str
    true_research_type: Optional[str]
    subtype: str
    is_boundary: bool


@dataclass
class CaseResult:
    case: EvalCase
    predicted_intent: Optional[str]
    predicted_research_type: Optional[str]
    intent_confidence: float
    research_type_confidence: Optional[float]
    intent_raw: dict
    research_type_raw: Optional[dict]
    latency_ms: int
    error: Optional[str]

    @property
    def intent_correct(self) -> bool:
        return self.predicted_intent == self.case.true_intent

    @property
    def research_type_correct(self) -> Optional[bool]:
        if self.case.true_research_type is None:
            return None
        return self.predicted_research_type == self.case.true_research_type


@dataclass
class PerClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class LevelMetrics:
    accuracy: float
    macro_f1: float
    per_class: dict[str, PerClassMetrics]
    confusion: dict[str, dict[str, int]]  # cm[true][pred] = count
    n: int


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str
    git_commit: str
    dataset_version: str
    level1_model: str
    level2_model: str
    concurrency: int
    duration_sec: float
    level1: LevelMetrics
    level2: LevelMetrics
