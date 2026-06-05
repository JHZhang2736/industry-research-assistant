import pytest
from unittest.mock import MagicMock

from app.service.deep_research_v2.agents.wizard import CodeWizard
from app.config import llm_config


@pytest.fixture
def wizard():
    return CodeWizard(llm_api_key="k", llm_base_url="http://x", model="deepseek-v3.2")


def test_backend_runtime_image_installs_cjk_font_package():
    from pathlib import Path

    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    assert "fonts-wqy-zenhei" in dockerfile.read_text(encoding="utf-8")


def test_inprocess_sandbox_configures_cjk_font_stack(monkeypatch):
    from app.service.deep_research_v2.agents import wizard as wizard_module

    monkeypatch.setattr(
        wizard_module,
        "_available_font_families",
        lambda: {"WenQuanYi Zen Hei", "Microsoft YaHei", "DejaVu Sans"},
    )

    configure_fonts = getattr(wizard_module, "_configure_matplotlib_for_chinese", None)
    assert callable(configure_fonts)

    class FakePlot:
        rcParams = {}

    configure_fonts(FakePlot)

    fonts = FakePlot.rcParams["font.sans-serif"]
    assert fonts[0] == "WenQuanYi Zen Hei"
    assert "Microsoft YaHei" in fonts
    assert FakePlot.rcParams["axes.unicode_minus"] is False


def test_inprocess_sandbox_filters_missing_cjk_fonts(monkeypatch):
    from app.service.deep_research_v2.agents import wizard as wizard_module

    monkeypatch.setattr(
        wizard_module,
        "_available_font_families",
        lambda: {"Microsoft YaHei", "DejaVu Sans"},
    )

    class FakePlot:
        rcParams = {}

    wizard_module._configure_matplotlib_for_chinese(FakePlot)

    fonts = FakePlot.rcParams["font.sans-serif"]
    assert fonts[0] == "Microsoft YaHei"
    assert "WenQuanYi Zen Hei" not in fonts
    assert fonts[-1] == "DejaVu Sans"


def test_inprocess_sandbox_applies_resolved_fonts_to_existing_text(monkeypatch):
    from app.service.deep_research_v2.agents import wizard as wizard_module

    monkeypatch.setattr(
        wizard_module,
        "_available_font_families",
        lambda: {"Microsoft YaHei", "DejaVu Sans"},
    )

    applied = []

    class FakeText:
        def set_fontfamily(self, fonts):
            applied.append(fonts)

    class FakeAxis:
        label = FakeText()

    class FakeAxes:
        title = FakeText()
        xaxis = FakeAxis()
        yaxis = FakeAxis()

        def get_xticklabels(self):
            return [FakeText()]

        def get_yticklabels(self):
            return [FakeText()]

        def get_title(self):
            return "title"

        def get_xlabel(self):
            return "x"

        def get_ylabel(self):
            return "y"

    class FakeFigure:
        def get_axes(self):
            return [FakeAxes()]

    apply_fonts = getattr(wizard_module, "_apply_chinese_fonts_to_figure", None)
    assert callable(apply_fonts)

    apply_fonts(FakeFigure())

    assert applied
    assert all(fonts == ["Microsoft YaHei", "DejaVu Sans"] for fonts in applied)


@pytest.mark.asyncio
async def test_docker_mode_uses_docker_executor(wizard, monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    llm_config.reload_config()

    fake = MagicMock(return_value={"success": True, "output": "", "error": None, "charts": ["B64"]})

    class FakeExecutor:
        def __init__(self, *a, **k):
            pass
        execute = fake

    monkeypatch.setattr(
        "app.service.deep_research_v2.security.docker_executor.DockerCodeExecutor",
        FakeExecutor,
    )

    code = "data = {'a':[1,2,3]}\ndf = pd.DataFrame(data)\nplt.figure()\nplt.plot(df['a'])\n"
    result = await wizard._execute_code(code)

    assert result["success"] is True
    assert result["charts"] == ["B64"]
    fake.assert_called_once()


@pytest.mark.asyncio
async def test_inprocess_mode_uses_in_process_sandbox(wizard, monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "inprocess")
    llm_config.reload_config()

    called = {"inproc": False}
    orig = wizard._execute_in_sandbox

    def spy(code):
        called["inproc"] = True
        return orig(code)

    monkeypatch.setattr(wizard, "_execute_in_sandbox", spy)

    code = "data = {'a':[1,2,3]}\ndf = pd.DataFrame(data)\nplt.figure()\nplt.plot(df['a'])\n"
    result = await wizard._execute_code(code)

    assert called["inproc"] is True
    assert result["success"] is True


@pytest.fixture(autouse=True)
def _restore_config():
    yield
    import os
    os.environ.pop("SANDBOX_MODE", None)
    llm_config.reload_config()
