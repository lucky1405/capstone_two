"""High-precision, float-free pricing calculations for AI tokens and API usage."""
from typing import Dict, Any
from app.config import settings


def calculate_token_cost_micro_units(
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> int:
    """
    Calculates AI token cost strictly using integer math in micro-units ($10^-6 USD).
    
    Pricing rules:
    - Standard input tokens: 500 micro-units per 1,000 tokens ($0.50 / 1M)
    - Cached input tokens:   125 micro-units per 1,000 tokens ($0.125 / 1M, 75% discount)
    - Output tokens:         1,500 micro-units per 1,000 tokens ($1.50 / 1M)
    - Reasoning tokens:      1,500 micro-units per 1,000 tokens (billed at output rate)
    
    Formula:
    cost_micro_units = (in * 500 + cached * 125 + out * 1500 + reasoning * 1500) // 1000
    """
    total_scaled = (
        int(input_tokens) * settings.PRICING.INPUT_RATE_PER_1K
        + int(cached_input_tokens) * settings.PRICING.CACHED_INPUT_RATE_PER_1K
        + int(output_tokens) * settings.PRICING.OUTPUT_RATE_PER_1K
        + int(reasoning_tokens) * settings.PRICING.REASONING_RATE_PER_1K
    )
    return total_scaled // 1000


def calculate_total_cost_micro_units(
    api_calls: int = 0,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> int:
    """Calculates total usage cost combining API calls and all token modalities."""
    token_cost = calculate_token_cost_micro_units(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
    )
    api_cost = int(api_calls) * settings.PRICING.API_CALL_UNIT_COST
    return token_cost + api_cost


def micro_units_to_cents(micro_units: int) -> int:
    """Converts micro-units ($10^-6 USD) to integer cents (1 cent = 10,000 micro-units)."""
    return micro_units // 10000


def format_currency(micro_units: int) -> str:
    """
    Formats micro-units into a human-readable USD string.
    Example: 1,875 micro-units -> '$0.001875', 29,000,000 micro-units -> '$29.00'
    """
    dollars = micro_units // 1_000_000
    remainder = abs(micro_units % 1_000_000)
    
    if remainder == 0:
        return f"${dollars}.00"
    
    # Format with up to 6 decimal places, stripping trailing zeros beyond 2 decimals
    cents = remainder // 10000
    fraction = f"{remainder:06d}".rstrip("0")
    if len(fraction) < 2:
        fraction = f"{cents:02d}"
    return f"${dollars}.{fraction}"


def get_token_breakdown_dict(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
) -> Dict[str, Any]:
    """Generates an itemized breakdown of token usage and associated costs."""
    cost_input = (input_tokens * settings.PRICING.INPUT_RATE_PER_1K) // 1000
    cost_cached = (cached_input_tokens * settings.PRICING.CACHED_INPUT_RATE_PER_1K) // 1000
    cost_output = (output_tokens * settings.PRICING.OUTPUT_RATE_PER_1K) // 1000
    cost_reasoning = (reasoning_tokens * settings.PRICING.REASONING_RATE_PER_1K) // 1000
    total_cost = cost_input + cost_cached + cost_output + cost_reasoning

    return {
        "input_tokens": input_tokens,
        "input_cost_micro_units": cost_input,
        "cached_input_tokens": cached_input_tokens,
        "cached_input_cost_micro_units": cost_cached,
        "output_tokens": output_tokens,
        "output_cost_micro_units": cost_output,
        "reasoning_tokens": reasoning_tokens,
        "reasoning_cost_micro_units": cost_reasoning,
        "total_tokens": input_tokens + cached_input_tokens + output_tokens + reasoning_tokens,
        "total_cost_micro_units": total_cost,
        "formatted_cost": format_currency(total_cost),
    }
