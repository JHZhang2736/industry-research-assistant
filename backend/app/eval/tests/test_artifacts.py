from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    EvidenceItem,
    QueryRequirement,
    ReportQualityScores,
    ReportSection,
    artifact_from_dict,
    artifact_to_dict,
)


def test_artifact_round_trips_to_plain_dict():
    artifact = EvalArtifact(
        evidence=[
            EvidenceItem(
                id="f1",
                text="2024 year sales reached 9.5 million vehicles.",
                source_name="CAAM",
                source_url="https://example.com/a",
                source_type="official",
                credibility_score=0.9,
            )
        ],
        sections=[
            ReportSection(
                id="s1",
                title="Market Size",
                text="Sales reached 9.5 million vehicles [1].",
                citation_ids=["1"],
            )
        ],
        requirements=[
            QueryRequirement(id="r1", text="Analyze 2024 market size", importance="high")
        ],
        claims=[
            AtomicClaim(
                id="c1",
                text="2024 year sales reached 9.5 million vehicles.",
                section_id="s1",
                importance="high",
                citation_ids=["1"],
                requirement_ids=["r1"],
            )
        ],
        verdicts=[
            ClaimVerdict(
                claim_id="c1",
                supported=True,
                reason="Evidence f1 states the same number.",
                evidence_ids=["f1"],
                confidence="high",
            )
        ],
        quality=ReportQualityScores(
            coherence=8.0,
            cohesion_structure=7.5,
            analytical_depth=8.2,
            professionalism_readability=8.4,
            decision_usefulness=7.8,
            raw_judge_outputs=[{"judge": "qwen", "coherence": 8.0}],
            std_by_dimension={"coherence": 0.5},
            low_confidence_dimensions=[],
            partial=False,
        ),
    )

    payload = artifact_to_dict(artifact)
    restored = artifact_from_dict(payload)

    assert payload["claims"][0]["id"] == "c1"
    assert restored.claims[0].text == artifact.claims[0].text
    assert restored.quality.coherence == 8.0
    assert restored.errors == []


def test_artifact_defaults_are_empty_lists():
    artifact = EvalArtifact()
    assert artifact.evidence == []
    assert artifact.sections == []
    assert artifact.requirements == []
    assert artifact.claims == []
    assert artifact.verdicts == []
    assert artifact.errors == []
    assert artifact.quality.coherence is None


def test_artifact_round_trip_preserves_quality_error():
    artifact = EvalArtifact(
        quality=ReportQualityScores(error="quality boom", partial=True)
    )

    restored = artifact_from_dict(artifact_to_dict(artifact))

    assert restored.quality.error == "quality boom"
    assert restored.quality.partial is True


def test_artifact_from_none_returns_empty_artifact():
    artifact = artifact_from_dict(None)

    assert artifact == EvalArtifact()


def test_artifact_from_dict_ignores_unknown_additive_keys():
    artifact = artifact_from_dict(
        {
            "evidence": [
                {
                    "id": "f1",
                    "text": "Sales reached 9.5 million vehicles.",
                    "source_name": "CAAM",
                    "source_url": "https://example.com/a",
                    "source_type": "official",
                    "future_field": "ignored",
                }
            ],
            "quality": {"coherence": 8.0, "future_dimension": 9.0},
            "future_top_level": "ignored",
        }
    )

    assert artifact.evidence[0].id == "f1"
    assert artifact.quality.coherence == 8.0


def test_artifact_from_dict_treats_none_quality_as_default_scores():
    artifact = artifact_from_dict({"quality": None})

    assert artifact.quality == ReportQualityScores()


def test_artifact_from_dict_accepts_existing_nested_dataclasses():
    evidence = EvidenceItem(
        id="f1",
        text="Sales reached 9.5 million vehicles.",
        source_name="CAAM",
        source_url="https://example.com/a",
        source_type="official",
    )
    quality = ReportQualityScores(coherence=8.0)

    artifact = artifact_from_dict({"evidence": [evidence], "quality": quality})

    assert artifact.evidence == [evidence]
    assert artifact.quality == quality


def test_artifact_from_dict_returns_existing_artifact_unchanged():
    artifact = EvalArtifact(errors=["already built"])

    assert artifact_from_dict(artifact) is artifact
