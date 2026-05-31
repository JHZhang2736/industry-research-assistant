import pytest

from app.eval.artifact_builders.json_utils import parse_json_object


def test_parse_json_object_plain_json():
    assert parse_json_object('{"claims": []}') == {"claims": []}


def test_parse_json_object_fenced_json():
    raw = '```json\n{"verdicts": [{"claim_id": "c1"}]}\n```'
    assert parse_json_object(raw) == {"verdicts": [{"claim_id": "c1"}]}


def test_parse_json_object_raises_for_non_object():
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object("[1, 2, 3]")
