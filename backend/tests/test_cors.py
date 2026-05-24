"""CORS 中间件行为测试。

中间件层测试，使用 anon_client（不依赖 DB），避免与业务测试耦合。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_preflight_request_from_allowed_origin(anon_client: AsyncClient) -> None:
    """OPTIONS 预检从白名单 Origin 发起应返回 200 + ACL 头。"""
    resp = await anon_client.options(
        "/auth/register",
        headers={
            "Origin": "http://localhost:5183",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5183"
    assert "POST" in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_preflight_disallowed_origin_lacks_acl_header(anon_client: AsyncClient) -> None:
    """不在白名单的 Origin 不会被授予 Access-Control-Allow-Origin（浏览器据此拒绝）。"""
    resp = await anon_client.options(
        "/auth/register",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example.com"
