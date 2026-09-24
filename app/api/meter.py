"""Metering API endpoints: billable AI generation and direct usage recording."""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, Response
import aiosqlite

from app.api.deps import get_db, resolve_tenant_id
from app.core.security import compute_request_hash
from app.core.pricing import get_token_breakdown_dict, format_currency
from app.models.schemas import (
    UsageRecordRequest,
    UsageRecordResponse,
    GenerateRequest,
    GenerateResponse,
)
from app.services.meter_service import MeterService
from app.services.quota_service import QuotaService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Metering"])


@router.post(
    "/api/v1/meter/record",
    response_model=UsageRecordResponse,
    summary="Record a billable usage event idempotently",
)
async def record_usage_event(
    request: Request,
    response: Response,
    payload: UsageRecordRequest,
    db: aiosqlite.Connection = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Records consumption of API calls or AI tokens.
    Guarantees exactly-once processing using the 'Idempotency-Key' header.
    """
    raw_body = await request.body()
    request_hash = (
        compute_request_hash(request.method, request.url.path, raw_body)
        if idempotency_key
        else None
    )

    result, is_replay = await MeterService.record_usage(
        conn=db,
        tenant_id=tenant_id,
        usage_type=payload.usage_type,
        quantity=payload.quantity,
        input_tokens=payload.input_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        output_tokens=payload.output_tokens,
        reasoning_tokens=payload.reasoning_tokens,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )

    response.headers["X-Usage-Event-Id"] = result.get("event_id", "")
    response.headers["X-Idempotent-Replay"] = "true" if is_replay else "false"
    return result


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Simulated billable AI generation endpoint",
)
async def generate_completion(
    request: Request,
    response: Response,
    payload: GenerateRequest,
    db: aiosqlite.Connection = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Dummy billable endpoint simulating an AI completion.
    
    Demonstrates:
    - Pre-action quota check (API calls and AI tokens)
    - Pinned pricing math including cached input and reasoning tokens
    - Idempotent request replay without double charging
    """
    raw_body = await request.body()
    request_hash = (
        compute_request_hash(request.method, request.url.path, raw_body)
        if idempotency_key
        else None
    )

    # 1. Determine simulated token quantities
    prompt_words = max(1, len(payload.prompt.split()))
    input_tokens = (
        payload.input_tokens
        if payload.input_tokens is not None
        else prompt_words * 4
    )
    cached_input_tokens = (
        payload.cached_input_tokens if payload.cached_input_tokens is not None else 0
    )
    output_tokens = (
        payload.output_tokens if payload.output_tokens is not None else 64
    )
    reasoning_tokens = (
        payload.reasoning_tokens if payload.reasoning_tokens is not None else 32
    )

    total_tokens = input_tokens + cached_input_tokens + output_tokens + reasoning_tokens

    # 2. Check and record usage idempotently
    meter_result, is_replay = await MeterService.record_usage(
        conn=db,
        tenant_id=tenant_id,
        usage_type="ai_tokens",
        quantity=total_tokens,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )

    token_breakdown = get_token_breakdown_dict(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
    )

    completion_text = (
        f"[Simulated AI Response by {payload.model}] "
        f"Processed prompt with {total_tokens} total tokens ({cached_input_tokens} cached, {reasoning_tokens} reasoning)."
    )

    response.headers["X-Usage-Event-Id"] = meter_result.get("event_id", "")
    response.headers["X-Idempotent-Replay"] = "true" if is_replay else "false"

    return {
        "status": "completed",
        "completion": completion_text,
        "tenant_id": tenant_id,
        "event_id": meter_result["event_id"],
        "token_usage": token_breakdown,
        "cost": {
            "cost_micro_units": meter_result["cost_micro_units"],
            "formatted_cost": meter_result["formatted_cost"],
        },
        "quota": {
            "used": meter_result["quota_used"],
            "limit": meter_result["quota_limit"],
            "remaining": meter_result["quota_remaining"],
        },
        "idempotent_replay": is_replay,
    }
