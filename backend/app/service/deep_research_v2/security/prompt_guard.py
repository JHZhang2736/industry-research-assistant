"""间接 Prompt 注入防护：启发式检测 + 内容隔离标记。

外部网页内容流入 LLM 前的收口层。三个核心能力：
- detect_injection: 启发式识别"试图当指令"的内容
- wrap_untrusted:   用带 nonce 的隔离块包裹不可信内容
- guard_results:    批量过滤搜索结果（命中即丢弃）
"""

import re
import secrets
from dataclasses import dataclass, field
from typing import Callable, List, Tuple


@dataclass
class InjectionVerdict:
    flagged: bool
    score: float
    matched_patterns: List[str] = field(default_factory=list)


# (name, compiled_pattern) —— 中英双语注入特征
_INJECTION_PATTERNS: List[Tuple[str, "re.Pattern"]] = [
    ("override_zh", re.compile(r"(忽略|无视|不要理会|不用管)[\s，,]*((以上|之前|前面|上述|所有|全部)[\s，,]*)*(的)?[\s，,]*(指令|提示|要求|命令|规则|设定)")),
    ("override_en", re.compile(
        r"ignore\s+(the\s+|all\s+)?(previous|above|prior|earlier|all|foregoing)\s+(instructions?|prompts?|rules?|commands?)",
        re.IGNORECASE)),
    ("disregard_en", re.compile(
        r"disregard\s+(the\s+|all\s+)?(previous|above|prior|all)\b", re.IGNORECASE)),
    ("role_token", re.compile(
        r"<\|im_(start|end)\|>|\[/?INST\]|###\s*(instruction|system)", re.IGNORECASE)),
    ("fake_role", re.compile(r"(?mi)^\s*(system|assistant)\s*[:：]")),
    ("role_reassign_en", re.compile(
        r"\byou\s+are\s+now\b|\bfrom\s+now\s+on\b|\bpretend\s+to\s+be\b|\bact\s+as\s+an?\b",
        re.IGNORECASE)),
    ("role_reassign_zh", re.compile(r"你现在是|从现在开始|从此以后你|扮演|假装你是|你不再是")),
    ("boundary_break", re.compile(r"</?\s*EXTERNAL_DATA", re.IGNORECASE)),
    ("prompt_leak", re.compile(
        r"(reveal|print|repeat|show|输出|打印|重复).{0,20}(system\s*prompt|your\s+instructions|系统提示|你的指令)",
        re.IGNORECASE)),
]


def detect_injection(text: str) -> InjectionVerdict:
    """启发式检测文本是否含 Prompt 注入特征。"""
    if not text:
        return InjectionVerdict(flagged=False, score=0.0, matched_patterns=[])
    matched = [name for name, pat in _INJECTION_PATTERNS if pat.search(text)]
    score = len(matched) / len(_INJECTION_PATTERNS)
    return InjectionVerdict(flagged=bool(matched), score=score, matched_patterns=matched)
