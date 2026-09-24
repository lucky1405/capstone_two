"""Database seed utility to establish demo tenants and baseline scenarios."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from app.db.connection import get_db_connection
from app.db.migrations import init_db
from app.core.pricing import calculate_total_cost_micro_units


async def seed_data(db_path: str = None) -> None:
    """Populates deterministic test fixtures for tenants, subscriptions, and usage."""
    await init_db(db_path)
    
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 30 days ahead
    period_end = period_start + timedelta(days=30)
    
    start_iso = period_start.isoformat()
    end_iso = period_end.isoformat()

    tenants = [
        {
            "id": "tenant_free",
            "name": "Acme Free Corp",
            "api_key": "key_free_12345",
            "plan_id": "free",
            "status": "active",
            "initial_calls": 10,
        },
        {
            "id": "tenant_pro",
            "name": "Globex Pro Systems",
            "api_key": "key_pro_67890",
            "plan_id": "pro",
            "status": "active",
            "initial_calls": 50,
        },
        {
            "id": "tenant_boundary",
            "name": "Boundary Test Labs",
            "api_key": "key_boundary_999",
            "plan_id": "free",
            "status": "active",
            "initial_calls": 999,  # Exactly 1 away from 1,000 limit
        },
        {
            "id": "tenant_past_due",
            "name": "Lapsed Payments LLC",
            "api_key": "key_lapsed_000",
            "plan_id": "free",
            "status": "past_due",  # Will trigger 402 Payment Required
            "initial_calls": 5,
        },
    ]

    async with get_db_connection(db_path) as conn:
        for t in tenants:
            # 1. Upsert tenant
            await conn.execute(
                """
                INSERT INTO tenants (id, name, api_key)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    api_key = excluded.api_key
                """,
                (t["id"], t["name"], t["api_key"]),
            )

            # 2. Upsert subscription
            sub_id = f"sub_{t['id']}"
            await conn.execute(
                """
                INSERT INTO subscriptions (
                    id, tenant_id, plan_id, status, stripe_customer_id, stripe_subscription_id,
                    current_period_start, current_period_end, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    status = excluded.status,
                    current_period_start = excluded.current_period_start,
                    current_period_end = excluded.current_period_end,
                    updated_at = excluded.updated_at
                """,
                (
                    sub_id,
                    t["id"],
                    t["plan_id"],
                    t["status"],
                    f"cus_{t['id']}",
                    f"sub_stripe_{t['id']}",
                    start_iso,
                    end_iso,
                    now.isoformat(),
                ),
            )

            # 3. Clean and populate initial usage events
            await conn.execute("DELETE FROM usage_events WHERE tenant_id = ?", (t["id"],))
            
            initial_calls = t["initial_calls"]
            if initial_calls > 0:
                cost_micro = calculate_total_cost_micro_units(api_calls=initial_calls)
                # Seed as aggregated or batch rows
                # Seed one summary row for initial calls
                event_id = f"evt_seed_{t['id']}_{uuid.uuid4().hex[:8]}"
                await conn.execute(
                    """
                    INSERT INTO usage_events (
                        id, tenant_id, usage_type, quantity, input_tokens, cached_input_tokens,
                        output_tokens, reasoning_tokens, cost_micro_units, idempotency_key, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        t["id"],
                        "api_call",
                        initial_calls,
                        0,
                        0,
                        0,
                        0,
                        cost_micro,
                        f"seed_{t['id']}",
                        now.isoformat(),
                    ),
                )
        
        await conn.commit()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed_data())
