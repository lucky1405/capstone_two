"""Main FastAPI application entrypoint with lifecycle hooks and global error handlers."""
import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.db.migrations import init_db
from app.core.errors import (
    BillingException,
    QuotaExceededException,
    PaymentRequiredException,
    IdempotencyConflictException,
    InvalidSignatureException,
    TenantNotFoundException,
)
from app.api import meter, usage, billing, webhooks
from app.services.background_jobs import (
    BillingBackgroundWorker,
    BillingReconciliationJob,
    QuotaAlertDispatcherJob,
)

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("billing_engine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes database schema and baseline plans upon startup."""
    logger.info("Initializing Usage Metering & Billing Engine...")
    await init_db()
    logger.info("Engine startup complete.")
    yield
    logger.info("Engine shutting down.")


app = FastAPI(
    title="Usage Metering & Billing Engine",
    description="SaaS Usage Metering, Honest Quota Enforcement, AI Token Pricing & Stripe Sync",
    version="1.0.0",
    lifespan=lifespan,
)

# Register route modules
app.include_router(meter.router)
app.include_router(usage.router)
app.include_router(billing.router)
app.include_router(webhooks.router)


# --- Global Exception Handlers for Strict Boundary Validation ---

@app.exception_handler(QuotaExceededException)
async def quota_exceeded_handler(request: Request, exc: QuotaExceededException):
    """Handles HTTP 429 Too Many Requests with explicit Retry-After headers."""
    headers = {"Retry-After": str(exc.retry_after)}
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
        headers=headers,
    )


@app.exception_handler(PaymentRequiredException)
async def payment_required_handler(request: Request, exc: PaymentRequiredException):
    """Handles HTTP 402 Payment Required for past due or expired subscriptions."""
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(IdempotencyConflictException)
async def idempotency_conflict_handler(request: Request, exc: IdempotencyConflictException):
    """Handles HTTP 409 Conflict when an idempotency key is reused with mismatched payloads."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": exc.error_code,
            "message": exc.message,
        },
    )


@app.exception_handler(InvalidSignatureException)
async def invalid_signature_handler(request: Request, exc: InvalidSignatureException):
    """Handles HTTP 400 Bad Request when webhook signature verification fails."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": exc.error_code,
            "message": exc.message,
        },
    )


@app.exception_handler(TenantNotFoundException)
async def tenant_not_found_handler(request: Request, exc: TenantNotFoundException):
    """Handles HTTP 404 Not Found for non-existent tenants."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": exc.error_code,
            "message": exc.message,
        },
    )


@app.exception_handler(BillingException)
async def generic_billing_handler(request: Request, exc: BillingException):
    """Handles general domain exceptions with standard error envelopes."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Boundary input validation: transforms Pydantic validation errors into clean 422 JSON."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Validation failed at the request boundary.",
            "details": exc.errors(),
        },
    )


# --- System & Operational Endpoints ---

@app.get("/health", tags=["System"])
async def health_check():
    """Operational health check endpoint."""
    return {
        "status": "healthy",
        "service": "usage-metering-billing-engine",
        "environment": settings.APP_ENV,
        "pricing_model": "integer-micro-units",
    }


@app.post("/admin/reconcile", tags=["System"])
async def trigger_reconciliation():
    """Triggers the background reconciliation audit job against Stripe state."""
    job_result = await BillingReconciliationJob.run_reconciliation()
    return job_result.to_dict()


@app.post("/jobs/reconcile", status_code=status.HTTP_202_ACCEPTED, tags=["System"])
async def enqueue_reconciliation_job(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: Optional[str] = None,
):
    """
    Enqueues bulk reconciliation audit completely OFF the request path.
    Returns HTTP 202 Accepted immediately.
    """
    simulate_fail = bool(
        request.headers.get("X-Simulate-Job-Fail") == "1"
        or request.query_params.get("simulate_job_fail") == "1"
    )
    background_tasks.add_task(
        BillingBackgroundWorker.process_stripe_reconciliation_background,
        tenant_id=tenant_id,
        simulate_fail=simulate_fail,
    )
    return {
        "status": "queued",
        "message": "Bulk reconciliation audit enqueued off the request path.",
        "tenant_id": tenant_id,
    }


@app.get("/admin/jobs/failures", tags=["System"])
async def list_failure_alerts():
    """Returns all critical failure alerts dispatched by exhausted background jobs."""
    from app.db.connection import get_db_connection
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, job_id, tenant_id, job_type, error_message, severity, created_at
            FROM job_failure_alerts
            ORDER BY created_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.get("/admin/jobs/{job_id}", tags=["System"])
async def get_job_status(job_id: str):
    """Inspects the execution state of an asynchronous background job."""
    from app.db.connection import get_db_connection
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, tenant_id, job_type, status, attempts, max_retries, last_error, created_at, updated_at
            FROM background_jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "job_not_found"})
        return dict(row)
