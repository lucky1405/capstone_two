"""Database schema migrations and initialization."""
import logging
import aiosqlite
from app.db.connection import get_db_connection
from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    max_api_calls INTEGER NOT NULL,
    max_ai_tokens INTEGER NOT NULL,
    monthly_fee_cents INTEGER NOT NULL,
    stripe_price_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    current_period_start TIMESTAMP NOT NULL,
    current_period_end TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    usage_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    cost_micro_units INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    event_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usage_alerts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    threshold_percent INTEGER NOT NULL,
    usage_type TEXT NOT NULL,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, threshold_percent, usage_type),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS background_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_failure_alerts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    tenant_id TEXT,
    job_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'CRITICAL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES background_jobs(id) ON DELETE CASCADE
);

-- Index optimization for fast multi-tenant quota aggregations & queries
CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_time ON usage_events (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_type ON usage_events (tenant_id, usage_type, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_idemp ON usage_events (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_sub ON subscriptions (stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_lookup ON idempotency_keys (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_background_jobs_status ON background_jobs (status, job_type);
CREATE INDEX IF NOT EXISTS idx_failure_alerts_job ON job_failure_alerts (job_id);
"""


async def init_db(db_path: str = None) -> None:
    """Applies database migrations and populates default plan tiers."""
    async with get_db_connection(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        
        # Populate standard plan definitions if not present
        for plan_key, plan_data in settings.PLANS.items():
            await conn.execute(
                """
                INSERT INTO plans (id, name, max_api_calls, max_ai_tokens, monthly_fee_cents, stripe_price_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    max_api_calls = excluded.max_api_calls,
                    max_ai_tokens = excluded.max_ai_tokens,
                    monthly_fee_cents = excluded.monthly_fee_cents,
                    stripe_price_id = excluded.stripe_price_id
                """,
                (
                    plan_data["id"],
                    plan_data["name"],
                    plan_data["max_api_calls"],
                    plan_data["max_ai_tokens"],
                    plan_data["monthly_fee_cents"],
                    plan_data["stripe_price_id"],
                ),
            )
        await conn.commit()
        logger.info("Database schema initialized and base plans verified.")
