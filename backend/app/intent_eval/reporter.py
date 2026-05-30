"""生成 markdown 报表 + JSON 存档。

设计：纯函数，从 RunSummary + list[CaseResult] 渲染成单个 markdown 文件。
"""
import json
from pathlib import Path
from app.intent_eval.types import (
    CaseResult, LevelMetrics, RunSummary,
    INTENT_CLASSES, RESEARCH_TYPE_CLASSES, ERROR_LABEL,
)


def _escape_pipe(text: str) -> str:
    return text.replace("|", "\\|")


def _truncate(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _render_per_class_table(metrics: LevelMetrics, classes: list[str]) -> list[str]:
    lines = ["| Class | Support | Precision | Recall | F1 |",
             "|---|---:|---:|---:|---:|"]
    for c in classes:
        m = metrics.per_class[c]
        lines.append(f"| {c} | {m.support} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} |")
    return lines


def _render_confusion_matrix(metrics: LevelMetrics, classes: list[str]) -> list[str]:
    has_error_col = any(metrics.confusion.get(t, {}).get(ERROR_LABEL, 0) > 0 for t in classes)
    cols = list(classes) + ([ERROR_LABEL] if has_error_col else [])
    header = "| true \\\\ pred | " + " | ".join(cols) + " |"
    sep = "|---|" + "|".join(["---:"] * len(cols)) + "|"
    lines = [header, sep]
    for t in classes:
        row_vals = []
        for c in cols:
            v = metrics.confusion.get(t, {}).get(c, 0)
            cell = f"**{v}**" if t == c else str(v)
            row_vals.append(cell)
        lines.append(f"| {t} | " + " | ".join(row_vals) + " |")
    return lines


def _render_badcases(case_results: list[CaseResult], for_level: int) -> list[str]:
    if for_level == 1:
        bad = [cr for cr in case_results if not cr.intent_correct]
        if not bad:
            return ["(no Level 1 errors)"]
        bad.sort(key=lambda cr: (not cr.case.is_boundary, cr.case.id))
        lines = ["| id | query | true | predicted | subtype | boundary |",
                 "|---|---|---|---|---|---|"]
        for cr in bad:
            lines.append(
                f"| {cr.case.id} | {_escape_pipe(_truncate(cr.case.query))} "
                f"| {cr.case.true_intent} | {cr.predicted_intent or ERROR_LABEL} "
                f"| {_escape_pipe(cr.case.subtype)} | {'✓' if cr.case.is_boundary else '✗'} |"
            )
        return lines
    # Level 2
    bad = [cr for cr in case_results
           if cr.case.true_research_type is not None and cr.research_type_correct is False]
    if not bad:
        return ["(no Level 2 errors)"]
    bad.sort(key=lambda cr: (not cr.case.is_boundary, cr.case.id))
    lines = ["| id | query | true | predicted | subtype |",
             "|---|---|---|---|---|"]
    for cr in bad:
        lines.append(
            f"| {cr.case.id} | {_escape_pipe(_truncate(cr.case.query))} "
            f"| {cr.case.true_research_type} | {cr.predicted_research_type or ERROR_LABEL} "
            f"| {_escape_pipe(cr.case.subtype)} |"
        )
    return lines


def write_markdown(
    summary: RunSummary, case_results: list[CaseResult], output_dir: Path
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = summary.finished_at.replace(":", "-")
    filename = f"{safe_ts}-{summary.git_commit[:7]}.md"
    out_path = output_dir / filename

    lines: list[str] = []
    lines.append(f"# Intent Eval Report — {summary.finished_at} @ {summary.git_commit[:7]}")
    lines.append("")
    lines.append(f"- Dataset version: {summary.dataset_version}")
    lines.append(f"- Level 1 model: {summary.level1_model}")
    lines.append(f"- Level 2 model: {summary.level2_model}")
    lines.append(f"- Duration: {summary.duration_sec:.1f} sec")
    lines.append(f"- Concurrency: {summary.concurrency}")
    lines.append("")

    # Level 1
    l1 = summary.level1
    lines.append("## Level 1: Intent Classification")
    lines.append("")
    lines.append(f"**Overall Accuracy: {round(l1.accuracy * l1.n)}/{l1.n} = "
                 f"{l1.accuracy * 100:.1f}%   Macro F1: {l1.macro_f1:.3f}**")
    lines.append("")
    lines.append("### Per-class")
    lines.extend(_render_per_class_table(l1, INTENT_CLASSES))
    lines.append("")
    lines.append("### Confusion Matrix (rows=true, cols=pred)")
    lines.extend(_render_confusion_matrix(l1, INTENT_CLASSES))
    lines.append("")

    # Level 2
    l2 = summary.level2
    lines.append(f"## Level 2: Research Type Classification (deep_research subset, n={l2.n})")
    lines.append("")
    lines.append(f"**Overall Accuracy: {round(l2.accuracy * l2.n)}/{l2.n} = "
                 f"{l2.accuracy * 100:.1f}%   Macro F1: {l2.macro_f1:.3f}**")
    lines.append("")
    lines.append("### Per-class")
    lines.extend(_render_per_class_table(l2, RESEARCH_TYPE_CLASSES))
    lines.append("")
    lines.append("### Confusion Matrix")
    lines.extend(_render_confusion_matrix(l2, RESEARCH_TYPE_CLASSES))
    lines.append("")

    # Badcases
    lines.append("## Badcases")
    lines.append("")
    lines.append("### Level 1 errors")
    lines.extend(_render_badcases(case_results, for_level=1))
    lines.append("")
    lines.append("### Level 2 errors")
    lines.extend(_render_badcases(case_results, for_level=2))
    lines.append("")

    # Metadata
    lines.append("## Run Metadata")
    lines.append("")
    meta = {
        "run_id": summary.run_id,
        "git_commit": summary.git_commit,
        "dataset_version": summary.dataset_version,
        "level1_model": summary.level1_model,
        "level2_model": summary.level2_model,
        "started_at": summary.started_at,
        "finished_at": summary.finished_at,
        "concurrency": summary.concurrency,
        "duration_sec": summary.duration_sec,
    }
    lines.append("```json")
    lines.append(json.dumps(meta, ensure_ascii=False, indent=2))
    lines.append("```")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
