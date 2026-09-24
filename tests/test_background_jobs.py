"""Tests for background jobs: reconciliation and quota alert dispatching."""
import pytest
from app.services.background_jobs import (
    BillingReconciliationJob,
    QuotaAlertDispatcherJob,
)
from app.db.connection import get_db_connection


@pytest.mark.asyncio
async def test_reconciliation_job_execution(test_db):
    """Verifies that the background reconciliation job processes subscriptions without crashing."""
    result = await BillingReconciliationJob.run_reconciliation(db_path=test_db)
    assert result.processed_count >= 1
    assert isinstance(result.errors, list)


@pytest.mark.asyncio
async def test_quota_alert_job_threshold_detection(client, test_db):
    """
    Verifies that tenants approaching or exceeding 80% and 100% quota
    trigger alerts recorded off the request path.
    """
    # tenant_boundary is at 999/1000 calls (99.9%, which crosses the 80% threshold)
    alert_result = await QuotaAlertDispatcherJob.evaluate_and_dispatch_alerts(db_path=test_db)
    assert len(alert_result.alerts_triggered) >= 1
    
    # Confirm alert row was written into usage_alerts table
    async with get_db_connection(test_db) as conn:
        cursor = await conn.execute(
            "SELECT threshold_percent, usage_type FROM usage_alerts WHERE tenant_id = 'tenant_boundary'"
        )
        alerts = await cursor.fetchall()
        thresholds = [a["threshold_percent"] for a in alerts]
        assert 80 in thresholds
