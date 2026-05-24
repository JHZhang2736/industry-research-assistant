"""initial schema: 6 业务表 + updated_at 触发器

Revision ID: 0001
Revises:
Create Date: 2026-05-24

业务表清单：
- users
- chat_sessions
- chat_messages
- knowledge_bases
- documents
- long_term_memories

PG 内置 gen_random_uuid()（13+），无需 uuid-ossp 扩展。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPDATED_AT_FUNC_SQL = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

UPDATED_AT_FUNC_DROP_SQL = "DROP FUNCTION IF EXISTS update_updated_at_column();"

TABLES_WITH_UPDATED_AT = (
    "users",
    "chat_sessions",
    "knowledge_bases",
    "documents",
)


def upgrade() -> None:
    # ---------- users ----------
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("email", sa.String(100), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # ---------- chat_sessions ----------
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False, server_default="新对话"),
        sa.Column("session_type", sa.String(50), nullable=False, server_default="chat"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    # ---------- chat_messages ----------
    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("thinking", sa.Text, nullable=True),
        sa.Column("references_data", JSONB, nullable=True),
        sa.Column("image_results", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # ---------- knowledge_bases ----------
    op.create_table(
        "knowledge_bases",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("document_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_knowledge_bases_user_id", "knowledge_bases", ["user_id"])

    # ---------- documents ----------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "knowledge_base_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("file_size", sa.BigInteger, nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_documents_knowledge_base_id", "documents", ["knowledge_base_id"])
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_status", "documents", ["status"])

    # ---------- long_term_memories ----------
    op.create_table(
        "long_term_memories",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("key_insights", JSONB, nullable=True),
        sa.Column("milvus_ids", ARRAY(sa.Text), nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_long_term_memories_user_id", "long_term_memories", ["user_id"])
    op.create_index("ix_long_term_memories_session_id", "long_term_memories", ["session_id"])

    # ---------- updated_at 触发器 ----------
    op.execute(UPDATED_AT_FUNC_SQL)
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at "
            f"BEFORE UPDATE ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION update_updated_at_column();"
        )


def downgrade() -> None:
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute(UPDATED_AT_FUNC_DROP_SQL)

    op.drop_table("long_term_memories")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("users")
