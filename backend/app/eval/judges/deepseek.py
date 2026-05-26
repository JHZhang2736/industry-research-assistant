"""DeepSeek judge."""
from app.eval.judges.base import JudgeClient
from app.eval.settings import JUDGES


def build_deepseek_judge() -> JudgeClient:
    cfg = next(j for j in JUDGES if j.name == "deepseek")
    return JudgeClient(cfg)
