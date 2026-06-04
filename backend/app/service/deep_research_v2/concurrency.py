"""Global provider-level semaphores for LLM and search API rate protection.

Shared across all agents to bound concurrent in-flight requests under provider
QPM limits. In-flight count ≠ QPM since each LLM call takes 1-30s; 10-20
in-flight roughly maps to 30-60 QPM in practice.

Configurable via env:
  DASHSCOPE_MAX_INFLIGHT  (default 10)
  DEEPSEEK_MAX_INFLIGHT   (default 20)
  BOCHA_MAX_INFLIGHT      (default 4)
"""
from __future__ import annotations

import asyncio
import logging
import os


_logger = logging.getLogger(__name__)


DASHSCOPE_MAX_INFLIGHT = int(os.getenv("DASHSCOPE_MAX_INFLIGHT", "10"))
DEEPSEEK_MAX_INFLIGHT  = int(os.getenv("DEEPSEEK_MAX_INFLIGHT", "20"))
BOCHA_MAX_INFLIGHT     = int(os.getenv("BOCHA_MAX_INFLIGHT", "4"))

DASHSCOPE_SEM = asyncio.Semaphore(DASHSCOPE_MAX_INFLIGHT)
DEEPSEEK_SEM  = asyncio.Semaphore(DEEPSEEK_MAX_INFLIGHT)
BOCHA_SEM     = asyncio.Semaphore(BOCHA_MAX_INFLIGHT)


def get_llm_semaphore(base_url) -> asyncio.Semaphore:
    """Select the right semaphore for an LLM provider based on its base_url.

    Accepts either a `str` or any object with a sane `__str__` (e.g. the
    OpenAI SDK exposes `client.base_url` as an httpx `URL` instance, not
    a string). Coerces to str defensively before substring matching.

    Default falls back to DASHSCOPE_SEM (most conservative) when base_url
    doesn't match a known provider, with a warning so unknown providers
    aren't silently throttled like dashscope.
    """
    url_str = str(base_url) if base_url is not None else ""
    if "dashscope" in url_str:
        return DASHSCOPE_SEM
    if "deepseek" in url_str:
        return DEEPSEEK_SEM
    _logger.warning(
        "Unknown LLM base_url %r; falling back to DASHSCOPE_SEM (default 10 in-flight)",
        url_str,
    )
    return DASHSCOPE_SEM


def sem_status() -> dict:
    """Diagnostic snapshot of current in-flight counts.

    Reads Semaphore._value which is a stable Python 3.4+ attribute.
    Used by graph.py review-node to log peak concurrency.
    """
    return {
        "dashscope_inflight": DASHSCOPE_MAX_INFLIGHT - DASHSCOPE_SEM._value,
        "deepseek_inflight":  DEEPSEEK_MAX_INFLIGHT  - DEEPSEEK_SEM._value,
        "bocha_inflight":     BOCHA_MAX_INFLIGHT     - BOCHA_SEM._value,
    }
