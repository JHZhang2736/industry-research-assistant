"""Chat 工作记忆滚动压缩：超阈值时压缩旧历史，完整保留最近 K 轮。"""

from typing import Callable, List, Dict, Tuple

Message = Dict[str, str]


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（中英文混合，约 3 字符/token）。"""
    return len(text) // 3


class ContextCompressor:
    def __init__(self, keep_recent_turns: int = 4, compress_threshold: int = 6000,
                 summarize_fn: Callable[[str], str] = None):
        self.keep_recent_turns = keep_recent_turns
        self.compress_threshold = compress_threshold
        self.summarize_fn = summarize_fn

    @staticmethod
    def _render(messages: List[Message]) -> str:
        return "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages)

    def build_history(self, prior_summary: str, summarized_up_to: int,
                      messages: List[Message]) -> Tuple[str, str, int]:
        """返回 (history_text, new_summary, new_summarized_up_to)。

        - 未超阈值：原文全返回，摘要/游标不变。
        - 超阈值：older = messages[:-keep_recent] 中尚未压缩的部分 → 并入 prior_summary；
          recent = 最近 keep_recent_turns 条原文保留。
        """
        recent = messages[-self.keep_recent_turns:] if self.keep_recent_turns > 0 else []
        recent_text = self._render(recent)

        total_tokens = estimate_tokens(self._render(messages))
        if total_tokens <= self.compress_threshold:
            return self._render(messages), prior_summary, summarized_up_to

        split = max(0, len(messages) - self.keep_recent_turns)
        new_old = messages[summarized_up_to:split]

        if not new_old:
            summary = prior_summary
            new_cursor = summarized_up_to
        else:
            to_summarize = (f"已有摘要：{prior_summary}\n\n" if prior_summary else "") + \
                           f"新增历史：\n{self._render(new_old)}"
            try:
                summary = self.summarize_fn(to_summarize) if self.summarize_fn else prior_summary
                new_cursor = split
            except Exception:
                summary = prior_summary
                new_cursor = summarized_up_to

        parts = []
        if summary:
            parts.append(f"[历史对话摘要]\n{summary}")
        if recent_text:
            parts.append(f"[最近对话]\n{recent_text}")
        return "\n\n".join(parts), summary, new_cursor
