import os
import sys
import json
import subprocess
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"


def _run(code: str) -> dict:
    env = dict(os.environ, SANDBOX_CODE=code, MPLCONFIGDIR="/tmp" if os.name != "nt" else os.environ.get("TEMP", "."))
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    last_line = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    return json.loads(last_line)


def test_runner_returns_chart_base64():
    code = (
        "data = {'Year': [2020, 2021, 2022], 'Value': [100, 150, 200]}\n"
        "df = pd.DataFrame(data)\n"
        "plt.figure()\n"
        "plt.plot(df['Year'], df['Value'])\n"
    )
    out = _run(code)
    assert out["success"] is True
    assert len(out["charts"]) == 1
    assert len(out["charts"][0]) > 100  # base64 非空


def test_runner_reports_error_without_crashing():
    out = _run("raise ValueError('boom')")
    assert out["success"] is False
    assert "boom" in out["error"]
    assert out["charts"] == []


def test_runner_captures_stdout():
    out = _run("print('hello-sandbox')")
    assert out["success"] is True
    assert "hello-sandbox" in out["output"]
