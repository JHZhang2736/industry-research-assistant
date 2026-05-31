"""Test Reporter markdown + csv generation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvalArtifact
from app.eval.reporter import Reporter
from app.eval.types import CaseResult, EvalCase, EvalResult


def make_case_result(case_id: str, scores: dict[str, float], ok: bool = True, error=None) -> CaseResult:
    return CaseResult(
        case=EvalCase(id=case_id, query=f"q-{case_id}", category="汽车", difficulty="easy"),
        results=[
            EvalResult(evaluator_name=name, score=s) for name, s in scores.items()
        ],
        ok=ok,
        error=error,
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 5),
    )


def test_reporter_writes_markdown(tmp_path: Path):
    out_dir = tmp_path / "results"
    cases = [
        make_case_result("q001", {"relevance": 8.0, "cost": 0.34}),
        make_case_result("q002", {"relevance": 7.5, "cost": 0.41}),
    ]
    r = Reporter(out_dir=str(out_dir))
    paths = r.write(
        run_id="run-001",
        suite="full",
        git_commit="abc1234",
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 30),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "run-001" in md
    assert "abc1234" in md
    assert "## Overall Scores" in md
    assert "relevance" in md
    csv_path = Path(paths["csv"])
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "q001" in csv_text and "q002" in csv_text


def test_reporter_marks_failed_cases(tmp_path: Path):
    cases = [
        make_case_result("q001", {"relevance": 7.0}),
        make_case_result("q002", {}, ok=False, error="TimeoutError"),
    ]
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-2",
        suite="mini",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Failed Cases" in md
    assert "q002" in md
    assert "TimeoutError" in md


def test_reporter_escapes_pipe_in_query(tmp_path: Path):
    cases = [
        make_case_result("q001", {"relevance": 7.0}),
    ]
    # Override query to contain a pipe
    cases[0].case = EvalCase(id="q001", query="A | B sector", category="x", difficulty="easy")
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-pipe",
        suite="t",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "A \\| B sector" in md  # escaped pipe


def test_reporter_groups_claim_centered_scores(tmp_path: Path):
    cases = [
        make_case_result(
            "q001",
            {
                "claim_support_rate": 5.0,
                "coherence": 8.0,
                "decision_usefulness": 7.0,
                "cost": 0.34,
            },
        ),
    ]
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-groups",
        suite="full",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=cases,
        langsmith_url=None,
    )

    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Score Groups" in md
    assert "### Information Fidelity" in md
    assert "claim_support_rate" in md
    assert "### Report Quality" in md
    assert "coherence" in md
    assert "decision_usefulness" in md
    assert "### Agentic / Operational" in md
    assert "cost" in md


def test_reporter_includes_claim_diagnostics(tmp_path: Path):
    case = make_case_result("q001", {"claim_support_rate": 5.0, "coherence": 8.0})
    case.artifact = EvalArtifact(
        claims=[
            AtomicClaim(
                id="c1",
                text="Unsupported market claim.",
                section_id="s1",
                importance="high",
                citation_ids=["1"],
            ),
            AtomicClaim(
                id="c2",
                text="Supported claim.",
                section_id="s1",
                importance="medium",
                citation_ids=["2"],
            ),
        ],
        verdicts=[
            ClaimVerdict(
                claim_id="c1",
                supported=False,
                reason="No matching evidence.",
                evidence_ids=[],
            ),
            ClaimVerdict(
                claim_id="c2",
                supported=True,
                reason="Supported.",
                evidence_ids=["f1"],
            ),
        ],
        errors=[],
    )
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-claim",
        suite="full",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=[case],
        langsmith_url=None,
    )

    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Claim Diagnostics" in md
    assert "Unsupported market claim." in md
    assert "No matching evidence." in md
    assert "Supported claim." not in md
