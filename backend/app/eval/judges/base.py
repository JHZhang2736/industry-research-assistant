"""JudgeClient base — OpenAI-compatible LLM judge with retry + rate limit."""
from __future__ import annotations

import json
import logging
import re

from aiolimiter import AsyncLimiter
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.eval.settings import (
    DEFAULT_JUDGE_TIMEOUT_SEC,
    JUDGE_RETRY_ATTEMPTS,
    JudgeConfig,
)
from app.eval.types import JudgeScore

logger = logging.getLogger("eval.judge")


def parse_judge_response(raw: str) -> tuple[float, str]:
    """Parse judge raw output into (score, reasoning).

    Strategy: ① strip markdown fences → ② json.loads → ③ regex first 0-10 number.
    Raises ValueError if no usable number found.
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "score" in obj:
            score = float(obj["score"])
            if not (0.0 <= score <= 10.0):
                raise ValueError(f"score {score} outside [0, 10]")
            reasoning = str(obj.get("reasoning", ""))
            return score, reasoning
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # regex fallback: find first number that looks like a 0-10 score
    m = re.search(r"\b(?:10|10\.0|[0-9](?:\.\d+)?)\b", raw)
    if m:
        return float(m.group(0)), raw

    raise ValueError(f"could not parse score from judge response: {raw[:200]!r}")


class JudgeClient:
    """One judge family. OpenAI-compatible chat completions."""

    def __init__(self, cfg: JudgeConfig):
        self.cfg = cfg
        self._client = AsyncOpenAI(
            api_key=cfg.api_key or "missing",
            base_url=cfg.base_url,
            timeout=DEFAULT_JUDGE_TIMEOUT_SEC,
        )
        self._limiter = AsyncLimiter(
            max_rate=cfg.max_rate_per_min,
            time_period=60,
        )

    async def call_judge(self, prompt: str) -> JudgeScore:
        """Call the judge with retry + limiter. Always returns JudgeScore (never raises)."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(JUDGE_RETRY_ATTEMPTS),
                wait=wait_exponential(multiplier=1, min=1, max=16),
                retry=retry_if_exception_type((APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)),
                reraise=True,
            ):
                with attempt:
                    async with self._limiter:
                        resp = await self._client.chat.completions.create(
                            model=self.cfg.model,
                            messages=[
                                {"role": "system", "content": "You are an evaluation judge. Respond ONLY with JSON: {\"score\": <0-10 float>, \"reasoning\": <short Chinese explanation>}."},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.0,
                        )
                    content = resp.choices[0].message.content or ""
                    score, reasoning = parse_judge_response(content)
                    return JudgeScore(
                        judge_name=self.cfg.name,
                        score=score,
                        reasoning=reasoning,
                        failed=False,
                    )
        except ValueError as e:
            logger.warning(f"[{self.cfg.name}] parse failed: {e}")
            return JudgeScore(
                judge_name=self.cfg.name,
                score=None,
                reasoning="",
                failed=True,
                error=str(e),
            )
        except Exception as e:
            logger.warning(f"[{self.cfg.name}] api failed after retries: {e}")
            return JudgeScore(
                judge_name=self.cfg.name,
                score=None,
                reasoning="",
                failed=True,
                error=str(e),
            )
