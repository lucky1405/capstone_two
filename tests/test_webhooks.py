"""Tests for Stripe webhook processing, signature verification, and deduplication (Evaluator Probes 3 & 4)."""
import json
import uuid
import pytest
from tests.conftest import generate_stripe_signature


@pytest.mark.asyncio
async def test_create_checkout_session_success(client):
    """Verifies that tenants can initiate a Stripe checkout session."""
    headers = {"X-Tenant-Id": "tenant_free"}
    payload = {
        "plan_id": "pro",
        "success_url": "https://example.com/success",
        "cancel_url": "https://example.com/cancel",
    }
    res = await client.post("/checkout/create-session", json=payload, headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "session_id" in data
    assert "checkout_url" in data
    assert data["tenant_id"] == "tenant_free"
    assert data["plan_id"] == "pro"


@pytest.mark.asyncio
async def test_probe_3_stripe_checkout_webhook_flips_free_to_pro(client):
    """
    PROBE 3: Complete a Stripe test Checkout -> the webhook flips the tenant Free -> Pro;
    GET /usage shows the new limits.
    """
    # 1. Verify tenant_free starts on Free tier (limit 1,000 calls, 100k tokens)
    usage_before = await client.get("/usage", headers={"X-Tenant-Id": "tenant_free"})
    assert usage_before.status_code == 200
    before_data = usage_before.json()
    assert before_data["plan_id"] == "free"
    assert before_data["api_calls"]["limit"] == 1000
    assert before_data["ai_tokens"]["limit"] == 100000

    # 2. Simulate Stripe checkout.session.completed webhook
    event_id = f"evt_checkout_{uuid.uuid4().hex}"
    webhook_payload = {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_test_{uuid.uuid4().hex[:10]}",
                "client_reference_id": "tenant_free",
                "customer": "cus_stripe_free_upgraded",
                "subscription": "sub_stripe_pro_active",
                "metadata": {"tenant_id": "tenant_free", "plan_id": "pro"},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    valid_sig = generate_stripe_signature(payload_bytes)

    webhook_res = await client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": valid_sig, "Content-Type": "application/json"},
    )
    assert webhook_res.status_code == 200, f"Webhook failed: {webhook_res.text}"
    assert webhook_res.json()["status"] == "success"

    # 3. Verify GET /usage reflects Pro plan and higher limits (50k calls, 5M tokens)
    usage_after = await client.get("/usage", headers={"X-Tenant-Id": "tenant_free"})
    assert usage_after.status_code == 200
    after_data = usage_after.json()
    assert after_data["plan_id"] == "pro"
    assert after_data["api_calls"]["limit"] == 50000
    assert after_data["ai_tokens"]["limit"] == 5000000


@pytest.mark.asyncio
async def test_probe_4_forged_webhook_signature_rejected_400(client):
    """
    PROBE 4 (Part 1): Send a forged webhook (bad signature) -> 400, nothing changes.
    """
    event_id = f"evt_forged_{uuid.uuid4().hex}"
    webhook_payload = {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "tenant_boundary",
                "customer": "cus_malicious",
                "subscription": "sub_malicious",
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    forged_sig = "t=1234567890,v1=bad_forged_hex_signature_abcdef123456"

    res = await client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": forged_sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_signature"

    # Confirm tenant_boundary was NOT changed
    usage_check = await client.get("/usage", headers={"X-Tenant-Id": "tenant_boundary"})
    assert usage_check.json()["plan_id"] == "free"


@pytest.mark.asyncio
async def test_probe_4_replay_real_event_twice_processed_once(client):
    """
    PROBE 4 (Part 2): Replay a real event twice -> processed once (deduplicated).
    """
    event_id = f"evt_replay_{uuid.uuid4().hex}"
    webhook_payload = {
        "id": event_id,
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_stripe_tenant_pro",
                "status": "active",
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    valid_sig = generate_stripe_signature(payload_bytes)

    # First delivery
    res_1 = await client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": valid_sig, "Content-Type": "application/json"},
    )
    assert res_1.status_code == 200
    assert res_1.json()["status"] == "success"

    # Replay of the exact same webhook event ID
    res_2 = await client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": valid_sig, "Content-Type": "application/json"},
    )
    assert res_2.status_code == 200
    assert res_2.json()["status"] == "ignored"
    assert "duplicate" in res_2.json()["message"].lower()
