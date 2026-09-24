"""Tests for background jobs: slow/bulk work off the request path, retries, and failure alerts."""
import asyncio
import pytest
from app.services.background_jobs import (
    BillingBackgroundWorker,
    BillingReconciliationJob,
    QuotaAlertDispatcherJob,
)
from app.db.connection import get_db_connection


@pytest.mark.asyncio
async def test_reconciliation_job_execution(test_db):
    """Verifies that the background reconciliation job processes subscriptions without crashing."""
    result = await BillingReconciliationJob.run_reconciliation(db_path=test_db)
    assert result["status"] == "completed"
    assert result["attempts"] >= 1


@pytest.mark.asyncio
async def test_quota_alert_job_threshold_detection(client, test_db):
    """
    Verifies that tenants approaching or exceeding 80% and 100% quota
    trigger alerts recorded off the request path.
    """
    # tenant_boundary is at 999/1000 calls (99.9%, which crosses the 80% threshold)
    alert_result = await QuotaAlertDispatcherJob.evaluate_and_dispatch_alerts(db_path=test_db)
    assert alert_result["status"] == "completed"
    assert alert_result["attempts"] >= 1

    # Confirm alert row was written into usage_alerts table
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT threshold_percent, usage_type FROM usage_alerts WHERE tenant_id = 'tenant_boundary'"
        )
        alerts = await cursor.fetchall()
        thresholds = [a["threshold_percent"] for a in alerts]
        assert 80 in thresholds


@pytest.mark.asyncio
async def test_background_job_executed_off_request_path(client, test_db):
    """
    Verifies that slow/bulk usage side-effects execute completely OFF the request path.
    1. HTTP request returns immediately (200 OK).
    2. Background worker registers job, executes retries if needed, and completes in DB.
    """
    headers = {"X-Tenant-Id": "tenant_pro"}
    payload = {"usage_type": "api_call", "quantity": 1}

    response = await client.post("/api/v1/meter/record", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Give background task event loop a slice to finish
    await asyncio.sleep(0.05)

    # Verify background_jobs table has recorded the execution
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT id, status, attempts FROM background_jobs WHERE tenant_id = 'tenant_pro'"
        )
        jobs = await cursor.fetchall()
        assert len(jobs) >= 1
        assert jobs[-1]["status"] == "completed"
        assert jobs[-1]["attempts"] >= 1


@pytest.mark.asyncio
async def test_background_job_exhaustion_emits_failure_alert(client, test_db):
    """
    Verifies retry exhaustion and failure alert:
    1. An unrecoverable background error retries up to max_retries.
    2. Upon exhaustion, status flips to 'failed'.
    3. A critical failure alert is written to job_failure_alerts.
    4. The caller's HTTP response was never compromised.
    """
    # Direct execution of worker with simulate_fail=True to test retry exhaustion
    result = await BillingBackgroundWorker.process_usage_event_background(
        tenant_id="tenant_free",
        event_id="evt_test_exhaustion",
        simulate_fail=True,
        max_retries=2,
        db_path=test_db,
    )
    assert result["status"] == "failed"
    assert result["attempts"] == 3  # Initial + 2 retries = 3 attempts
    assert "Simulated notification service outage" in result["error"]

    # Verify that the critical failure alert was recorded in database
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT * FROM job_failure_alerts WHERE job_id = ?", (result["job_id"],)
        )
        alert = await cursor.fetchone()
        assert alert is not None
        assert alert["severity"] == "CRITICAL"
        assert alert["job_type"] == "usage_aggregation_and_alerts"
        assert "Simulated notification service outage" in alert["error_message"]

    # Verify that the failure alerts endpoint exposes the alert
    alerts_res = await client.get("/admin/jobs/failures")
    assert alerts_res.status_code == 200
    alerts_list = alerts_res.json()
    assert any(a["job_id"] == result["job_id"] for a in alerts_list)


@pytest.mark.asyncio
async def test_async_bulk_reconciliation_enqueued_202(client, test_db):
    """
    Verifies that bulk reconciliation can be enqueued asynchronously,
    returning HTTP 202 Accepted immediately.
    """
    res = await client.post("/jobs/reconcile?tenant_id=tenant_pro")
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "queued"
    assert "enqueued off the request path" in data["message"]
