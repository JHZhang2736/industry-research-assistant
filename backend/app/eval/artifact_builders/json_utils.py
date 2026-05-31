"""Utilities for parsing structured judge JSON."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a plain or fenced JSON object from judge output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse structured JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("structured judge output must be a JSON object")
    return parsed
