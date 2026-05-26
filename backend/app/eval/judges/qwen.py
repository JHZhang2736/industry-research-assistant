"""Qwen judge (dashscope OpenAI-compatible)."""
from app.eval.judges.base import JudgeClient
from app.eval.settings import JUDGES


def build_qwen_judge() -> JudgeClient:
    cfg = next(j for j in JUDGES if j.name == "qwen")
    return JudgeClient(cfg)
