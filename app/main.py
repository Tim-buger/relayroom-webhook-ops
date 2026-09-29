import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pythonjsonlogger.json import JsonFormatter

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Database
from app.models import Base


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    database = Database(settings)
    if settings.auto_create_schema:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    redis = await create_pool(RedisSettings(host=settings.redis_host, port=settings.redis_port))

    app.state.settings = settings
    app.state.database = database
    app.state.redis = redis
    app.state.simulator_mode = "failure"
    yield
    await redis.aclose()
    await database.dispose()


app = FastAPI(
    title="RelayRoom Webhook Operations API",
    description="Reliable webhook ingestion, delivery, retry, and recovery.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("relayroom.request").info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000),
        },
    )
    return response


app.include_router(router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def operations_console() -> FileResponse:
    return FileResponse("app/static/index.html")
