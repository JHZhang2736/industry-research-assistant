"""Build support verdicts for extracted atomic claims."""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvidenceItem

_SYSTEM_PROMPT = (
    "You verify report claims against provided evidence. "
    "Respond only with a JSON object matching the requested schema."
)
_PROMPT_PATH = Path(__file__).parent / "prompts" / "claim_verification.md"


class ClaimVerificationBuilder:
    """Verify each claim against evidence with a structured judge."""

    async def build(
        self,
        claims: list[AtomicClaim],
        evidence: list[EvidenceItem],
        judge: Any,
    ) -> list[ClaimVerdict]:
        if not claims:
            return []

        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            claims_json=json.dumps(
                [_to_jsonable(claim) for claim in claims],
                ensure_ascii=False,
            ),
            evidence_json=json.dumps(
                [_to_jsonable(item) for item in evidence],
                ensure_ascii=False,
            ),
        )
        result = await judge.generate_structured(prompt, system_prompt=_SYSTEM_PROMPT)
        if result.failed:
            raise ValueError(f"structured judge failed: {result.error or result.content}")

        payload = parse_json_object(result.content)
        known_claim_ids = {claim.id for claim in claims}
        verdicts_by_claim_id = _normalize_verdicts(
            payload.get("verdicts") or [],
            known_claim_ids,
        )

        return [
            verdicts_by_claim_id.get(
                claim.id,
                ClaimVerdict(
                    claim_id=claim.id,
                    supported=False,
                    reason="judge omitted verdict",
                    evidence_ids=[],
                    confidence="low",
                ),
            )
            for claim in claims
        ]


def _normalize_verdicts(
    items: list[Any],
    known_claim_ids: set[str],
) -> dict[str, ClaimVerdict]:
    verdicts_by_claim_id: dict[str, ClaimVerdict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "").strip()
        if not claim_id or claim_id not in known_claim_ids:
            continue
        verdicts_by_claim_id[claim_id] = ClaimVerdict(
            claim_id=claim_id,
            supported=_coerce_supported(item.get("supported")),
            reason=str(item.get("reason") or ""),
            evidence_ids=_string_list(item.get("evidence_ids")),
            confidence=str(item.get("confidence") or "low"),
        )
    return verdicts_by_claim_id


def _coerce_supported(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() == "true"
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _to_jsonable(item: Any) -> dict[str, Any]:
    return {field.name: getattr(item, field.name) for field in fields(item)}
