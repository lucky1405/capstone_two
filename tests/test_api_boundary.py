"""Tests for boundary validation: bad input -> clean 4xx, never 500 (Requirement 2)."""
import pytest


@pytest.mark.asyncio
async def test_negative_quantity_returns_422(client):
    """Negative quantity must be rejected at the boundary with 422, never a 500."""
    res = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": -10},
        headers={"X-Tenant-Id": "tenant_free"},
    )
    assert res.status_code == 422
    data = res.json()
    assert data["error"] == "validation_error"


@pytest.mark.asyncio
async def test_zero_quantity_returns_422(client):
    """Zero quantity must be rejected with 422."""
    res = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 0},
        headers={"X-Tenant-Id": "tenant_free"},
    )
    assert res.status_code == 422
    assert res.json()["error"] == "validation_error"


@pytest.mark.asyncio
async def test_invalid_usage_type_returns_422(client):
    """Invalid usage_type must be rejected with 422."""
    res = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "quantum_qubits", "quantity": 1},
        headers={"X-Tenant-Id": "tenant_free"},
    )
    assert res.status_code == 422
    assert res.json()["error"] == "validation_error"


@pytest.mark.asyncio
async def test_empty_prompt_generate_returns_422(client):
    """Empty string prompt on /generate must be rejected with 422."""
    res = await client.post(
        "/generate",
        json={"prompt": ""},
        headers={"X-Tenant-Id": "tenant_pro"},
    )
    assert res.status_code == 422
    assert res.json()["error"] == "validation_error"


@pytest.mark.asyncio
async def test_nonexistent_tenant_returns_404(client):
    """Non-existent tenant header must return 404 Not Found."""
    res = await client.post(
        "/api/v1/meter/record",
        json={"usage_type": "api_call", "quantity": 1},
        headers={"X-Tenant-Id": "tenant_does_not_exist_at_all"},
    )
    assert res.status_code == 404
    assert res.json()["error"] == "tenant_not_found"
