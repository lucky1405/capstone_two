"""Billing and Stripe Checkout API endpoints."""
from typing import Optional
from fastapi import APIRouter, Depends, Request
import aiosqlite

from app.api.deps import get_db, resolve_tenant_id
from app.models.schemas import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
)
from app.services.stripe_service import StripeService

router = APIRouter(tags=["Billing"])


@router.post(
    "/checkout/create-session",
    response_model=CheckoutSessionResponse,
    summary="Create a Stripe Checkout Session for subscription upgrade",
)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    db: aiosqlite.Connection = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id),
):
    """
    Creates a Stripe Checkout Session (Test Mode) allowing a tenant to upgrade to the Pro plan.
    Returns a secure Stripe Checkout URL.
    """
    session_data = await StripeService.create_checkout_session(
        conn=db,
        tenant_id=tenant_id,
        plan_id=payload.plan_id,
        success_url=payload.success_url or "https://example.com/checkout/success",
        cancel_url=payload.cancel_url or "https://example.com/checkout/cancel",
    )
    return session_data
