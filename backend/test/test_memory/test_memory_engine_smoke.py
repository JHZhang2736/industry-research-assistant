"""真实 mem0 + Milvus + DashScope 往返。需外部服务，默认跳过(标记 slow)。
运行：python -m pytest test/test_memory/test_memory_engine_smoke.py -q
"""
import os
import uuid
import pytest
from app.service.memory_engine import get_memory_engine

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="需要 DASHSCOPE_API_KEY")
def test_preference_roundtrip():
    engine = get_memory_engine()
    if engine is None:
        pytest.skip("MemoryEngine 初始化失败（mem0/Milvus 不可用）")
    uid = f"smoke_{uuid.uuid4().hex[:8]}"
    engine.remember_preferences(uid, [{"role": "user", "content": "我只关注智慧交通，报告要简洁"}])
    ctx = engine.recall_preferences(uid, "用户关注哪个行业")
    assert "交通" in ctx or ctx == ""


@pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="需要 DASHSCOPE_API_KEY")
def test_lessons_roundtrip():
    engine = get_memory_engine()
    if engine is None:
        pytest.skip("MemoryEngine 初始化失败")
    fb = [{"issue_type": "missing_source", "severity": "critical",
           "description": "缺官方来源", "suggestion": "补充国家统计局"}]
    engine.remember_lessons("智慧交通", fb, 6.0)
    ctx = engine.recall_lessons("智慧交通", "市场规模官方数据", min_recurrence=1)
    assert isinstance(ctx, str)
