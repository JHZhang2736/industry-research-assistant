"""DeepResearch 安全防护包：Prompt 注入防护 + 代码沙箱。"""

from .prompt_guard import (
    InjectionVerdict,
    GuardedResults,
    detect_injection,
    wrap_untrusted,
    guard_results,
    INJECTION_DEFENSE_PREAMBLE,
)

__all__ = [
    "InjectionVerdict",
    "GuardedResults",
    "detect_injection",
    "wrap_untrusted",
    "guard_results",
    "INJECTION_DEFENSE_PREAMBLE",
]
