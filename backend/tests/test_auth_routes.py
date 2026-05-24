"""认证路由集成测试：注册 / 登录 / 当前用户。

走真实 PG（conftest 的 db_session fixture 提供事务回滚隔离）。
使用 httpx.AsyncClient + ASGITransport，确保 HTTP 请求和 DB 操作同 loop。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _register_payload(**override: object) -> dict[str, object]:
    base: dict[str, object] = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "Passw0rd!",
    }
    base.update(override)
    return base


# ---------- register ----------


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json=_register_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"]
    assert body["user"]["username"] == "alice"
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["is_active"] is True
    assert "hashed_password" not in body["user"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient) -> None:
    await client.post("/auth/register", json=_register_payload())
    resp = await client.post("/auth/register", json=_register_payload(email="alice2@example.com"))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    await client.post("/auth/register", json=_register_payload())
    resp = await client.post("/auth/register", json=_register_payload(username="bob"))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json=_register_payload(password="alllettersnodigit"))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json=_register_payload(password="ab1"))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json=_register_payload(email="not-an-email"))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_username_chars(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json=_register_payload(username="ali ce"))
    assert resp.status_code == 422


# ---------- login ----------


@pytest.mark.asyncio
async def test_login_with_username(client: AsyncClient) -> None:
    await client.post("/auth/register", json=_register_payload())
    resp = await client.post("/auth/login", json={"account": "alice", "password": "Passw0rd!"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


@pytest.mark.asyncio
async def test_login_with_email(client: AsyncClient) -> None:
    await client.post("/auth/register", json=_register_payload())
    resp = await client.post(
        "/auth/login", json={"account": "alice@example.com", "password": "Passw0rd!"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    await client.post("/auth/register", json=_register_payload())
    resp = await client.post("/auth/login", json={"account": "alice", "password": "WrongPw123"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient) -> None:
    resp = await client.post("/auth/login", json={"account": "ghost", "password": "Passw0rd!"})
    assert resp.status_code == 401


# ---------- me ----------


@pytest.mark.asyncio
async def test_me_without_token(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient) -> None:
    resp = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient) -> None:
    reg = await client.post("/auth/register", json=_register_payload())
    token = reg.json()["access_token"]
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
