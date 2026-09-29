import asyncio
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import CrmRecord, EventStatus
from app.schemas import CrmRecordView, EventView, IngestResponse, SimulatorModeRequest
from app.security import InvalidSignature, verify_stripe_signature
from app.services.events import EventRepository

router = APIRouter()
repository = EventRepository()
VALID_SIMULATOR_MODES = {"success", "failure", "rejected", "timeout"}


@router.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "relayroom"}


@router.get("/api/v1/ready")
async def readiness(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        if not await request.app.state.redis.ping():
            raise RuntimeError("Redis did not respond")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dependencies unavailable") from exc
    return {"status": "ready", "database": "ok", "queue": "ok"}


@router.post(
    "/api/v1/webhooks/stripe",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_stripe_event(
    request: Request,
    stripe_signature: Annotated[str, Header(alias="Stripe-Signature")],
) -> IngestResponse:
    raw_body = await request.body()
    settings = request.app.state.settings
    if len(raw_body) > settings.max_payload_bytes:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds the size limit")
    try:
        verify_stripe_signature(
            raw_body,
            stripe_signature,
            settings.webhook_signing_secret,
            settings.signature_tolerance_seconds,
        )
    except InvalidSignature as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        payload = json.loads(raw_body)
        provider_event_id = str(payload["id"])
        event_type = str(payload["type"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Stripe event envelope") from exc

    async with request.app.state.database.session_factory() as session:
        event, duplicate = await repository.ingest(
            session, provider_event_id, event_type, payload
        )

    if not duplicate:
        await request.app.state.redis.enqueue_job(
            "deliver_event", str(event.id), _job_id=f"deliver:{event.id}"
        )
    return IngestResponse(
        event_id=event.id,
        provider_event_id=event.provider_event_id,
        status=event.status,
        duplicate=duplicate,
    )


@router.get("/api/v1/events", response_model=list[EventView])
async def list_events(
    request: Request,
    event_status: Annotated[EventStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EventView]:
    async with request.app.state.database.session_factory() as session:
        return await repository.list_recent(session, event_status, limit)


@router.post("/api/v1/events/{event_id}/replay", status_code=status.HTTP_202_ACCEPTED)
async def replay_event(event_id: UUID, request: Request) -> dict[str, str]:
    async with request.app.state.database.session_factory() as session:
        event = await repository.get(session, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if event.status != EventStatus.dead_letter:
            raise HTTPException(status_code=409, detail="Only dead-letter events can be replayed")
        event.status = EventStatus.pending
        await session.commit()

    await request.app.state.redis.enqueue_job(
        "deliver_event",
        str(event.id),
        _job_id=f"replay:{event.id}:{uuid4().hex[:8]}",
    )
    return {"status": "queued"}


@router.post("/api/v1/demo/events", response_model=IngestResponse)
async def create_demo_event(request: Request) -> IngestResponse:
    event_id = f"evt_demo_{uuid4().hex[:12]}"
    payload = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{uuid4().hex[:10]}",
                "customer_email": "maya@northwind.studio",
                "amount_total": 12900,
                "currency": "usd",
            }
        },
    }
    async with request.app.state.database.session_factory() as session:
        event, duplicate = await repository.ingest(
            session, event_id, payload["type"], payload
        )
    await request.app.state.redis.enqueue_job(
        "deliver_event", str(event.id), _job_id=f"deliver:{event.id}"
    )
    return IngestResponse(
        event_id=event.id,
        provider_event_id=event.provider_event_id,
        status=event.status,
        duplicate=duplicate,
    )


@router.put("/api/v1/demo/destination")
async def configure_simulator(payload: SimulatorModeRequest, request: Request) -> dict[str, str]:
    if payload.mode not in VALID_SIMULATOR_MODES:
        raise HTTPException(
            status_code=422,
            detail="Mode must be success, failure, rejected, or timeout",
        )
    request.app.state.simulator_mode = payload.mode
    return {"mode": payload.mode}


@router.get("/api/v1/demo/destination")
async def get_simulator_mode(request: Request) -> dict[str, str]:
    return {"mode": request.app.state.simulator_mode}


@router.post("/simulator/crm", include_in_schema=False)
async def crm_simulator(request: Request) -> Response:
    mode = request.app.state.simulator_mode
    if mode == "failure":
        return Response(status_code=503)
    if mode == "rejected":
        return Response(status_code=422)
    if mode == "timeout":
        await asyncio.sleep(request.app.state.settings.delivery_timeout_seconds + 1)

    payload = await request.json()
    source_event_id = request.headers.get("X-RelayRoom-Event") or str(payload.get("id", ""))
    if not source_event_id:
        return Response(status_code=422)
    customer = payload.get("data", {}).get("object", {})
    async with request.app.state.database.session_factory() as session:
        existing = await session.scalar(
            select(CrmRecord).where(CrmRecord.source_event_id == source_event_id)
        )
        if existing is None:
            session.add(
                CrmRecord(
                    source_event_id=source_event_id,
                    customer_email=customer.get("customer_email"),
                    amount_total=customer.get("amount_total"),
                    currency=customer.get("currency"),
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
    return Response(status_code=204)


@router.get("/api/v1/demo/crm-records", response_model=list[CrmRecordView])
async def list_crm_records(request: Request) -> list[CrmRecord]:
    async with request.app.state.database.session_factory() as session:
        records = await session.scalars(select(CrmRecord).order_by(CrmRecord.created_at.desc()))
        return list(records.all())
