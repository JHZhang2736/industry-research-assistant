"""LangSmith trace + dataset upload. Best-effort (fail-open)."""
from __future__ import annotations

import logging
import os
from typing import Any

from app.eval.types import CaseResult

logger = logging.getLogger("eval.langsmith")


class LangSmithAdapter:
    """Best-effort uploader. Never raises — logs warnings on any failure."""

    def __init__(self, project: str):
        self.project = project
        self._api_key = os.getenv("LANGSMITH_API_KEY")
        self.enabled = bool(self._api_key)
        self._client = None
        if self.enabled:
            try:
                from langsmith import Client
                self._client = Client(api_key=self._api_key)
            except Exception as e:
                logger.warning(f"LangSmith init failed: {e}, disabling")
                self.enabled = False

    def upload_case_sync(self, run_id: str, case_result: CaseResult) -> None:
        if not self.enabled or self._client is None:
            return
        try:
            self._client.create_run(
                name=f"eval-case-{case_result.case.id}",
                run_type="chain",
                project_name=self.project,
                inputs={"query": case_result.case.query, "case_id": case_result.case.id},
                outputs={
                    "final_report": (case_result.state or {}).get("final_report", "")[:5000],
                    "evaluator_scores": {
                        r.evaluator_name: r.score for r in case_result.results
                    },
                },
                start_time=case_result.started_at,
                end_time=case_result.finished_at,
                extra={"run_id": run_id, "error": case_result.error},
            )
        except Exception as e:
            logger.warning(f"LangSmith upload failed for {case_result.case.id}: {e}")

    def dashboard_url(self) -> str | None:
        if not self.enabled:
            return None
        return f"https://smith.langchain.com/o/-/projects/p/{self.project}"
