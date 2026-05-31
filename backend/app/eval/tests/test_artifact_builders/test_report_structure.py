from app.eval.artifact_builders.report_structure import (
    extract_citation_ids,
    parse_report_sections,
)


def test_extract_citation_ids_handles_single_list_and_range():
    text = "Market grew [1], policy helped [2,3], and exports rose [4-6]."
    assert extract_citation_ids(text) == ["1", "2", "3", "4", "5", "6"]


def test_parse_report_sections_ignores_references():
    report = """
## Executive Summary
Summary claim [1].

## 1 Market Size
Sales increased [1,2].

### 1.1 Export
Exports grew [3].

## References
[1] Source A
[2] Source B
"""

    sections = parse_report_sections(report)

    assert [s.id for s in sections] == ["s1", "s2", "s3"]
    assert sections[0].title == "Executive Summary"
    assert sections[1].citation_ids == ["1", "2"]
    assert sections[2].title == "1.1 Export"


def test_parse_report_sections_preserves_mid_report_source_section():
    report = """
## Market
Sales increased [1].

### 来源
Demand came from exports and replacement cycles.

## Outlook
Growth continued [2].
"""

    sections = parse_report_sections(report)

    assert [s.title for s in sections] == ["Market", "来源", "Outlook"]
    assert "Demand came from exports" in sections[1].text
    assert sections[2].citation_ids == ["2"]


def test_extract_citation_ids_ignores_numeric_markdown_links():
    text = "See [1](https://example.com) for background, but use footnote [2]."

    assert extract_citation_ids(text) == ["2"]
