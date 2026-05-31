import pytest
from unittest.mock import MagicMock

from app.service.deep_research_v2.agents.wizard import CodeWizard
from app.config import llm_config


@pytest.fixture
def wizard():
    return CodeWizard(llm_api_key="k", llm_base_url="http://x", model="deepseek-v3.2")


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
