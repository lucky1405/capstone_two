"""Tests for AI token pricing, cached/reasoning rules, and integer math (Evaluator Probe 5)."""
import pytest
from app.core.pricing import (
    calculate_token_cost_micro_units,
    calculate_total_cost_micro_units,
    format_currency,
)


def test_token_pricing_isolated_math():
    """
    Directly tests that:
    - Cached input tokens are 75% cheaper than fresh input (125 vs 500 micro-units / 1k)
    - Reasoning tokens are priced at output token rate (1500 micro-units / 1k)
    - Categories cannot simply be summed
    - Pure integer math avoids float drift
    """
    # 1. Standard Input vs Cached Input
    in_cost = calculate_token_cost_micro_units(input_tokens=1000)
    cached_cost = calculate_token_cost_micro_units(cached_input_tokens=1000)
    assert in_cost == 500, f"Expected 500 micro-units, got {in_cost}"
    assert cached_cost == 125, f"Expected 125 micro-units, got {cached_cost}"
    assert cached_cost < in_cost
    assert cached_cost * 4 == in_cost  # Exactly 75% discount

    # 2. Output Tokens vs Reasoning Tokens
    out_cost = calculate_token_cost_micro_units(output_tokens=1000)
    reasoning_cost = calculate_token_cost_micro_units(reasoning_tokens=1000)
    assert out_cost == 1500, f"Expected 1500 micro-units, got {out_cost}"
    assert reasoning_cost == 1500, f"Expected 1500 micro-units, got {reasoning_cost}"
    assert out_cost == reasoning_cost, "Reasoning tokens must be billed at output rate"

    # 3. Non-trivial combined batch
    # 10k in (5000), 40k cached (5000), 2k out (3000), 1k reasoning (1500)
    combined = calculate_token_cost_micro_units(
        input_tokens=10000,
        cached_input_tokens=40000,
        output_tokens=2000,
        reasoning_tokens=1000,
    )
    expected_combined = 5000 + 5000 + 3000 + 1500
    assert combined == 14500, f"Expected {expected_combined}, got {combined}"
    assert isinstance(combined, int), "Calculation must be pure integer"


@pytest.mark.asyncio
async def test_probe_5_pricing_rules_and_usage_rollup_match(client):
    """
    PROBE 5: Check the pinned pricing rules -> cached-input and reasoning-token rules
    produce the exact expected totals; GET /usage matches.
    """
    headers = {"X-Tenant-Id": "tenant_pro"}

    # Record token usage with distinct modalities:
    # 10k fresh input, 40k cached input, 2k output, 1k reasoning tokens
    payload = {
        "usage_type": "ai_tokens",
        "quantity": 53000,
        "input_tokens": 10000,
        "cached_input_tokens": 40000,
        "output_tokens": 2000,
        "reasoning_tokens": 1000,
    }

    record_res = await client.post("/api/v1/meter/record", json=payload, headers=headers)
    assert record_res.status_code == 200
    rec_data = record_res.json()
    assert rec_data["cost_micro_units"] == 14500
    assert rec_data["formatted_cost"] == "$0.0145"

    # GET /usage should match the recorded amounts
    usage_res = await client.get("/usage", headers=headers)
    assert usage_res.status_code == 200
    usage_data = usage_res.json()

    assert usage_data["token_breakdown"]["input_tokens"] == 10000
    assert usage_data["token_breakdown"]["cached_input_tokens"] == 40000
    assert usage_data["token_breakdown"]["output_tokens"] == 2000
    assert usage_data["token_breakdown"]["reasoning_tokens"] == 1000
    assert usage_data["token_breakdown"]["total_tokens"] == 53000
    assert usage_data["total_cost_micro_units"] == 14500
    assert usage_data["formatted_total_cost"] == "$0.0145"
