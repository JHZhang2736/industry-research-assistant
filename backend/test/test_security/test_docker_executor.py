import pytest

from app.service.deep_research_v2.security.docker_executor import DockerCodeExecutor


def _docker_available() -> bool:
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:
        return False


docker_required = pytest.mark.skipif(not _docker_available(), reason="需要 Docker 守护进程")


def test_constructs_with_config():
    ex = DockerCodeExecutor(image="industry-research-sandbox:latest", timeout=15)
    assert ex.image == "industry-research-sandbox:latest"
    assert ex.timeout == 15


@docker_required
def test_executes_chart_code():
    ex = DockerCodeExecutor(image="industry-research-sandbox:latest", timeout=60)
    code = (
        "data = {'Year': [2020, 2021], 'Value': [100, 200]}\n"
        "df = pd.DataFrame(data)\n"
        "plt.figure()\nplt.plot(df['Year'], df['Value'])\n"
    )
    result = ex.execute(code)
    assert result["success"] is True
    assert len(result["charts"]) == 1


@docker_required
def test_infinite_loop_times_out():
    ex = DockerCodeExecutor(image="industry-research-sandbox:latest", timeout=5)
    result = ex.execute("while True:\n    pass\n")
    assert result["success"] is False
    assert "timeout" in (result.get("error") or "").lower()


@docker_required
def test_network_is_disabled():
    ex = DockerCodeExecutor(image="industry-research-sandbox:latest", timeout=30)
    code = (
        "import urllib.request\n"
        "urllib.request.urlopen('http://example.com', timeout=3)\n"
    )
    result = ex.execute(code)
    assert result["success"] is False  # 无网络，连接失败
