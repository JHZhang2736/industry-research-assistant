"""Claim-centered eval artifact dataclasses."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    id: str
    text: str
    source_name: str
    source_url: str
    source_type: str
    credibility_score: float | None = None


@dataclass
class ReportSection:
    id: str
    title: str
    text: str
    citation_ids: list[str] = field(default_factory=list)


@dataclass
class QueryRequirement:
    id: str
    text: str
    importance: str


@dataclass
class AtomicClaim:
    id: str
    text: str
    section_id: str
    importance: str
    citation_ids: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)


@dataclass
class ClaimVerdict:
    claim_id: str
    supported: bool
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str | None = None


@dataclass
class ReportQualityScores:
    coherence: float | None = None
    cohesion_structure: float | None = None
    analytical_depth: float | None = None
    professionalism_readability: float | None = None
    decision_usefulness: float | None = None
    raw_judge_outputs: list[dict[str, Any]] = field(default_factory=list)
    std_by_dimension: dict[str, float] = field(default_factory=dict)
    low_confidence_dimensions: list[str] = field(default_factory=list)
    partial: bool = False


@dataclass
class EvalArtifact:
    evidence: list[EvidenceItem] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    requirements: list[QueryRequirement] = field(default_factory=list)
    claims: list[AtomicClaim] = field(default_factory=list)
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    quality: ReportQualityScores = field(default_factory=ReportQualityScores)
    errors: list[str] = field(default_factory=list)


def artifact_to_dict(artifact: EvalArtifact) -> dict[str, Any]:
    return asdict(artifact)


def artifact_from_dict(payload: dict[str, Any]) -> EvalArtifact:
    return EvalArtifact(
        evidence=[EvidenceItem(**item) for item in payload.get("evidence", [])],
        sections=[ReportSection(**item) for item in payload.get("sections", [])],
        requirements=[
            QueryRequirement(**item) for item in payload.get("requirements", [])
        ],
        claims=[AtomicClaim(**item) for item in payload.get("claims", [])],
        verdicts=[ClaimVerdict(**item) for item in payload.get("verdicts", [])],
        quality=ReportQualityScores(**payload.get("quality", {})),
        errors=list(payload.get("errors", [])),
    )
