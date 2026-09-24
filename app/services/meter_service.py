"""Metering service with strict idempotency and duplicate charge prevention."""
import json
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
import aiosqlite

from app.core.errors import IdempotencyConflictException
from app.core.pricing import (
    calculate_token_cost_micro_units,
    calculate_total_cost_micro_units,
    format_currency,
)
from app.services.quota_service import QuotaService

logger = logging.getLogger(__name__)


class MeterService:
    """Handles exactly-once metering and usage recording."""

    @classmethod
    async def record_usage(
        cls,
        conn: aiosqlite.Connection,
        tenant_id: str,
        usage_type: str,
        quantity: int = 1,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Records a usage event ensuring exact idempotency.
        
        Returns:
            Tuple of (response_dict, is_idempotent_replay)
        """
        # 1. Idempotency Key Lookup
        if idempotency_key:
            cursor = await conn.execute(
                """
                SELECT request_hash, status_code, response_body, event_id
                FROM idempotency_keys
                WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (tenant_id, idempotency_key),
            )
            stored = await cursor.fetchone()
            if stored:
                # Compare request hash to detect misuse
                if request_hash and stored["request_hash"] != request_hash:
                    logger.warning(
                        "Idempotency conflict for tenant %s with key %s: hash mismatch",
                        tenant_id,
                        idempotency_key,
                    )
                    raise IdempotencyConflictException(
                        "Idempotency key has already been used with a different request payload."
                    )
                
                # Replay original response without creating any new event
                cached_data = json.loads(stored["response_body"])
                cached_data["idempotent_replay"] = True
                logger.info(
                    "Replaying cached response for idempotency key %s (tenant %s, event %s)",
                    idempotency_key,
                    tenant_id,
                    stored["event_id"],
                )
                return cached_data, True

        # 2. Quota Check (Enforced before action, never after)
        quota_check = await QuotaService.check_quota_or_raise(
            conn=conn,
            tenant_id=tenant_id,
            usage_type=usage_type,
            requested_units=quantity,
        )

        # 3. Calculate Cost using integer micro-units
        if usage_type == "ai_tokens":
            cost_micro_units = calculate_token_cost_micro_units(
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            )
        else:
            cost_micro_units = calculate_total_cost_micro_units(api_calls=quantity)

        # 4. Persist Usage Event
        event_id = f"evt_{uuid.uuid4().hex}"
        await conn.execute(
            """
            INSERT INTO usage_events (
                id, tenant_id, usage_type, quantity, input_tokens, cached_input_tokens,
                output_tokens, reasoning_tokens, cost_micro_units, idempotency_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                tenant_id,
                usage_type,
                quantity,
                input_tokens,
                cached_input_tokens,
                output_tokens,
                reasoning_tokens,
                cost_micro_units,
                idempotency_key,
            ),
        )

        result_payload = {
            "success": True,
            "event_id": event_id,
            "tenant_id": tenant_id,
            "usage_type": usage_type,
            "quantity": quantity,
            "cost_micro_units": cost_micro_units,
            "formatted_cost": format_currency(cost_micro_units),
            "quota_used": quota_check["current_used"] + quantity,
            "quota_limit": quota_check["limit"],
            "quota_remaining": quota_check["remaining"],
            "idempotent_replay": False,
        }

        # 5. Persist Idempotency Record
        if idempotency_key and request_hash:
            await conn.execute(
                """
                INSERT INTO idempotency_keys (
                    tenant_id, idempotency_key, request_hash, status_code, response_body, event_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    idempotency_key,
                    request_hash,
                    200,
                    json.dumps(result_payload),
                    event_id,
                ),
            )

        await conn.commit()
        return result_payload, False
