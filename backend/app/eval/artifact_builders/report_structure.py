"""Build report structure artifacts from Markdown reports."""
from __future__ import annotations

import re

from app.eval.artifacts import ReportSection
from app.eval.settings import REPORT_CHARS

REFERENCE_TITLES = {"references", "参考文献", "引用", "来源"}
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
CITATION_RE = re.compile(r"\[([0-9][0-9,\-\s]*)\]")


def extract_citation_ids(text: str) -> list[str]:
    citation_ids: list[str] = []
    seen: set[str] = set()

    for match in CITATION_RE.finditer(text):
        for part in match.group(1).split(","):
            part = part.strip()
            range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                if start <= end:
                    for value in range(start, end + 1):
                        _append_unique(citation_ids, seen, str(value))
                continue
            if part.isdigit():
                _append_unique(citation_ids, seen, part)

    return citation_ids


def strip_reference_section(report: str) -> str:
    for match in HEADING_RE.finditer(report):
        title = _normalize_heading_title(match.group(2))
        if title in REFERENCE_TITLES:
            return report[: match.start()].rstrip()
    return report


def parse_report_sections(report: str) -> list[ReportSection]:
    body = strip_reference_section(report[:REPORT_CHARS]).strip()
    if not body:
        return []

    headings = list(HEADING_RE.finditer(body))
    if not headings:
        return [
            ReportSection(
                id="s1",
                title="Report",
                text=body,
                citation_ids=extract_citation_ids(body),
            )
        ]

    sections: list[ReportSection] = []
    for index, heading in enumerate(headings, start=1):
        next_start = headings[index].start() if index < len(headings) else len(body)
        text = body[heading.end() : next_start].strip()
        sections.append(
            ReportSection(
                id=f"s{index}",
                title=heading.group(2).strip(),
                text=text,
                citation_ids=extract_citation_ids(text),
            )
        )
    return sections


def _append_unique(items: list[str], seen: set[str], value: str) -> None:
    if value in seen:
        return
    seen.add(value)
    items.append(value)


def _normalize_heading_title(title: str) -> str:
    return title.strip().strip(":：").casefold()
