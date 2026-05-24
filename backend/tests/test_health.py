"""/health 端点测试：mock 四个 probe 验证聚合状态。"""

from collections.abc import Iterator
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.health import DependencyStatus
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _patch_probes(
    db: DependencyStatus,
    redis: DependencyStatus,
    milvus: DependencyStatus,
    minio: DependencyStatus,
) -> ExitStack:
    """同时 mock 四个 probe，返回 ExitStack 让调用方控制生命周期。"""
    stack = ExitStack()
    stack.enter_context(patch("app.api.health._probe_db", new=AsyncMock(return_value=db)))
    stack.enter_context(patch("app.api.health._probe_redis", new=AsyncMock(return_value=redis)))
    stack.enter_context(patch("app.api.health._probe_milvus", new=AsyncMock(return_value=milvus)))
    stack.enter_context(patch("app.api.health._probe_minio", new=AsyncMock(return_value=minio)))
    return stack


def test_health_ok_when_all_deps_reachable(client: TestClient) -> None:
    with _patch_probes(
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok", detail="v2.4.17"),
        DependencyStatus(status="ok", detail="buckets=0"),
    ):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "industry-research-assistant"
    assert body["env"] in {"dev", "test", "prod"}
    assert body["version"]
    for dep in ("db", "redis", "milvus", "minio"):
        assert body[dep]["status"] == "ok"


def test_health_degraded_when_db_down(client: TestClient) -> None:
    with _patch_probes(
        DependencyStatus(status="down", detail="OperationalError"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
    ):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"]["status"] == "down"
    assert body["db"]["detail"] == "OperationalError"
    assert body["redis"]["status"] == "ok"


def test_health_degraded_when_redis_down(client: TestClient) -> None:
    with _patch_probes(
        DependencyStatus(status="ok"),
        DependencyStatus(status="down", detail="ConnectionError"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
    ):
        response = client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"]["status"] == "down"


def test_health_degraded_when_milvus_down(client: TestClient) -> None:
    with _patch_probes(
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="down", detail="MilvusException"),
        DependencyStatus(status="ok"),
    ):
        response = client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["milvus"]["status"] == "down"


def test_health_degraded_when_minio_down(client: TestClient) -> None:
    with _patch_probes(
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="ok"),
        DependencyStatus(status="down", detail="S3Error"),
    ):
        response = client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["minio"]["status"] == "down"
