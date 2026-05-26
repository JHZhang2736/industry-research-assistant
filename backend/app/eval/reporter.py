"""Markdown + CSV reporter."""
from __future__ import annotations

import csv
import statistics
from datetime import datetime
from pathlib import Path

from app.eval.types import CaseResult


class Reporter:
    def __init__(self, out_dir: str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        run_id: str,
        suite: str,
        git_commit: str,
        started_at: datetime,
        finished_at: datetime,
        case_results: list[CaseResult],
        langsmith_url: str | None,
    ) -> dict[str, str]:
        md_path = self.out_dir / f"{started_at:%Y-%m-%d}-{suite}-{run_id}.md"
        csv_path = self.out_dir / f"{started_at:%Y-%m-%d}-{suite}-{run_id}.csv"

        md_path.write_text(self._render_md(
            run_id, suite, git_commit, started_at, finished_at, case_results, langsmith_url
        ), encoding="utf-8")
        self._write_csv(csv_path, case_results)
        return {"markdown": str(md_path), "csv": str(csv_path)}

    def _render_md(
        self,
        run_id, suite, git_commit, started_at, finished_at, case_results, langsmith_url,
    ) -> str:
        total = len(case_results)
        failed = [c for c in case_results if not c.ok]
        ok_cases = [c for c in case_results if c.ok]
        duration = (finished_at - started_at).total_seconds()

        # Aggregate by evaluator
        evaluator_names = sorted({
            r.evaluator_name for c in ok_cases for r in c.results
        })
        rows = []
        for name in evaluator_names:
            scores = [
                r.score for c in ok_cases for r in c.results
                if r.evaluator_name == name and r.score is not None
            ]
            low_conf = sum(
                1 for c in ok_cases for r in c.results
                if r.evaluator_name == name and r.low_confidence
            )
            if scores:
                rows.append({
                    "name": name,
                    "mean": round(statistics.mean(scores), 2),
                    "median": round(statistics.median(scores), 2),
                    "std": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
                    "low_conf": low_conf,
                    "n": len(scores),
                })

        md = [
            f"# Eval Suite: {suite}",
            f"**Run ID**: `{run_id}`",
            f"**Commit**: `{git_commit}`",
            f"**Started**: {started_at:%Y-%m-%d %H:%M:%S}",
            f"**Duration**: {int(duration)}s",
            f"**Cases**: {total} total, {len(ok_cases)} ok, {len(failed)} failed",
            "",
            "## Overall Scores",
            "",
            "| Evaluator | Mean | Median | Std | Low-confidence | N |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            md.append(f"| {r['name']} | {r['mean']} | {r['median']} | {r['std']} | {r['low_conf']}/{r['n']} | {r['n']} |")
        md.append("")

        # Per-case breakdown
        md.append("## Per-case Breakdown")
        md.append("")
        md.append("| case_id | query | " + " | ".join(evaluator_names) + " |")
        md.append("|" + "---|" * (2 + len(evaluator_names)))
        for c in ok_cases:
            score_map = {r.evaluator_name: r.score for r in c.results}
            cells = " | ".join(
                f"{score_map.get(n):.2f}" if isinstance(score_map.get(n), (int, float)) else "-"
                for n in evaluator_names
            )
            q = c.case.query[:30] + ("…" if len(c.case.query) > 30 else "")
            q = q.replace("|", "\\|")
            md.append(f"| `{c.case.id}` | {q} | {cells} |")
        md.append("")

        # Low-confidence cases
        low_conf_rows = []
        for c in ok_cases:
            for r in c.results:
                if r.low_confidence:
                    individual = " / ".join(
                        f"{o.get('judge')}={o.get('score')}" for o in (r.raw_judge_outputs or [])
                    )
                    low_conf_rows.append(f"- `{c.case.id}` / **{r.evaluator_name}** std={r.metadata.get('std', '?'):.2f}: {individual}")
        if low_conf_rows:
            md.append("## Low-confidence Cases (judge variance high — manual review recommended)")
            md.append("")
            md.extend(low_conf_rows)
            md.append("")

        # Failed cases
        if failed:
            md.append("## Failed Cases")
            md.append("")
            for c in failed:
                md.append(f"- `{c.case.id}`: {c.error}")
            md.append("")

        # LangSmith
        if langsmith_url:
            md.append("## LangSmith Dashboard")
            md.append("")
            md.append(f"[{langsmith_url}]({langsmith_url})")

        return "\n".join(md)

    def _write_csv(self, path: Path, case_results: list[CaseResult]) -> None:
        evaluator_names = sorted({
            r.evaluator_name for c in case_results for r in c.results
        })
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["case_id", "query", "ok", "error"] + evaluator_names)
            for c in case_results:
                score_map = {r.evaluator_name: r.score for r in c.results}
                row = [c.case.id, c.case.query, c.ok, c.error or ""]
                for n in evaluator_names:
                    v = score_map.get(n)
                    row.append("" if v is None else v)
                w.writerow(row)
