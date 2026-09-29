import json

from app.security import create_demo_signature


def signed_request(client, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = create_demo_signature(body, "whsec_test")
    return client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["service"] == "relayroom"


def test_operations_console_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Delivery operations" in response.text


def test_readiness_checks_database_and_queue(client):
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "queue": "ok"}


def test_response_has_request_correlation_id(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req_customer_42"})

    assert response.headers["X-Request-ID"] == "req_customer_42"


def test_rejects_oversized_webhook_before_processing(client, monkeypatch):
    client.app.state.settings.max_payload_bytes = 10
    response = signed_request(
        client,
        {"id": "evt_too_large", "type": "invoice.paid", "data": {"object": {}}},
    )

    assert response.status_code == 413


def test_ingests_and_enqueues_signed_event(client, fake_redis):
    response = signed_request(
        client,
        {"id": "evt_paid_001", "type": "checkout.session.completed", "data": {"object": {}}},
    )

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert response.json()["status"] == "pending"
    assert fake_redis.jobs[0][0] == "deliver_event"


def test_duplicate_is_safe_and_not_enqueued_twice(client, fake_redis):
    payload = {"id": "evt_duplicate_001", "type": "charge.refunded", "data": {"object": {}}}

    first = signed_request(client, payload)
    second = signed_request(client, payload)

    assert first.status_code == second.status_code == 202
    assert second.json()["duplicate"] is True
    matching_jobs = [job for job in fake_redis.jobs if second.json()["event_id"] in job[1]]
    assert len(matching_jobs) == 1


def test_rejects_invalid_signature(client):
    response = client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_bad","type":"charge.failed"}',
        headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bad"},
    )

    assert response.status_code == 400


def test_lists_ingested_events(client):
    signed_request(
        client,
        {"id": "evt_list_001", "type": "payment_intent.succeeded", "data": {"object": {}}},
    )

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    assert response.json()[0]["provider_event_id"] == "evt_list_001"


def test_only_dead_letter_events_can_be_manually_replayed(client):
    created = signed_request(
        client,
        {"id": "evt_pending_001", "type": "invoice.paid", "data": {"object": {}}},
    )

    response = client.post(f"/api/v1/events/{created.json()['event_id']}/replay")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only dead-letter events can be replayed"


def test_crm_simulator_applies_business_effect_once(client):
    client.put("/api/v1/demo/destination", json={"mode": "success"})
    payload = {
        "id": "evt_crm_once",
        "data": {
            "object": {
                "customer_email": "client@example.com",
                "amount_total": 4200,
                "currency": "usd",
            }
        },
    }
    headers = {"X-RelayRoom-Event": "evt_crm_once"}

    first = client.post("/simulator/crm", json=payload, headers=headers)
    second = client.post("/simulator/crm", json=payload, headers=headers)
    records = client.get("/api/v1/demo/crm-records")

    assert first.status_code == second.status_code == 204
    assert len(records.json()) == 1
    assert records.json()[0]["source_event_id"] == "evt_crm_once"
