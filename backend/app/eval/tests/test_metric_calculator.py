from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    EvidenceItem,
    QueryRequirement,
    ReportQualityScores,
    ReportSection,
)
from app.eval.metric_calculator import MetricCalculator
from app.eval.types import EvalCase, EvalContext


def make_ctx() -> EvalContext:
    return EvalContext(
        case=EvalCase(
            id="q1",
            query="Analyze market size and risks",
            category="auto",
            difficulty="easy",
        ),
        state={
            "outline": [{"id": "s1", "title": "Market"}, {"id": "s2", "title": "Risks"}],
            "logs": [{"tokens_used": 1000, "model": "qwen-max"}],
            "critic_feedback": [{"id": "cf1", "resolved": True}],
        },
        started_at=datetime(2026, 5, 31, 10, 0),
        finished_at=datetime(2026, 5, 31, 10, 5),
    )


def make_evidence(id: str, text: str = "Market size grew.") -> EvidenceItem:
    return EvidenceItem(
        id=id,
        text=text,
        source_name="Example",
        source_url=f"https://example.com/{id}",
        source_type="web",
    )


def test_metric_calculator_computes_claim_metrics():
    artifact = EvalArtifact(
        evidence=[make_evidence("ref_1")],
        sections=[
            ReportSection("s1", "Market", "Text", ["1"]),
            ReportSection("s2", "Risks", "Text", []),
        ],
        requirements=[
            QueryRequirement("r1", "market size", "high"),
            QueryRequirement("r2", "risks", "high"),
        ],
        claims=[
            AtomicClaim("c1", "Market size grew.", "s1", "high", ["1"], ["r1"]),
            AtomicClaim("c2", "Risk is low.", "s2", "high", [], ["r2"]),
        ],
        verdicts=[
            ClaimVerdict("c1", True, reason="supported", evidence_ids=["ref_1"]),
            ClaimVerdict("c2", False, reason="missing evidence"),
        ],
        quality=ReportQualityScores(coherence=8.0, cohesion_structure=7.0),
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    scores = {r.evaluator_name: r.score for r in results}

    assert scores["claim_support_rate"] == 5.0
    assert scores["citation_verifiability"] == pytest.approx(10.0)
    assert scores["relevance_coverage"] == 10.0
    assert scores["completeness"] == 5.0
    assert scores["coherence"] == 8.0
    assert scores["cohesion_structure"] == 7.0
    assert scores["analytical_depth"] is None
    assert scores["professionalism_readability"] is None
    assert scores["decision_usefulness"] is None
    assert scores["critic_loop"] == 10.0
    assert scores["critic_loop_effectiveness"] == 10.0
    assert scores["cost"] is not None
    assert scores["latency"] == 300.0

    by_name = {r.evaluator_name: r for r in results}
    assert by_name["critic_loop"].metadata == by_name["critic_loop_effectiveness"].metadata
    assert by_name["critic_loop"].error == by_name["critic_loop_effectiveness"].error


def test_metric_calculator_records_artifact_errors():
    artifact = EvalArtifact(errors=["claim_extraction: bad json"])
    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["claim_support_rate"].score is None
    assert "claim_extraction" in by_name["claim_support_rate"].error


def test_report_quality_error_does_not_suppress_claim_metrics():
    artifact = EvalArtifact(
        evidence=[make_evidence("ref_1")],
        requirements=[QueryRequirement("r1", "market size", "high")],
        claims=[AtomicClaim("c1", "Market size grew.", "s1", "high", ["1"], ["r1"])],
        verdicts=[
            ClaimVerdict("c1", True, reason="supported", evidence_ids=["ref_1"]),
        ],
        quality=ReportQualityScores(error="judge timeout", partial=True),
        errors=["report_quality: judge timeout"],
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["claim_support_rate"].score == 10.0
    assert by_name["citation_verifiability"].score == pytest.approx(10.0)
    assert by_name["relevance_coverage"].score == 10.0
    assert by_name["completeness"].score == 10.0


def test_missing_quality_dimensions_return_errors():
    artifact = EvalArtifact(quality=ReportQualityScores(coherence=8.0))
    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["coherence"].score == 8.0
    assert by_name["analytical_depth"].score is None
    assert "missing quality score" in by_name["analytical_depth"].error


def test_malformed_none_artifact_fields_do_not_abort_metrics():
    artifact = EvalArtifact(
        evidence=[make_evidence("ref_1")],
        requirements=[QueryRequirement("r1", "market size", None)],
        claims=[AtomicClaim("c1", "Market size grew.", "s1", "high", None, None)],
        verdicts=[ClaimVerdict("c1", True, reason="supported", evidence_ids=None)],
        quality=ReportQualityScores(
            coherence=8.0,
            raw_judge_outputs=None,
            std_by_dimension=None,
            low_confidence_dimensions=None,
        ),
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["claim_support_rate"].score == 10.0
    assert by_name["citation_verifiability"].score is None
    assert "no cited claims" in by_name["citation_verifiability"].error
    assert by_name["relevance_coverage"].score == 0.0
    assert by_name["completeness"].score == 0.0
    assert by_name["coherence"].score == 8.0
    assert by_name["coherence"].raw_judge_outputs == []
    assert by_name["coherence"].metadata["std"] is None


def test_malformed_metric_failure_does_not_abort_other_metrics():
    artifact = EvalArtifact(
        evidence=[make_evidence("ref_1")],
        requirements=[QueryRequirement("r1", "market size", "high")],
        claims=[AtomicClaim("c1", "Market size grew.", "s1", "high", 5, ["r1"])],
        verdicts=[ClaimVerdict("c1", True, reason="supported", evidence_ids=["ref_1"])],
        quality=ReportQualityScores(coherence=8.0),
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["claim_support_rate"].score == 10.0
    assert by_name["citation_verifiability"].score is None
    assert "citation_verifiability" in by_name["citation_verifiability"].error
    assert by_name["relevance_coverage"].score == 10.0
    assert by_name["completeness"].score == 10.0
    assert by_name["coherence"].score == 8.0


def test_citation_verifiability_normalizes_ids_and_uses_overlap():
    artifact = EvalArtifact(
        evidence=[make_evidence("ref_1"), make_evidence("ref_2")],
        claims=[
            AtomicClaim(
                "c1",
                "Supported with partial overlap.",
                "s1",
                "high",
                ["1", "ref-2"],
                [],
            ),
            AtomicClaim("c2", "Unsupported unknown citation.", "s1", "high", ["3"], []),
        ],
        verdicts=[
            ClaimVerdict("c1", True, reason="supported", evidence_ids=["ref_1"]),
            ClaimVerdict("c2", False, reason="not supported", evidence_ids=[]),
        ],
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["citation_verifiability"].score == pytest.approx(5.56)
    assert by_name["citation_verifiability"].metadata[
        "known_citation_rate"
    ] == pytest.approx(2 / 3)
    assert by_name["citation_verifiability"].metadata["supported_cited_claim_rate"] == 0.5
    assert by_name["citation_verifiability"].metadata[
        "citation_evidence_overlap_rate"
    ] == 0.5


def test_no_claims_or_requirements_fail_softly():
    artifact = EvalArtifact()
    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}

    assert by_name["claim_support_rate"].score is None
    assert "no applicable claims" in by_name["claim_support_rate"].error
    assert by_name["citation_verifiability"].score is None
    assert "no cited claims" in by_name["citation_verifiability"].error
    assert by_name["relevance_coverage"].score is None
    assert "no requirements" in by_name["relevance_coverage"].error
    assert by_name["completeness"].score is None
    assert "no applicable requirements" in by_name["completeness"].error
