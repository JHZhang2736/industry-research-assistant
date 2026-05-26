"""Citation evaluator: rule-based scoring of (1) ref id integrity (2) URL reachability (3) coverage."""
from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

from app.eval.evaluators.base import Evaluator
from app.eval.settings import URL_CHECK_TIMEOUT_SEC
from app.eval.types import EvalContext, EvalResult

logger = logging.getLogger("eval.citation")

# [1], [2], [1,3], [1-3]
_CITATION_PATTERN = re.compile(r"\[(\d+(?:[,\-]\d+)*)\]")


def _extract_cited_ids(report: str) -> list[str]:
    cited: list[str] = []
    for m in _CITATION_PATTERN.finditer(report):
        token = m.group(1)
        # support [1,2] and [1-3]
        if "-" in token:
            a, b = token.split("-", 1)
            try:
                for i in range(int(a), int(b) + 1):
                    cited.append(str(i))
            except ValueError:
                pass
        else:
            cited.extend([p.strip() for p in token.split(",")])
    return cited


async def _check_url(session: aiohttp.ClientSession, url: str) -> int | None:
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=URL_CHECK_TIMEOUT_SEC),
        ) as r:
            return r.status
    except Exception as e:
        logger.debug(f"url check failed for {url}: {e}")
        return None


class CitationEvaluator(Evaluator):
    name = "citation"
    scale = (0, 10)
    requires_judge = False
    requires_network = True

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        report = ctx.state.get("final_report") or ""
        refs: list[dict] = ctx.state.get("references") or []
        outline: list[dict] = ctx.state.get("outline") or []

        ref_ids = {str(r.get("id")) for r in refs if r.get("id") is not None}
        cited = _extract_cited_ids(report)
        citation_count = len(cited)

        unknown_ref_ids = sorted(set(cited) - ref_ids)

        # URL reachability
        urls = [r.get("url") for r in refs if r.get("url")]
        broken = 0
        if urls:
            async with aiohttp.ClientSession() as session:
                statuses = await asyncio.gather(
                    *[_check_url(session, u) for u in urls],
                    return_exceptions=True,
                )
            broken = sum(1 for s in statuses if not (isinstance(s, int) and 200 <= s < 400))

        # Coverage: citations per outline section (rough proxy)
        section_count = max(len(outline), 1)
        coverage_ratio = min(citation_count / section_count, 2.0) / 2.0  # cap at 100%

        # Compose score (0-10)
        if citation_count == 0:
            score = 1.0  # report with zero citations is bad
        else:
            url_ok_ratio = (len(urls) - broken) / max(len(urls), 1)
            unknown_ratio = len(unknown_ref_ids) / max(citation_count, 1)
            score = (
                4.0 * url_ok_ratio
                + 3.0 * (1 - unknown_ratio)
                + 3.0 * coverage_ratio
            )
            score = max(0.0, min(10.0, score))

        return EvalResult(
            evaluator_name=self.name,
            score=round(score, 2),
            metadata={
                "citation_count": citation_count,
                "ref_count": len(refs),
                "broken_urls": broken,
                "unknown_ref_ids": unknown_ref_ids,
                "coverage_ratio": round(coverage_ratio, 3),
            },
        )
