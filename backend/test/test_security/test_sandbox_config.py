from app.config.llm_config import reload_config


def test_sandbox_defaults_to_inprocess(monkeypatch):
    for k in ("SANDBOX_MODE", "SANDBOX_IMAGE", "SANDBOX_MEM",
              "SANDBOX_CPUS", "SANDBOX_PIDS", "SANDBOX_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    cfg = reload_config()
    assert cfg.sandbox.mode == "inprocess"
    assert cfg.sandbox.image == "industry-research-sandbox:latest"
    assert cfg.sandbox.mem_limit == "512m"
    assert cfg.sandbox.timeout == 30


def test_sandbox_reads_env(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    monkeypatch.setenv("SANDBOX_TIMEOUT", "45")
    monkeypatch.setenv("SANDBOX_CPUS", "2.0")
    cfg = reload_config()
    assert cfg.sandbox.mode == "docker"
    assert cfg.sandbox.timeout == 45
    assert cfg.sandbox.cpus == 2.0
