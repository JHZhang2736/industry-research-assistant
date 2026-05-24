from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health_ok_when_db_reachable(client: TestClient) -> None:
    """DB 可达时 /health 返回 ok。"""
    with patch("app.api.health._probe_db", new=AsyncMock()) as probe:
        from app.api.health import DependencyStatus

        probe.return_value = DependencyStatus(status="ok")
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "industry-research-assistant"
    assert body["env"] in {"dev", "test", "prod"}
    assert body["version"]
    assert body["db"]["status"] == "ok"


def test_health_degraded_when_db_down(client: TestClient) -> None:
    """DB 不可达时 /health 返回 degraded，但仍 200。"""
    with patch("app.api.health._probe_db", new=AsyncMock()) as probe:
        from app.api.health import DependencyStatus

        probe.return_value = DependencyStatus(status="down", detail="OperationalError")
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"]["status"] == "down"
    assert body["db"]["detail"] == "OperationalError"
