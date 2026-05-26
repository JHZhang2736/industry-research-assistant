"""Main eval runner: orchestrates research execution + evaluation + storage."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from app.eval.evaluators import build_all_evaluators
from app.eval.langsmith_adapter import LangSmithAdapter
from app.eval.reporter import Reporter
from app.eval.settings import DEFAULT_RESEARCH_TIMEOUT_SEC, LANGSMITH_PROJECT
from app.eval.storage import EvalStorage
from app.eval.types import CaseResult, EvalCase, EvalContext

logger = logging.getLogger("eval.runner")


class EvalRunner:
    def __init__(
        self,
        service: Any,
        load_final_state: Callable[[str], Awaitable[dict | None]],
        judge: Any,
        db_path: str,
        out_dir: str,
        concurrency: int = 5,
        git_commit: str = "unknown",
        langsmith_project: str = LANGSMITH_PROJECT,
    ):
        self.service = service
        self.load_final_state = load_final_state
        self.judge = judge
        self.evaluators = build_all_evaluators()
        self.storage = EvalStorage(db_path)
        self.storage.init_schema()
        self.reporter = Reporter(out_dir)
        self.langsmith = LangSmithAdapter(project=langsmith_project)
        self.concurrency = concurrency
        self.git_commit = git_commit

    async def run(self, suite: str, cases: list[EvalCase]) -> dict[str, Any]:
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        started_at = datetime.now()
        self.storage.save_run_start(
            run_id=run_id,
            suite=suite,
            started_at=started_at,
            git_commit=self.git_commit,
            config={"concurrency": self.concurrency},
        )

        sem = asyncio.Semaphore(self.concurrency)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            transient=False,
        ) as progress:
            task = progress.add_task("Eval", total=len(cases))

            async def one(case: EvalCase) -> CaseResult:
                async with sem:
                    result = await self._run_one_case(case, run_id)
                    progress.update(task, advance=1)
                    return result

            case_results = await asyncio.gather(*[one(c) for c in cases])

        finished_at = datetime.now()
        self.storage.save_run_end(run_id, finished_at)

        ls_url = self.langsmith.dashboard_url()
        paths = self.reporter.write(
            run_id=run_id,
            suite=suite,
            git_commit=self.git_commit,
            started_at=started_at,
            finished_at=finished_at,
            case_results=case_results,
            langsmith_url=ls_url,
        )

        return {
            "run_id": run_id,
            "total": len(case_results),
            "ok": sum(1 for c in case_results if c.ok),
            "failed": sum(1 for c in case_results if not c.ok),
            "markdown_path": paths["markdown"],
            "csv_path": paths["csv"],
            "langsmith_url": ls_url,
        }

    async def _run_one_case(self, case: EvalCase, run_id: str) -> CaseResult:
        started = datetime.now()
        try:
            # Phase A: run research
            state = await asyncio.wait_for(
                self._execute_research(case),
                timeout=DEFAULT_RESEARCH_TIMEOUT_SEC,
            )
            finished = datetime.now()

            ctx = EvalContext(
                case=case,
                state=state,
                started_at=started,
                finished_at=finished,
            )

            # Phase B: run all evaluators
            results = await asyncio.gather(
                *[ev.evaluate(ctx, self.judge) for ev in self.evaluators],
                return_exceptions=True,
            )

            from app.eval.types import EvalResult
            ev_results: list[EvalResult] = []
            for ev, r in zip(self.evaluators, results):
                if isinstance(r, EvalResult):
                    ev_results.append(r)
                else:
                    ev_results.append(EvalResult(
                        evaluator_name=ev.name,
                        score=None,
                        error=str(r),
                    ))

            cr = CaseResult(
                case=case,
                results=ev_results,
                ok=True,
                state=state,
                started_at=started,
                finished_at=finished,
            )

            # Phase C: persist
            self.storage.save_case(run_id, cr)
            self.langsmith.upload_case_sync(run_id, cr)
            return cr

        except asyncio.TimeoutError:
            cr = CaseResult(case=case, ok=False, error="TimeoutError (>10min)", started_at=started, finished_at=datetime.now())
            self.storage.save_case(run_id, cr)
            return cr
        except Exception as e:
            logger.exception(f"[{case.id}] failed: {e}")
            cr = CaseResult(case=case, ok=False, error=str(e), started_at=started, finished_at=datetime.now())
            self.storage.save_case(run_id, cr)
            return cr

    async def _execute_research(self, case: EvalCase) -> dict:
        """Consume SSE stream, then load final state from checkpoint."""
        async for chunk in self.service.research(
            query=case.query,
            session_id=case.id,
        ):
            if "[DONE]" in chunk:
                break

        # checkpoint write has a small delay; retry once if missing
        state = await self.load_final_state(case.id)
        if state is None:
            await asyncio.sleep(5)
            state = await self.load_final_state(case.id)
        if state is None:
            raise RuntimeError(f"checkpoint not found for session {case.id}")
        return state
