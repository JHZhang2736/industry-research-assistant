from app.eval.artifact_builders.evidence import EvidenceIndexBuilder


def test_evidence_builder_uses_facts_first_and_deduplicates():
    state = {
        "facts": [
            {
                "id": "f1",
                "content": "Sales reached 9.5 million vehicles in 2024.",
                "source_name": "CAAM",
                "source_url": "https://example.com/a",
                "source_type": "official",
                "credibility_score": 0.9,
            },
            {
                "id": "f2",
                "content": "Sales reached 9.5 million vehicles in 2024.",
                "source_name": "CAAM duplicate",
                "source_url": "https://example.com/a",
                "source_type": "official",
                "credibility_score": 0.8,
            },
        ],
        "references": [
            {"id": "1", "title": "Industry report", "url": "https://example.com/ref"}
        ],
    }

    items = EvidenceIndexBuilder(max_items=10).build(state)

    assert [item.id for item in items] == ["f1", "ref_1"]
    assert items[0].source_name == "CAAM"
    assert items[1].text == "Industry report"


def test_evidence_builder_truncates_text_and_limits_count():
    state = {
        "facts": [
            {
                "id": f"f{i}",
                "content": "x" * 500,
                "source_name": "src",
                "source_url": f"https://example.com/{i}",
            }
            for i in range(5)
        ]
    }

    items = EvidenceIndexBuilder(max_items=2, item_chars=100).build(state)

    assert len(items) == 2
    assert len(items[0].text) == 100
