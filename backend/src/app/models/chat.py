from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._types import UUIDPK, CreatedAt, UpdatedAt


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[UUIDPK]
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, default="chat")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[UUIDPK]
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text)
    references_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    image_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[CreatedAt]
