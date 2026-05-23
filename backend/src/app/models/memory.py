from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._types import UUIDPK, CreatedAt


class LongTermMemory(Base):
    __tablename__ = "long_term_memories"

    id: Mapped[UUIDPK]
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_insights: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    milvus_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]
