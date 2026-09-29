from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EventStatus(StrEnum):
    pending = "pending"
    delivering = "delivering"
    delivered = "delivered"
    retrying = "retrying"
    dead_letter = "dead_letter"


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(40), default="stripe")
    provider_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, native_enum=False), default=EventStatus.pending, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[list["DeliveryAttempt"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="DeliveryAttempt.started_at"
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("webhook_events.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    event: Mapped[WebhookEvent] = relationship(back_populates="attempts")


class CrmRecord(Base):
    """A tiny stand-in for the downstream business side effect.

    The unique source event id demonstrates the part webhook demos often omit:
    retries may redeliver, but the business action must still happen once.
    """

    __tablename__ = "crm_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    amount_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
