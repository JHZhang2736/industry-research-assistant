"""长期记忆管理路由（mem0 后端）"""
from typing import List
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from models.user import User
from router.auth_router import get_current_user_required
from service.memory_engine import get_memory_engine

router = APIRouter(prefix="/memories", tags=["长期记忆"])


class MemoryItem(BaseModel):
    id: str
    content: str
    type: str = Field(..., description="preference / sop / unknown")


class MemoryListResponse(BaseModel):
    memories: List[MemoryItem] = Field(default_factory=list)
    total: int = 0


@router.get("", response_model=MemoryListResponse)
async def get_memories(current_user: User = Depends(get_current_user_required)):
    """列出当前用户的长期记忆（来自 mem0）。"""
    engine = get_memory_engine()
    items = engine.list_memories(str(current_user.id)) if engine else []
    return MemoryListResponse(
        memories=[MemoryItem(**it) for it in items],
        total=len(items),
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user_required),
):
    """删除一条记忆。"""
    engine = get_memory_engine()
    if engine:
        engine.delete_memory(memory_id)
    return None
