"""Test CitationEvaluator. URL check is mocked via aresponses."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.citation import CitationEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(report: str, refs: list[dict]) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={
            "final_report": report,
            "references": refs,
            "outline": [{"id": "s1", "title": "A"}, {"id": "s2", "title": "B"}],
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_citation_full_match_high_score(aresponses):
    aresponses.add("example.com", "/a", "HEAD", aresponses.Response(status=200))
    aresponses.add("example.com", "/b", "HEAD", aresponses.Response(status=200))

    report = "段落 [1] 内容\n段落 [2] 内容"
    refs = [
        {"id": "1", "url": "https://example.com/a", "title": "A"},
        {"id": "2", "url": "https://example.com/b", "title": "B"},
    ]
    ev = CitationEvaluator()
    res = await ev.evaluate(make_ctx(report, refs), judge=None)
    assert res.score >= 8.0
    assert res.metadata["broken_urls"] == 0
    assert res.metadata["unknown_ref_ids"] == []


@pytest.mark.asyncio
async def test_citation_broken_url_penalty(aresponses):
    aresponses.add("example.com", "/dead", "HEAD", aresponses.Response(status=404))

    report = "段落 [1] 内容"
    refs = [{"id": "1", "url": "https://example.com/dead", "title": "X"}]
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert res.metadata["broken_urls"] == 1
    assert res.score < 8.0


@pytest.mark.asyncio
async def test_citation_unknown_ref_id_penalty(aresponses):
    aresponses.add("example.com", "/a", "HEAD", aresponses.Response(status=200))

    # report cites [2] but references only has [1]
    report = "段落 [2] 内容"
    refs = [{"id": "1", "url": "https://example.com/a", "title": "A"}]
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert "2" in res.metadata["unknown_ref_ids"]
    assert res.score < 8.0


@pytest.mark.asyncio
async def test_citation_no_citations_low_score():
    report = "段落内容，无任何引用编号"
    refs = []
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert res.score <= 3.0
    assert res.metadata["citation_count"] == 0
