"""演示：同一行业连写两次教训/偏好后，第二次召回到记忆。
运行：python -m app.scripts.demo_memory
"""
from app.service.memory_engine import get_memory_engine, classify_industry


def main():
    engine = get_memory_engine()
    if engine is None:
        print("MemoryEngine 不可用（检查 mem0/Milvus/DASHSCOPE_API_KEY）")
        return
    uid = "demo_user"
    industry = classify_industry("智慧交通市场规模与车路协同")
    print(f"行业判定: {industry}")

    engine.remember_preferences(uid, [{"role": "user", "content": "我只看智慧交通，报告要简洁，多用数据"}])
    engine.remember_lessons(industry, [
        {"issue_type": "missing_source", "description": "渗透率无官方源", "suggestion": "用国家统计局口径"},
    ], quality_score=6.0)

    print("\n--- 第二次研究 Planner 会拿到 ---")
    print(engine.recall_preferences(uid, "智慧交通 2025 趋势"))
    print(engine.recall_lessons(industry, "智慧交通 市场规模 官方数据", min_recurrence=1))


if __name__ == "__main__":
    main()
