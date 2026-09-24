"""Quota checking and boundary enforcement service."""
import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import aiosqlite

from app.core.errors import (
    TenantNotFoundException,
    QuotaExceededException,
    PaymentRequiredException,
)
from app.config import settings


class QuotaService:
    """Manages subscription tier quotas and pre-action boundary validation."""

    @staticmethod
    async def get_tenant_subscription(
        conn: aiosqlite.Connection, tenant_id: str
    ) -> Dict[str, Any]:
        """Retrieves tenant subscription and plan limits."""
        cursor = await conn.execute(
            """
            SELECT 
                t.id as tenant_id,
                t.name as tenant_name,
                t.api_key,
                s.id as subscription_id,
                s.plan_id,
                s.status as subscription_status,
                s.stripe_customer_id,
                s.stripe_subscription_id,
                s.current_period_start,
                s.current_period_end,
                p.name as plan_name,
                p.max_api_calls,
                p.max_ai_tokens,
                p.monthly_fee_cents
            FROM tenants t
            LEFT JOIN subscriptions s ON t.id = s.tenant_id
            LEFT JOIN plans p ON s.plan_id = p.id
            WHERE t.id = ?
            """,
            (tenant_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise TenantNotFoundException(f"Tenant '{tenant_id}' not found.")
        return dict(row)

    @staticmethod
    async def get_usage_rollup(
        conn: aiosqlite.Connection, tenant_id: str, period_start: str
    ) -> Dict[str, Any]:
        """Aggregates tenant usage from the start of the current billing cycle."""
        cursor = await conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN usage_type = 'api_call' THEN quantity ELSE 0 END), 0) as api_calls_used,
                COALESCE(SUM(CASE WHEN usage_type = 'ai_tokens' THEN quantity ELSE (input_tokens + cached_input_tokens + output_tokens + reasoning_tokens) END), 0) as ai_tokens_used,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(cached_input_tokens), 0) as total_cached_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(reasoning_tokens), 0) as total_reasoning_tokens,
                COALESCE(SUM(cost_micro_units), 0) as total_cost_micro_units
            FROM usage_events
            WHERE tenant_id = ? AND created_at >= ?
            """,
            (tenant_id, period_start),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {
            "api_calls_used": 0,
            "ai_tokens_used": 0,
            "total_input_tokens": 0,
            "total_cached_input_tokens": 0,
            "total_output_tokens": 0,
            "total_reasoning_tokens": 0,
            "total_cost_micro_units": 0,
        }

    @classmethod
    async def check_quota_or_raise(
        cls,
        conn: aiosqlite.Connection,
        tenant_id: str,
        usage_type: str,
        requested_units: int,
    ) -> Dict[str, Any]:
        """
        Validates whether the requested action is permitted within subscription limits.
        
        Enforces:
        - 402 Payment Required: If subscription is past_due, unpaid, or canceled.
        - 429 Too Many Requests: If current_usage + requested_units > limit.
        - Exact boundary semantics:
          current=999, requested=1, limit=1000 -> ALLOWED (now 1000)
          current=1000, requested=1, limit=1000 -> REJECTED (429)
        """
        sub = await cls.get_tenant_subscription(conn, tenant_id)
        status = sub.get("subscription_status") or "active"

        # Check subscription status for payment delinquency
        if status in ("past_due", "unpaid", "canceled"):
            raise PaymentRequiredException(
                message=f"Subscription is '{status}'. Please resolve your payment method or reactivate your subscription.",
                reason=f"subscription_{status}",
            )

        period_start = sub.get("current_period_start")
        if not period_start:
            # Fallback to beginning of current calendar month
            period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).isoformat()

        rollup = await cls.get_usage_rollup(conn, tenant_id, period_start)

        if usage_type == "api_call":
            limit = sub["max_api_calls"]
            current_used = rollup["api_calls_used"]
        elif usage_type == "ai_tokens":
            limit = sub["max_ai_tokens"]
            current_used = rollup["ai_tokens_used"]
        else:
            limit = 0
            current_used = 0

        # Boundary check: strictly > limit triggers 429
        if current_used + requested_units > limit:
            # Compute Retry-After in seconds
            retry_after = settings.DEFAULT_RETRY_AFTER_SECONDS
            period_end = sub.get("current_period_end")
            if period_end:
                try:
                    end_dt = datetime.fromisoformat(period_end)
                    now_dt = datetime.now(timezone.utc)
                    diff = int((end_dt - now_dt).total_seconds())
                    if diff > 0:
                        retry_after = min(diff, 86400 * 30)
                except Exception:
                    pass

            raise QuotaExceededException(
                message=f"Monthly {usage_type} quota of {limit:,} exceeded. Current usage: {current_used:,}, requested: {requested_units:,}. Upgrade to Pro for higher limits.",
                current_usage=current_used,
                limit=limit,
                usage_type=usage_type,
                retry_after=retry_after,
                reset_at=period_end,
            )

        return {
            "allowed": True,
            "current_used": current_used,
            "limit": limit,
            "remaining": limit - (current_used + requested_units),
            "subscription": sub,
            "rollup": rollup,
        }
