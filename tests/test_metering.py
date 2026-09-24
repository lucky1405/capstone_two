"""Tests for idempotent metering and duplicate prevention (Evaluator Probe 1)."""
import uuid
import pytest
import aiosqlite
from app.db.connection import get_db_connection


@pytest.mark.asyncio
async def test_probe_1_idempotent_metering_duplicate_prevention(client, test_db):
    """
    PROBE 1: Send the same billable request twice with one idempotency key
    -> exactly one usage event; the second response mirrors the first.
    """
    idempotency_key = f"key_probe_1_{uuid.uuid4().hex}"
    headers = {
        "X-Tenant-Id": "tenant_free",
        "Idempotency-Key": idempotency_key,
    }
    payload = {
        "usage_type": "api_call",
        "quantity": 1,
    }

    # Count initial events for tenant_free
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) as count FROM usage_events WHERE tenant_id = 'tenant_free'"
        )
        initial_count = (await cursor.fetchone())["count"]

    # 1. First Request
    response_1 = await client.post("/api/v1/meter/record", json=payload, headers=headers)
    assert response_1.status_code == 200, f"Expected 200, got {response_1.text}"
    data_1 = response_1.json()
    assert data_1["success"] is True
    assert data_1["idempotent_replay"] is False
    assert response_1.headers.get("X-Idempotent-Replay") == "false"
    first_event_id = data_1["event_id"]

    # Verify event count increased by exactly 1
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) as count FROM usage_events WHERE tenant_id = 'tenant_free'"
        )
        count_after_first = (await cursor.fetchone())["count"]
        assert count_after_first == initial_count + 1

    # 2. Second Request (Replay with same idempotency key)
    response_2 = await client.post("/api/v1/meter/record", json=payload, headers=headers)
    assert response_2.status_code == 200, f"Expected 200, got {response_2.text}"
    data_2 = response_2.json()

    # The second response must mirror the first
    assert data_2["event_id"] == first_event_id
    assert data_2["cost_micro_units"] == data_1["cost_micro_units"]
    assert data_2["quota_used"] == data_1["quota_used"]
    assert data_2["idempotent_replay"] is True
    assert response_2.headers.get("X-Idempotent-Replay") == "true"

    # Verify event count in database DID NOT increase
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) as count FROM usage_events WHERE tenant_id = 'tenant_free'"
        )
        count_after_second = (await cursor.fetchone())["count"]
        assert count_after_second == count_after_first, "Duplicate usage event was created!"


@pytest.mark.asyncio
async def test_idempotent_generate_endpoint_replays(client, test_db):
    """Verifies that the /generate simulated AI endpoint is also strictly idempotent."""
    idempotency_key = f"key_gen_{uuid.uuid4().hex}"
    headers = {
        "X-Tenant-Id": "tenant_pro",
        "Idempotency-Key": idempotency_key,
    }
    payload = {
        "prompt": "Analyze market trends in usage metering.",
        "input_tokens": 150,
        "cached_input_tokens": 50,
        "output_tokens": 75,
        "reasoning_tokens": 25,
    }

    # First call
    res_1 = await client.post("/generate", json=payload, headers=headers)
    assert res_1.status_code == 200
    body_1 = res_1.json()
    assert body_1["idempotent_replay"] is False

    # Second call (replay)
    res_2 = await client.post("/generate", json=payload, headers=headers)
    assert res_2.status_code == 200
    body_2 = res_2.json()
    assert body_2["idempotent_replay"] is True
    assert body_2["event_id"] == body_1["event_id"]
    assert body_2["cost"]["cost_micro_units"] == body_1["cost"]["cost_micro_units"]


@pytest.mark.asyncio
async def test_idempotency_key_payload_conflict(client):
    """
    Reusing an Idempotency-Key with a different payload must return 409 Conflict.
    """
    key = f"key_conflict_{uuid.uuid4().hex}"
    headers = {"X-Tenant-Id": "tenant_pro", "Idempotency-Key": key}

    # Request A
    res_a = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 1},
        headers=headers,
    )
    assert res_a.status_code == 200

    # Request B with different quantity on same key
    res_b = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 5},
        headers=headers,
    )
    assert res_b.status_code == 409
    assert res_b.json()["error"] == "idempotency_conflict"
