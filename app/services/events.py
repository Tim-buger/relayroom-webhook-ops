from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import EventStatus, WebhookEvent


class EventRepository:
    async def ingest(
        self,
        session: AsyncSession,
        provider_event_id: str,
        event_type: str,
        payload: dict,
    ) -> tuple[WebhookEvent, bool]:
        existing = await session.scalar(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == provider_event_id)
        )
        if existing:
            return existing, True

        event = WebhookEvent(
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload=payload,
        )
        session.add(event)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(WebhookEvent).where(WebhookEvent.provider_event_id == provider_event_id)
            )
            if existing is None:
                raise
            return existing, True
        await session.refresh(event)
        return event, False

    async def list_recent(
        self, session: AsyncSession, status: EventStatus | None, limit: int
    ) -> list[WebhookEvent]:
        statement = (
            select(WebhookEvent)
            .options(selectinload(WebhookEvent.attempts))
            .order_by(WebhookEvent.received_at.desc())
            .limit(limit)
        )
        if status:
            statement = statement.where(WebhookEvent.status == status)
        return list((await session.scalars(statement)).unique().all())

    async def get(self, session: AsyncSession, event_id: UUID) -> WebhookEvent | None:
        return await session.scalar(
            select(WebhookEvent)
            .options(selectinload(WebhookEvent.attempts))
            .where(WebhookEvent.id == event_id)
        )
