"""Eval framework settings.

Reads from env vars. No dynamic imports. Override via os.environ in tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path as _Path

# Load backend/.env so `python -c "..."` and pytest pick up secrets without
# needing the FastAPI main entry to run. load_dotenv is idempotent and never
# overrides values already in os.environ, so shell exports still win.
try:
    from dotenv import load_dotenv as _load_dotenv
    _ENV_PATH = _Path(__file__).resolve().parent.parent.parent / ".env"
    if _ENV_PATH.exists():
        _load_dotenv(_ENV_PATH)
except ImportError:
    pass


@dataclass(frozen=True)
class JudgeConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    max_rate_per_min: int

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


# Three judge families
JUDGES: list[JudgeConfig] = [
    JudgeConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        model=os.getenv("DEEPSEEK_JUDGE_MODEL", "deepseek-chat"),
        api_key_env="DEEPSEEK_API_KEY",
        max_rate_per_min=50,
    ),
    JudgeConfig(
        name="mimo",
        base_url="https://api.xiaomimimo.com/v1",
        model=os.getenv("XIAOMI_JUDGE_MODEL", "mimo-v2.5-pro"),
        api_key_env="XIAOMI_API_KEY",
        max_rate_per_min=30,
    ),
    JudgeConfig(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model=os.getenv("QWEN_JUDGE_MODEL", "qwen-max"),
        api_key_env="DASHSCOPE_API_KEY",
        max_rate_per_min=50,
    ),
]


# Per-1M-tokens cost in RMB (input, output). Update when pricing changes.
PRICING_RMB_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    "qwen-max": (20.0, 60.0),
    "qwen-plus": (4.0, 12.0),
    "qwen-turbo": (2.0, 6.0),
    "deepseek-chat": (1.0, 2.0),
    "deepseek-v3": (1.0, 2.0),
    "deepseek-v3.2": (1.0, 2.0),
    "mimo-v2.5-pro": (3.0, 9.0),  # placeholder, update from official pricing
}


# Eval suite defaults
DEFAULT_CONCURRENCY = 5
# Real research can take 20-30 min on hard queries (multi-agent + retries + chart codegen).
# Override via env: EVAL_RESEARCH_TIMEOUT_SEC=2400 for 40min hard cap.
DEFAULT_RESEARCH_TIMEOUT_SEC = int(os.getenv("EVAL_RESEARCH_TIMEOUT_SEC", "1800"))
DEFAULT_JUDGE_TIMEOUT_SEC = 60
JUDGE_RETRY_ATTEMPTS = 3
URL_CHECK_TIMEOUT_SEC = 5
LOW_CONFIDENCE_STD_THRESHOLD = 2.0
MAX_EVIDENCE_ITEMS = int(os.getenv("EVAL_MAX_EVIDENCE_ITEMS", "60"))
EVIDENCE_ITEM_CHARS = int(os.getenv("EVAL_EVIDENCE_ITEM_CHARS", "300"))
MAX_CLAIMS = int(os.getenv("EVAL_MAX_CLAIMS", "40"))
REPORT_CHARS = int(os.getenv("EVAL_REPORT_CHARS", "8000"))
JUDGE_WEIGHTS: dict[str, float] = {
    "deepseek": float(os.getenv("EVAL_JUDGE_WEIGHT_DEEPSEEK", "0.4")),
    "qwen": float(os.getenv("EVAL_JUDGE_WEIGHT_QWEN", "0.4")),
    "mimo": float(os.getenv("EVAL_JUDGE_WEIGHT_MIMO", "0.2")),
}

REPORT_QUALITY_DIMENSIONS = (
    "coherence",
    "cohesion_structure",
    "analytical_depth",
    "professionalism_readability",
    "decision_usefulness",
)

# SQLite storage path
SQLITE_PATH = os.getenv(
    "EVAL_SQLITE_PATH",
    str(_Path(__file__).parent / ".eval.db"),
)

# LangSmith (optional)
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "industry-research-eval")
LANGSMITH_ENABLED = bool(os.getenv("LANGSMITH_API_KEY"))


def validate_required_keys() -> list[str]:
    """Return list of missing required env vars."""
    missing = []
    for j in JUDGES:
        if not j.api_key:
            missing.append(j.api_key_env)
    # Research itself needs these too
    for required in ("DASHSCOPE_API_KEY", "BOCHA_API_KEY"):
        if not os.getenv(required) and required not in missing:
            missing.append(required)
    return missing
