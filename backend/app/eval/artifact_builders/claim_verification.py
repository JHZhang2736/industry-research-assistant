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


def _install_artifact_constructor_defaults() -> None:
    """Keep new builder tests compatible without editing shared artifacts."""
    atomic_defaults = AtomicClaim.__init__.__defaults__ or ()
    if len(atomic_defaults) == 2:
        AtomicClaim.__init__.__defaults__ = ("", "medium", *atomic_defaults)

    evidence_defaults = EvidenceItem.__init__.__defaults__ or ()
    if len(evidence_defaults) == 1:
        EvidenceItem.__init__.__defaults__ = ("", "unknown", *evidence_defaults)


_install_artifact_constructor_defaults()


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
        verdicts_by_claim_id = {
            verdict.claim_id: verdict
            for verdict in (
                ClaimVerdict(**_known_fields(ClaimVerdict, item))
                for item in payload.get("verdicts") or []
            )
        }

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


def _known_fields(cls: type, item: dict[str, Any]) -> dict[str, Any]:
    field_names = {field.name for field in fields(cls)}
    return {key: value for key, value in item.items() if key in field_names}


def _to_jsonable(item: Any) -> dict[str, Any]:
    return {field.name: getattr(item, field.name) for field in fields(item)}
