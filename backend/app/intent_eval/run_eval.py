"""Intent eval 入口：argparse 参数 + 总装 dataset/runner/metrics/storage/reporter。

用法（CWD = backend/）：
    python -m app.intent_eval.run_eval --help
    python -m app.intent_eval.run_eval                          # 默认参数
    python -m app.intent_eval.run_eval --no-db                  # 跳过 SQLite
    python -m app.intent_eval.run_eval --concurrency 5
"""
import argparse
import asyncio
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# 加载仓库根目录的 .env，让本地 `python -m app.intent_eval.run_eval` 不经 FastAPI
# 主入口也能拿到 DASHSCOPE_API_KEY。load_dotenv 幂等且不覆盖已存在的 os.environ，
# shell 导出仍优先。CI 通过 env 注入密钥，无 .env 文件时这里静默跳过。
try:
    from dotenv import load_dotenv as _load_dotenv
    # run_eval.py = backend/app/intent_eval/run_eval.py，向上四级即仓库根目录
    _ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
    if _ENV_PATH.exists():
        _load_dotenv(_ENV_PATH)
except ImportError:
    pass

from app.intent_eval.dataset import load as load_dataset
from app.intent_eval.metrics import compute_level_metrics
from app.intent_eval.reporter import write_markdown
from app.intent_eval.runner import run as run_eval
from app.intent_eval.storage import Storage
from app.intent_eval.types import (
    RunSummary, INTENT_CLASSES, RESEARCH_TYPE_CLASSES,
)
from app.service.intent_service import IntentService
from app.service.research_type_service import ResearchTypeService


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.intent_eval.run_eval",
        description="Run intent recognition eval against current production model.",
    )
    default_ds = Path("app/intent_eval/datasets/intent_eval_v1.jsonl")
    p.add_argument("--dataset", type=Path, default=default_ds,
                   help="Path to jsonl dataset (default: %(default)s)")
    p.add_argument("--concurrency", type=int, default=10,
                   help="Max concurrent LLM calls (default: %(default)s)")
    p.add_argument("--level1-model", type=str, default="qwen-turbo",
                   help="Model for Level 1 intent (default: %(default)s)")
    p.add_argument("--level2-model", type=str, default="qwen-turbo",
                   help="Model for Level 2 research_type (default: %(default)s)")
    p.add_argument("--output-dir", type=Path, default=Path("intent_eval_results"),
                   help="Where to write markdown report (default: %(default)s)")
    p.add_argument("--no-db", action="store_true",
                   help="Skip SQLite persistence (use in CI)")
    return p.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    cases = load_dataset(args.dataset)
    print(f"Loaded {len(cases)} cases from {args.dataset}", file=sys.stderr)

    intent_svc = IntentService(model=args.level1_model)
    rt_svc = ResearchTypeService(model=args.level2_model)

    started_at = datetime.now().replace(microsecond=0).isoformat()
    t0 = time.perf_counter()
    results = await run_eval(cases, intent_svc, rt_svc, concurrency=args.concurrency)
    duration_sec = time.perf_counter() - t0
    finished_at = datetime.now().replace(microsecond=0).isoformat()

    # Level 1 metrics: all cases
    true1 = [c.true_intent for c in cases]
    pred1 = [(r.predicted_intent or "<error>") for r in results]
    level1 = compute_level_metrics(true1, pred1, INTENT_CLASSES)

    # Level 2 metrics: only deep_research cases
    # 空列表也走 compute_level_metrics：per_class 会带全零的三类，避免报表渲染时 KeyError
    l2_pairs = [(c.true_research_type, (r.predicted_research_type or "<error>"))
                for c, r in zip(cases, results) if c.true_research_type is not None]
    true2 = [t for t, _ in l2_pairs]
    pred2 = [p for _, p in l2_pairs]
    level2 = compute_level_metrics(true2, pred2, RESEARCH_TYPE_CLASSES)

    summary = RunSummary(
        run_id=uuid.uuid4().hex[:12],
        started_at=started_at,
        finished_at=finished_at,
        git_commit=_git_commit(),
        dataset_version=args.dataset.stem.split("_")[-1] if "_" in args.dataset.stem else "v1",
        level1_model=args.level1_model,
        level2_model=args.level2_model,
        concurrency=args.concurrency,
        duration_sec=duration_sec,
        level1=level1,
        level2=level2,
    )

    report_path = write_markdown(summary, results, args.output_dir)

    if not args.no_db:
        db_path = args.output_dir / "intent_eval.db"
        storage = Storage(db_path)
        storage.init_schema()
        storage.save_run(summary, results)

    # stdout summary
    print()
    print(f"=== Intent Eval Run {summary.run_id} ===")
    print(f"Dataset: {args.dataset.name} ({len(cases)} cases)")
    print(f"Duration: {duration_sec:.0f} sec")
    print()
    print("Level 1 (intent):")
    print(f"  Accuracy: {level1.accuracy * 100:.1f}% "
          f"({round(level1.accuracy * level1.n)}/{level1.n})")
    print(f"  Macro F1: {level1.macro_f1:.3f}")
    print()
    print(f"Level 2 (research_type, n={level2.n}):")
    print(f"  Accuracy: {level2.accuracy * 100:.1f}% "
          f"({round(level2.accuracy * level2.n)}/{level2.n})")
    print(f"  Macro F1: {level2.macro_f1:.3f}")
    print()
    print(f"Report: {report_path}")
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_main_async(args))
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
