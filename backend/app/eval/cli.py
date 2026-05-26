"""Eval CLI. Entry: python -m app.eval.cli"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.eval.judges.deepseek import build_deepseek_judge
from app.eval.judges.ensemble import EnsembleJudge
from app.eval.judges.mimo import build_mimo_judge
from app.eval.judges.qwen import build_qwen_judge
from app.eval.runner import EvalRunner
from app.eval.settings import (
    DEFAULT_CONCURRENCY,
    LANGSMITH_PROJECT,
    SQLITE_PATH,
    validate_required_keys,
)
from app.eval.types import EvalCase

logger = logging.getLogger("eval.cli")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent.parent.parent,
        ).decode().strip()
    except Exception:
        return "unknown"


def _load_dataset(name: str) -> list[EvalCase]:
    base = Path(__file__).parent / "datasets"
    if name == "full":
        path = base / "seed_queries.jsonl"
    elif name == "mini":
        # First 5 of seed for quick iteration
        path = base / "seed_queries.jsonl"
    else:
        # Treat as path
        path = Path(name)

    lines = path.read_text(encoding="utf-8").splitlines()
    cases = [EvalCase(**json.loads(line)) for line in lines if line.strip()]
    if name == "mini":
        cases = cases[:5]
    return cases


async def _load_final_state(session_id: str) -> dict | None:
    """Load final research state from PG checkpoint table."""
    try:
        from service.checkpoint_service import CheckpointService
    except ImportError:
        try:
            from app.service.checkpoint_service import CheckpointService
        except ImportError:
            logger.error("Cannot import CheckpointService")
            return None

    svc = CheckpointService()
    cp = await svc.get_latest(session_id)
    if cp is None:
        return None
    return cp.get("state") if isinstance(cp, dict) else getattr(cp, "state", None)


def _build_service():
    try:
        from service.deep_research_v2.service import DeepResearchV2Service
    except ImportError:
        from app.service.deep_research_v2.service import DeepResearchV2Service
    return DeepResearchV2Service()


async def cmd_run(args: argparse.Namespace) -> int:
    missing = validate_required_keys()
    if missing:
        print(f"❌ Missing required env vars: {missing}", file=sys.stderr)
        return 2

    cases = _load_dataset(args.suite)
    if args.limit:
        cases = cases[: args.limit]
    print(f"Suite: {args.suite}, {len(cases)} cases, concurrency={args.concurrency}")

    judge = EnsembleJudge([
        build_deepseek_judge(),
        build_mimo_judge(),
        build_qwen_judge(),
    ])

    runner = EvalRunner(
        service=_build_service(),
        load_final_state=_load_final_state,
        judge=judge,
        db_path=args.db,
        out_dir=args.out,
        concurrency=args.concurrency,
        git_commit=_git_commit(),
        langsmith_project=args.langsmith_project,
    )

    summary = await runner.run(args.suite, cases)
    print("\n✅ Eval complete")
    print(f"  Run ID: {summary['run_id']}")
    print(f"  OK / Total: {summary['ok']} / {summary['total']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Markdown: {summary['markdown_path']}")
    print(f"  CSV: {summary['csv_path']}")
    if summary["langsmith_url"]:
        print(f"  LangSmith: {summary['langsmith_url']}")
    return 0 if summary["failed"] == 0 else 1


async def cmd_smoke(args: argparse.Namespace) -> int:
    """One-case real run for fast manual verification."""
    cases = [EvalCase(
        id=args.case_id,
        query=args.query,
        category="manual",
        difficulty="easy",
    )]
    args.suite = "smoke"
    args.limit = None
    return await cmd_run(args)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(prog="python -m app.eval.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run a full eval suite")
    p_run.add_argument("--suite", default="full", help="full | mini | <jsonl path>")
    p_run.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p_run.add_argument("--db", default=SQLITE_PATH)
    p_run.add_argument("--out", default="docs/eval-results")
    p_run.add_argument("--langsmith-project", default=LANGSMITH_PROJECT)
    p_run.add_argument("--limit", type=int, default=None, help="cap number of cases")

    p_smoke = sub.add_parser("smoke", help="Run 1 case (real LLM/network)")
    p_smoke.add_argument("--query", required=True)
    p_smoke.add_argument("--case-id", default="smoke-001")
    p_smoke.add_argument("--concurrency", type=int, default=1)
    p_smoke.add_argument("--db", default=SQLITE_PATH)
    p_smoke.add_argument("--out", default="docs/eval-results")
    p_smoke.add_argument("--langsmith-project", default=LANGSMITH_PROJECT)

    args = p.parse_args()
    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    elif args.cmd == "smoke":
        return asyncio.run(cmd_smoke(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
