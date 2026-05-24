from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router
from app.cache.redis import dispose_redis
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.vectorstore.milvus import dispose_milvus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings)
    log = structlog.get_logger()
    log.info("startup", app=settings.app_name, env=settings.env, version=__version__)
    try:
        yield
    finally:
        # 关停顺序无强依赖；逐个释放避免单点异常阻塞后续清理
        for name, closer in (
            ("db", dispose_engine),
            ("redis", dispose_redis),
            ("milvus", dispose_milvus),
        ):
            try:
                await closer()
            except Exception as exc:
                log.warning("dispose_failed", component=name, error=str(exc))
        log.info("shutdown", app=settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    return app


app = create_app()
