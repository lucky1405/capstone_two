"""Usage and metrics rollup endpoints."""
from fastapi import APIRouter, Depends
import aiosqlite

from app.api.deps import get_db, resolve_tenant_id
from app.models.schemas import UsageSummaryResponse
from app.services.pricing_service import PricingService

router = APIRouter(tags=["Usage"])


@router.get(
    "/usage",
    response_model=UsageSummaryResponse,
    summary="Get tenant usage rollup, quotas, and current cost",
)
async def get_tenant_usage(
    db: aiosqlite.Connection = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id),
):
    """
    Returns the tenant's current billing cycle usage, including:
    - API call allowances and current usage
    - AI token allowances and breakdowns (fresh input, cached input, output, reasoning)
    - Total calculated cost strictly computed with integer pricing
    """
    summary = await PricingService.get_tenant_usage_summary(conn=db, tenant_id=tenant_id)
    return summary
