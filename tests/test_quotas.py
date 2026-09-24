"""Tests for quota boundary honesty and status codes (Evaluator Probe 2)."""
import pytest


@pytest.mark.asyncio
async def test_probe_2_exact_quota_boundary_behavior(client):
    """
    PROBE 2: Drive a tenant to its exact quota -> the request at the boundary behaves
    per documented rule; the one after returns 429 / 402 with a clear message.
    
    tenant_boundary is seeded with exactly 999 calls (out of 1,000 Free quota).
    """
    headers = {"X-Tenant-Id": "tenant_boundary"}

    # 1. The boundary request: 999 + 1 = 1000 calls (exact limit).
    # Per documented rule, this is the final permitted request.
    boundary_req = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 1},
        headers=headers,
    )
    assert boundary_req.status_code == 200, f"Expected 200 at boundary, got {boundary_req.text}"
    boundary_data = boundary_req.json()
    assert boundary_data["quota_used"] == 1000
    assert boundary_data["quota_remaining"] == 0

    # 2. The subsequent request: 1000 + 1 = 1001 calls (> 1000 limit).
    # Must be rejected with 429 Too Many Requests.
    exceeded_req = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 1},
        headers=headers,
    )
    assert exceeded_req.status_code == 429, f"Expected 429, got {exceeded_req.status_code}"
    exceeded_data = exceeded_req.json()
    assert exceeded_data["error"] == "quota_exceeded"
    assert "exceeded" in exceeded_data["message"].lower()
    assert exceeded_data["details"]["current_usage"] == 1000
    assert exceeded_data["details"]["limit"] == 1000
    assert "Retry-After" in exceeded_req.headers


@pytest.mark.asyncio
async def test_probe_2_payment_required_status_402(client):
    """
    Verifies that a tenant whose subscription is delinquent or past_due
    receives HTTP 402 Payment Required.
    """
    headers = {"X-Tenant-Id": "tenant_past_due"}
    req = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 1},
        headers=headers,
    )
    assert req.status_code == 402, f"Expected 402 Payment Required, got {req.status_code}"
    data = req.json()
    assert data["error"] == "payment_required"
    assert "past_due" in data["message"] or data["details"]["reason"] == "subscription_past_due"


@pytest.mark.asyncio
async def test_ai_tokens_quota_exhaustion_429(client):
    """Verifies that exceeding the AI token limit on Free tier triggers 429."""
    headers = {"X-Tenant-Id": "tenant_free"}
    # Free tier limit is 100,000 tokens
    req = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "ai_tokens", "quantity": 100001},
        headers=headers,
    )
    assert req.status_code == 429
    assert req.json()["error"] == "quota_exceeded"
