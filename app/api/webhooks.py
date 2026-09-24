"""Stripe webhook receiver and signature verification handler."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request
import aiosqlite

from app.api.deps import get_db
from app.models.schemas import WebhookResponse
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


@router.post(
    "/webhooks/stripe",
    response_model=WebhookResponse,
    summary="Receive and verify signed Stripe webhook events",
)
async def handle_stripe_webhook(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Ingests and processes Stripe webhooks.
    
    Security & Reliability Guarantees:
    1. Cryptographic HMAC signature verification (whsec_...) -> Invalid signatures yield 400 Bad Request.
    2. Deduplication check -> Replayed event IDs are acknowledged with 200 OK without double processing.
    3. Idempotent state synchronization for subscriptions and plan tiers.
    """
    payload_bytes = await request.body()
    
    # 1. Verify cryptographic signature
    event = StripeService.verify_webhook_signature(
        payload=payload_bytes,
        sig_header=stripe_signature,
    )

    # 2. Process event idempotently
    result = await StripeService.process_webhook_event(conn=db, event=event)
    return result
