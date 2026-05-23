from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from app import __version__
    from app.core.config import get_settings

    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        env=settings.env,
        version=__version__,
    )
