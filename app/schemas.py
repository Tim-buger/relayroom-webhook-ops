from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import EventStatus


class IngestResponse(BaseModel):
    event_id: UUID
    provider_event_id: str
    status: EventStatus
    duplicate: bool


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_number: int
    status_code: int | None
    duration_ms: int
    error: str | None
    started_at: datetime


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    provider_event_id: str
    event_type: str
    status: EventStatus
    payload: dict
    attempt_count: int
    last_error: str | None
    received_at: datetime
    delivered_at: datetime | None
    attempts: list[AttemptView] = Field(default_factory=list)


class CrmRecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_event_id: str
    customer_email: str | None
    amount_total: int | None
    currency: str | None
    created_at: datetime


class SimulatorModeRequest(BaseModel):
    mode: str
