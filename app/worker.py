from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

import httpx
from arq.connections import RedisSettings
from arq.worker import Retry, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.models import DeliveryAttempt, EventStatus, WebhookEvent

RETRY_DELAYS_SECONDS = (2, 10, 30, 90, 300)


async def deliver_event(ctx: dict, event_id: str) -> None:
    database: Database = ctx["database"]
    settings: Settings = ctx["settings"]

    async with database.session_factory() as session:
        event = await session.get(WebhookEvent, UUID(event_id))
        if event is None or event.status == EventStatus.delivered:
            return

        event.attempt_count += 1
        attempt_number = event.attempt_count
        event.status = EventStatus.delivering
        await session.commit()

        started = perf_counter()
        status_code: int | None = None
        error: str | None = None
        retryable = False
        try:
            async with httpx.AsyncClient(timeout=settings.delivery_timeout_seconds) as client:
                response = await client.post(
                    settings.destination_url,
                    json=event.payload,
                    headers={
                        "X-RelayRoom-Event": event.provider_event_id,
                        "X-RelayRoom-Attempt": str(attempt_number),
                    },
                )
            status_code = response.status_code
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retryable = is_retryable_status(exc.response.status_code)
            error = _safe_error(exc)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            retryable = True
            error = _safe_error(exc)

        duration_ms = round((perf_counter() - started) * 1000)
        await _record_result(
            session,
            event,
            attempt_number,
            status_code,
            duration_ms,
            error,
            retryable,
            settings.max_delivery_attempts,
        )

        if error and retryable and event.status != EventStatus.dead_letter:
            delay = RETRY_DELAYS_SECONDS[min(attempt_number - 1, len(RETRY_DELAYS_SECONDS) - 1)]
            raise Retry(defer=delay)


async def _record_result(
    session: AsyncSession,
    event: WebhookEvent,
    attempt_number: int,
    status_code: int | None,
    duration_ms: int,
    error: str | None,
    retryable: bool,
    max_attempts: int,
) -> None:
    session.add(
        DeliveryAttempt(
            event_id=event.id,
            attempt_number=attempt_number,
            status_code=status_code,
            duration_ms=duration_ms,
            error=error,
        )
    )
    if error:
        event.last_error = error
        event.status = (
            EventStatus.dead_letter
            if not retryable or attempt_number >= max_attempts
            else EventStatus.retrying
        )
    else:
        event.status = EventStatus.delivered
        event.last_error = None
        event.delivered_at = datetime.now(UTC)
    await session.commit()


def is_retryable_status(status_code: int) -> bool:
    """Retry congestion/transient responses; fail fast for permanent client errors."""
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"destination returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "destination timed out"
    return "destination connection failed"


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["database"] = Database(settings)


async def shutdown(ctx: dict) -> None:
    await ctx["database"].dispose()


settings = get_settings()


class WorkerSettings:
    functions = [func(deliver_event, max_tries=settings.max_delivery_attempts)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    job_timeout = 30
