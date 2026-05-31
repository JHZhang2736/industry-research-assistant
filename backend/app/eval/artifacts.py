"""Claim-centered eval artifact dataclasses."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
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
    error: str | None = None


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


def _coerce_dataclass(cls: type, value: Any) -> Any:
    if isinstance(value, cls):
        return value
    if value is None:
        return cls()
    field_names = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in value.items() if key in field_names})


def _coerce_dataclass_list(cls: type, values: Any) -> list[Any]:
    if values is None:
        return []
    return [_coerce_dataclass(cls, item) for item in values]


def artifact_from_dict(payload: dict[str, Any] | EvalArtifact | None) -> EvalArtifact:
    if isinstance(payload, EvalArtifact):
        return payload
    if payload is None:
        payload = {}

    return EvalArtifact(
        evidence=_coerce_dataclass_list(EvidenceItem, payload.get("evidence")),
        sections=_coerce_dataclass_list(ReportSection, payload.get("sections")),
        requirements=_coerce_dataclass_list(
            QueryRequirement, payload.get("requirements")
        ),
        claims=_coerce_dataclass_list(AtomicClaim, payload.get("claims")),
        verdicts=_coerce_dataclass_list(ClaimVerdict, payload.get("verdicts")),
        quality=_coerce_dataclass(ReportQualityScores, payload.get("quality")),
        errors=list(payload.get("errors") or []),
    )
