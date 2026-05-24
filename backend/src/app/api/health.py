from typing import Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


class DependencyStatus(BaseModel):
    status: Literal["ok", "down"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    env: str
    version: str
    db: DependencyStatus


async def _probe_db() -> DependencyStatus:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return DependencyStatus(status="ok")
    except SQLAlchemyError as exc:
        log.warning("db_health_probe_failed", error=str(exc))
        return DependencyStatus(status="down", detail=exc.__class__.__name__)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    db_status = await _probe_db()
    overall: Literal["ok", "degraded"] = "ok" if db_status.status == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        app=settings.app_name,
        env=settings.env,
        version=__version__,
        db=db_status,
    )
