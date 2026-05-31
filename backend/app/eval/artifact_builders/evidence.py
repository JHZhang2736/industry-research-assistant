"""Build evidence artifacts from research state."""
from __future__ import annotations

import re
from typing import Any

from app.eval.artifacts import EvidenceItem
from app.eval.settings import EVIDENCE_ITEM_CHARS, MAX_EVIDENCE_ITEMS


class EvidenceIndexBuilder:
    """Build a deduplicated evidence index from final research state."""

    def __init__(
        self,
        max_items: int = MAX_EVIDENCE_ITEMS,
        item_chars: int = EVIDENCE_ITEM_CHARS,
    ) -> None:
        self.max_items = max_items
        self.item_chars = item_chars

    def build(self, state: dict[str, Any]) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        seen: set[tuple[str, str]] = set()

        for fact in state.get("facts") or []:
            self._append(
                items,
                seen,
                EvidenceItem(
                    id=str(fact.get("id") or f"fact_{len(items) + 1}"),
                    text=self._truncate(fact.get("content") or fact.get("text") or ""),
                    source_name=str(fact.get("source_name") or ""),
                    source_url=str(fact.get("source_url") or ""),
                    source_type=str(fact.get("source_type") or "unknown"),
                    credibility_score=fact.get("credibility_score"),
                ),
            )

        for ref in state.get("references") or []:
            ref_id = ref.get("id") or len(items) + 1
            self._append(
                items,
                seen,
                EvidenceItem(
                    id=f"ref_{ref_id}",
                    text=self._truncate(
                        ref.get("title")
                        or ref.get("name")
                        or ref.get("snippet")
                        or ref.get("url")
                        or ""
                    ),
                    source_name=str(ref.get("title") or ref.get("name") or ""),
                    source_url=str(ref.get("url") or ref.get("source_url") or ""),
                    source_type=str(ref.get("source_type") or "reference"),
                    credibility_score=ref.get("credibility_score"),
                ),
            )

        for source in self._raw_sources(state):
            source_id = source.get("id") or len(items) + 1
            self._append(
                items,
                seen,
                EvidenceItem(
                    id=f"source_{source_id}",
                    text=self._truncate(
                        source.get("content")
                        or source.get("text")
                        or source.get("title")
                        or source.get("url")
                        or ""
                    ),
                    source_name=str(source.get("source_name") or source.get("title") or ""),
                    source_url=str(source.get("source_url") or source.get("url") or ""),
                    source_type=str(source.get("source_type") or "source"),
                    credibility_score=source.get("credibility_score"),
                ),
            )

        return items[: self.max_items]

    def _append(
        self,
        items: list[EvidenceItem],
        seen: set[tuple[str, str]],
        item: EvidenceItem,
    ) -> None:
        if len(items) >= self.max_items or not item.text:
            return
        key = (item.source_url, self._normalized_text_prefix(item.text))
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    def _truncate(self, text: Any) -> str:
        return str(text)[: self.item_chars]

    @staticmethod
    def _normalized_text_prefix(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()[:120]

    @staticmethod
    def _raw_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
        sources = state.get("raw_sources")
        if sources is None:
            sources = state.get("sources")
        return list(sources or [])
