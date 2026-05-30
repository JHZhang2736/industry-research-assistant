"""一次性 DB 同步：为 chat_sessions 加记忆压缩列、删除旧 long_term_memories 表。
create_all 不会 ALTER 既有表，故手动执行。幂等。

运行：python -m app.scripts.sync_memory_schema
"""
from sqlalchemy import text
try:
    from app.core.database import engine
except ImportError:
    from core.database import engine

DDL = [
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_summary TEXT",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summarized_up_to INTEGER DEFAULT 0",
    "DROP TABLE IF EXISTS long_term_memories CASCADE",
]


def main():
    with engine.begin() as conn:
        for stmt in DDL:
            print(f"执行: {stmt}")
            conn.execute(text(stmt))
    print("DB 同步完成。")


if __name__ == "__main__":
    main()
