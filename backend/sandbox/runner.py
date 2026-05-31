"""沙箱容器入口：从 env SANDBOX_CODE 读代码，受限 exec，输出 JSON 结果到 stdout。

只在锁死的一次性容器里运行。不可信代码经此执行，结果（图表 base64 + stdout）
以单行 JSON 打到 stdout 供宿主解析。
"""

import os
import io
import sys
import json
import base64
from contextlib import redirect_stdout, redirect_stderr


def _build_globals(plt, pd, np, sns, matplotlib):
    import datetime as _dt
    import math as _math
    import statistics as _stat
    import json as _json
    import collections as _coll
    import re as _re

    safe_builtins = {
        "print": print, "len": len, "range": range, "enumerate": enumerate,
        "zip": zip, "map": map, "filter": filter, "sorted": sorted, "sum": sum,
        "min": min, "max": max, "abs": abs, "round": round, "int": int,
        "float": float, "str": str, "list": list, "dict": dict, "tuple": tuple,
        "set": set, "bool": bool, "True": True, "False": False, "None": None,
        "isinstance": isinstance, "type": type, "getattr": getattr,
        "setattr": setattr, "hasattr": hasattr, "callable": callable,
        "iter": iter, "next": next, "reversed": reversed, "slice": slice,
        "all": all, "any": any, "chr": chr, "ord": ord, "hex": hex, "bin": bin,
        "oct": oct, "pow": pow, "divmod": divmod, "format": format,
        "repr": repr, "hash": hash, "id": id,
        "input": lambda *a: "", "open": None,
        "__import__": __import__,  # 容器内本就隔离，允许常规 import
        # 常用异常类
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
        "RuntimeError": RuntimeError, "StopIteration": StopIteration,
        "NotImplementedError": NotImplementedError, "IOError": IOError,
        "OSError": OSError, "NameError": NameError, "ZeroDivisionError": ZeroDivisionError,
        "OverflowError": OverflowError, "ImportError": ImportError,
        "AssertionError": AssertionError, "ArithmeticError": ArithmeticError,
        "LookupError": LookupError, "MemoryError": MemoryError,
        "RecursionError": RecursionError,
    }
    return {
        "__builtins__": safe_builtins,
        "pd": pd, "np": np, "plt": plt, "sns": sns,
        "pandas": pd, "numpy": np, "matplotlib": matplotlib,
        "datetime": _dt, "math": _math, "statistics": _stat,
        "json": _json, "collections": _coll, "re": _re,
    }


def main() -> None:
    code = os.environ.get("SANDBOX_CODE", "")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import numpy as np
    import seaborn as sns

    plt.rcParams["font.sans-serif"] = [
        "WenQuanYi Zen Hei", "SimHei", "Microsoft YaHei",
        "Arial Unicode MS", "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.figsize"] = [12, 7]
    plt.rcParams["figure.dpi"] = 200

    exec_globals = _build_globals(plt, pd, np, sns, matplotlib)
    out, err = io.StringIO(), io.StringIO()
    charts = []

    try:
        _orig_savefig = plt.savefig
        plt.savefig = lambda *a, **kw: None
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(code, exec_globals)
        finally:
            plt.savefig = _orig_savefig

        fig = plt.gcf()
        if fig.get_axes():
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
            buf.seek(0)
            charts.append(base64.b64encode(buf.read()).decode("utf-8"))
            plt.close(fig)

        sys.stdout.write(json.dumps({
            "success": True,
            "output": out.getvalue(),
            "error": err.getvalue() or None,
            "charts": charts,
        }))
    except Exception as e:  # noqa: BLE001 — 兜底，错误以 JSON 返回
        sys.stdout.write(json.dumps({
            "success": False,
            "output": out.getvalue(),
            "error": str(e),
            "charts": [],
        }))


if __name__ == "__main__":
    main()
