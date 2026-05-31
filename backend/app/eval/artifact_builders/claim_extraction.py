"""Build query requirements and atomic claims from report sections."""
from __future__ import annotations

import json
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
        requirements = _normalize_requirements(payload.get("requirements") or [])
        claims = _normalize_claims(payload.get("claims") or [])
        return requirements, claims[: self.max_claims]


def _normalize_requirements(items: list[Any]) -> list[QueryRequirement]:
    requirements: list[QueryRequirement] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        requirements.append(
            QueryRequirement(
                id=str(item.get("id") or f"r{index}"),
                text=text,
                importance=str(item.get("importance") or "medium"),
            )
        )
    return requirements


def _normalize_claims(items: list[Any]) -> list[AtomicClaim]:
    claims: list[AtomicClaim] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        claims.append(
            AtomicClaim(
                id=str(item.get("id") or f"c{index}"),
                text=text,
                section_id=str(item.get("section_id") or ""),
                importance=str(item.get("importance") or "medium"),
                citation_ids=_string_list(item.get("citation_ids")),
                requirement_ids=_string_list(item.get("requirement_ids")),
            )
        )
    return claims


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
