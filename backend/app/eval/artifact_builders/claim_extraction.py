"""Build query requirements and atomic claims from report sections."""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import AtomicClaim, QueryRequirement, ReportSection
from app.eval.settings import MAX_CLAIMS

_SYSTEM_PROMPT = (
    "You extract evaluation artifacts from industry research reports. "
    "Respond only with a JSON object matching the requested schema."
)
_PROMPT_PATH = Path(__file__).parent / "prompts" / "claim_extraction.md"


class ClaimExtractionBuilder:
    """Extract query requirements and atomic report claims with a judge."""

    def __init__(self, max_claims: int = MAX_CLAIMS) -> None:
        self.max_claims = max_claims

    async def build(
        self,
        query: str,
        sections: list[ReportSection],
        judge: Any,
    ) -> tuple[list[QueryRequirement], list[AtomicClaim]]:
        sections_json = json.dumps(
            [
                {
                    "id": section.id,
                    "title": section.title,
                    "text": section.text,
                    "citation_ids": section.citation_ids,
                }
                for section in sections
            ],
            ensure_ascii=False,
        )
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            query=query,
            sections_json=sections_json,
            max_claims=self.max_claims,
        )
        result = await judge.generate_structured(prompt, system_prompt=_SYSTEM_PROMPT)
        if result.failed:
            raise ValueError(f"structured judge failed: {result.error or result.content}")

        payload = parse_json_object(result.content)
        requirements = [
            QueryRequirement(**_known_fields(QueryRequirement, item))
            for item in payload.get("requirements") or []
            if str(item.get("text") or "").strip()
        ]
        claims = [
            AtomicClaim(**_known_fields(AtomicClaim, item))
            for item in payload.get("claims") or []
            if str(item.get("text") or "").strip()
        ]
        return requirements, claims[: self.max_claims]


def _known_fields(cls: type, item: dict[str, Any]) -> dict[str, Any]:
    field_names = {field.name for field in fields(cls)}
    return {key: value for key, value in item.items() if key in field_names}
