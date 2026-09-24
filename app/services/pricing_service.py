"""Pricing and usage rollup aggregation service."""
from datetime import datetime, timezone
from typing import Dict, Any
import aiosqlite

from app.core.pricing import (
    calculate_token_cost_micro_units,
    calculate_total_cost_micro_units,
    format_currency,
)
from app.services.quota_service import QuotaService


class PricingService:
    """Computes usage rollups, costs, and token breakdowns for reporting."""

    @classmethod
    async def get_tenant_usage_summary(
        cls, conn: aiosqlite.Connection, tenant_id: str
    ) -> Dict[str, Any]:
        """Produces a comprehensive usage rollup with token breakdowns and costs."""
        sub = await QuotaService.get_tenant_subscription(conn, tenant_id)
        period_start = sub.get("current_period_start")
        if not period_start:
            period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).isoformat()
        period_end = sub.get("current_period_end") or ""

        rollup = await QuotaService.get_usage_rollup(conn, tenant_id, period_start)

        api_calls_used = rollup["api_calls_used"]
        max_api_calls = sub["max_api_calls"]
        api_remaining = max(0, max_api_calls - api_calls_used)
        api_percent = round((api_calls_used / max_api_calls) * 100, 2) if max_api_calls else 0.0

        ai_tokens_used = rollup["ai_tokens_used"]
        max_ai_tokens = sub["max_ai_tokens"]
        ai_remaining = max(0, max_ai_tokens - ai_tokens_used)
        ai_percent = round((ai_tokens_used / max_ai_tokens) * 100, 2) if max_ai_tokens else 0.0

        in_tok = rollup["total_input_tokens"]
        cached_tok = rollup["total_cached_input_tokens"]
        out_tok = rollup["total_output_tokens"]
        reason_tok = rollup["total_reasoning_tokens"]

        total_cost_micro = rollup["total_cost_micro_units"]
        if total_cost_micro == 0 and (in_tok or cached_tok or out_tok or reason_tok):
            total_cost_micro = calculate_token_cost_micro_units(
                input_tokens=in_tok,
                cached_input_tokens=cached_tok,
                output_tokens=out_tok,
                reasoning_tokens=reason_tok,
            )

        return {
            "tenant_id": tenant_id,
            "tenant_name": sub["tenant_name"],
            "plan_id": sub["plan_id"],
            "plan_name": sub["plan_name"],
            "subscription_status": sub["subscription_status"],
            "current_period_start": period_start,
            "current_period_end": period_end,
            "api_calls": {
                "used": api_calls_used,
                "limit": max_api_calls,
                "remaining": api_remaining,
                "percent_used": api_percent,
            },
            "ai_tokens": {
                "used": ai_tokens_used,
                "limit": max_ai_tokens,
                "remaining": ai_remaining,
                "percent_used": ai_percent,
            },
            "token_breakdown": {
                "input_tokens": in_tok,
                "cached_input_tokens": cached_tok,
                "output_tokens": out_tok,
                "reasoning_tokens": reason_tok,
                "total_tokens": in_tok + cached_tok + out_tok + reason_tok,
            },
            "total_cost_micro_units": total_cost_micro,
            "formatted_total_cost": format_currency(total_cost_micro),
        }
