# Build Log: Usage Metering & Billing Engine

This log documents the iterative development of the Usage Metering & Billing Engine, detailing design decisions, implementation steps, where AI assistance was utilized, where initial assumptions required corrections, and how architectural guarantees were verified.

---

## Phase 1: Architecture, Specification & Design

### What was built:
- Defined the complete system architecture separating presentation (HTTP), business logic (metering, quotas, pricing, Stripe synchronization), and persistence (aiosqlite database).
- Authored `DESIGN.md` detailing the data model, entity relationships, plans and quota limits (Free vs Pro), exact quota boundary semantics (behavior at 999 vs 1,000), idempotency key hashing and replay mechanisms, and float-free integer token money math.
- Established environment baseline with `.gitignore`, safe `.env.example`, `pyproject.toml`, and `requirements.txt`.

### Where AI assisted:
- Outlined standard multi-tenant schema structure including `usage_events`, `subscriptions`, and `idempotency_keys`.
- Drafted the integer micro-unit pricing model for AI token modalities (fresh input, cached input, output, reasoning tokens).

### Where AI was corrected / refined:
- **Floating-point risk**: Initial suggestion used standard float multiplications for token cost fractions (e.g. `0.0000005 * tokens`). This was replaced with integer arithmetic scaled to micro-units ($\mu\$ = 10^{-6}$ USD) with integer division `// 1000` to guarantee zero IEEE 754 precision drift.
- **Quota Boundary Semantics**: Ensured the boundary condition explicitly distinguishes between 999 calls (under limit -> allowed) vs 1,000 calls (exact limit reached -> last allowed) vs 1,001 calls (exceeded -> blocked with `429 Too Many Requests` + `Retry-After`).
- **Idempotency Conflict**: Clarified that submitting the same `Idempotency-Key` with a different request payload must result in a `409 Conflict` rather than silently replaying stale results.

---

## Phase 2: Core Billing Logic & Idempotency

### What was built:
- Implemented `app/db/connection.py` managing async SQLite with WAL mode (`PRAGMA journal_mode=WAL`) and foreign key constraints.
- Authored `app/db/migrations.py` creating the complete multi-tenant schema with targeted indexes on `(tenant_id, created_at)` and `(tenant_id, idempotency_key)`.
- Created `app/db/seed.py` establishing demo tenants (`tenant_free`, `tenant_pro`, `tenant_boundary` at 999/1000 calls, and `tenant_past_due`).
- Developed `MeterService` with SHA-256 payload fingerprinting and transaction-level idempotency storage.
- Developed `QuotaService` enforcing boundary honesty and returning status 429 (with `Retry-After`) and 402 for lapsed tenants.
- Built `POST /api/v1/meter/record` and the simulated AI endpoint `POST /generate`.

### Where AI assisted:
- Scaffolded Pydantic schemas with positive validation constraints (`ge=1`, `ge=0`) to eliminate invalid negative inputs at the boundary.
- Provided initial test structure for idempotency replay and boundary limit transitions.

### Where AI was corrected / refined:
- **Idempotency Replay Header**: AI initially returned standard 200 without signaling whether a response was fresh or replayed. Added `X-Idempotent-Replay: true/false` and response payload flags so client applications can differentiate fresh execution from retries.
- **Retry-After Header Calculation**: AI suggested a static `Retry-After: 60`. Refined this to dynamically compute the time remaining until `current_period_end` while providing a sane fallback.

---

## Phase 3: Stripe Test Mode Integration & Webhooks

### What was built:
- Developed `StripeService` for creating checkout sessions in test mode (`POST /checkout/create-session`).
- Implemented HMAC-SHA256 signature verification in `verify_webhook_signature` using Stripe's raw body byte payload.
- Implemented webhook deduplication against `processed_events` table to gracefully handle replay attacks.
- Handled lifecycle events: `checkout.session.completed` (upgrades tenant Free -> Pro), `customer.subscription.updated`, and `customer.subscription.deleted` (downgrades Pro -> Free).

### Where AI assisted:
- Outlined webhook payload fixtures and HMAC signature generation helpers for unit tests.

### Where AI was corrected / refined:
- **Stripe Object Dict Conversion in SDK 15+**: Stripe Python SDK version 15+ returns `stripe.Event` objects where accessing `.get()` raises `AttributeError: 'get' is a dict method, but a Event is not a dict. Use .to_dict() to convert it.` AI originally wrote dictionary lookups directly on `event`. Added `if hasattr(event, "to_dict"): event = event.to_dict()` to resolve compatibility.
- **Offline / Sandbox Network Resilience**: AI omitted a fast-path for mock Stripe keys in offline environments, which caused test runs to attempt real HTTPS calls to `api.stripe.com` and timeout. Added simulated offline test paths for credentials containing `MockTest` or `placeholder`.

---

## Phase 4: AI Token Pricing Rules, Background Jobs & Finalization

### What was built:
- Created `app/core/pricing.py` implementing exact token pricing rules:
  - Fresh Input: 500 micro-units / 1k ($0.50 per 1M)
  - Cached Input: 125 micro-units / 1k ($0.125 per 1M, 75% discount)
  - Output: 1,500 micro-units / 1k ($1.50 per 1M)
  - Reasoning: 1,500 micro-units / 1k (billed at output rate)
- Built `GET /usage` rollup endpoint providing detailed breakdown of token modalities, percentages, limits, and formatted currency costs.
- Developed background jobs: `BillingReconciliationJob` (with exponential backoff retries and failure alerting) and `QuotaAlertDispatcherJob` (recording 80% and 100% quota threshold alerts).
- Built complete Docker setup (`Dockerfile`, `docker-compose.yml`), `capstone.yaml` manifest, and `EVIDENCE.md`.

### Where AI assisted:
- Generated comprehensive test matrices verifying all 5 evaluator acceptance probes.
- Drafted markdown tables and ASCII architecture diagrams for documentation.

### Where AI was corrected / refined:
- **Reasoning Token Billing Discrepancy**: Early pricing draft naively treated reasoning tokens as input tokens. Corrected this to adhere strictly to LLM pricing rules (reasoning tokens generate hidden output thought chains and are billed at the higher output token rate).
- **Float Rounding in Cost Rollup**: Verified that database stores `cost_micro_units` as integer `INTEGER NOT NULL DEFAULT 0`, completely preventing float accumulation errors across millions of events.
