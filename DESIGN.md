# Design Document: Usage Metering & Billing Engine

**Author**: lucky1405  
**Track**: FlyRank Internship — Backend Development Track  
**Capstone**: Usage Metering & Billing Engine  
**Target Runtime**: Python 3.13 / FastAPI / SQLite (with aiosqlite) / Docker / Stripe Test Mode  

---

## 1. Problem Statement & Scope

Every software-as-a-service (SaaS) business must reliably answer three fundamental operational questions:
1. **How much has this tenant consumed?**
2. **What does that consumption cost?**
3. **Have they exceeded their allocated subscription quota?**

In distributed environments, network retries, race conditions, and webhook delays frequently lead to catastrophic errors: double-billing customers, permitting unbounded usage past tier limits, or desynchronizing subscription states.

This capstone implements an enterprise-grade, deterministic usage metering and subscription billing engine featuring:
- **Strictly idempotent usage metering** preventing double counting across network retries.
- **Honest quota boundary enforcement** with standard HTTP `429 Too Many Requests` and `402 Payment Required` semantics.
- **High-precision, float-free AI token pricing** respecting cached inputs, reasoning/thinking tokens, and standard input/output token rules.
- **Cryptographically verified Stripe test-mode synchronization** with signature checking and webhook deduplication.

### Explicit Non-Goal
This system will **not** process live production financial transactions or manage multi-currency FX conversions. All payment and subscription lifecycles operate strictly within Stripe Test Mode (`sk_test_*` and `whsec_*`), utilizing free test credit cards. Invoicing, proration, and overage tracking are handled via deterministic engine calculation without third-party card processing fees.

---

## 2. Layered Architecture Overview

The system is decoupled into four distinct architectural tiers:

```
┌─────────────────────────────────────────────────────────────┐
│                    HTTP Presentation Tier                   │
│   FastAPI Routers (/generate, /meter/record, /usage, etc.)  │
│         Header Validation, Pydantic Request Validation      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Business Logic Tier                      │
│   MeterService      · Idempotency verification & replay     │
│   QuotaService      · Pre-action boundary checks (429/402)  │
│   PricingEngine     · Integer-unit token & API cost math    │
│   StripeService     · Checkout sessions & webhook sync      │
│   ReconcilerJob     · Async state auditing & alert checks   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Access Tier                       │
│    aiosqlite Connection Pool, Transactional Atomicity,      │
│     Tenant-Isolated Repository Queries, Index Tuning        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Persistence Storage                      │
│   SQLite (WAL Mode) / PostgreSQL with foreign key integrity │
└─────────────────────────────────────────────────────────────┘
```

### Key Architectural Tenets:
1. **Separation of Concerns**: HTTP handlers do not execute SQL queries; business services do not touch FastAPI request objects directly.
2. **Boundary Validation**: Malformed JSON or negative quantities return immediate `422 Unprocessable Entity` or `400 Bad Request` — zero unhandled `500 Internal Server Errors`.
3. **Auditability**: Every billable action produces an immutable usage event linked to an idempotency record and tenant ID.

---

## 3. Core Entities & Data Model

The data model guarantees multi-tenant isolation by scoping all subscription, usage, and idempotency queries to the authenticated `tenant_id`.

### 3.1 Entity Relationship Diagram

```
┌────────────────────────┐         1:1         ┌────────────────────────┐
│        tenants         ├────────────────────►│     subscriptions      │
├────────────────────────┤                     ├────────────────────────┤
│ id (PK, TEXT)          │                     │ id (PK, TEXT)          │
│ name (TEXT)            │                     │ tenant_id (FK, TEXT)   │
│ api_key (TEXT, UNIQUE) │                     │ plan_id (FK, TEXT)     │
│ created_at (TIMESTAMP) │                     │ status (TEXT)          │
└───────────┬────────────┘                     │ stripe_customer_id     │
            │                                  │ stripe_subscription_id │
            │ 1:N                              │ current_period_start   │
            ├─────────────────────┐            │ current_period_end     │
            │                     │            │ updated_at (TIMESTAMP) │
            ▼                     ▼            └────────────────────────┘
┌────────────────────────┐  ┌────────────────────────┐
│      usage_events      │  │    idempotency_keys    │
├────────────────────────┤  ├────────────────────────┤
│ id (PK, TEXT)          │  │ tenant_id (PK, TEXT)   │
│ tenant_id (FK, TEXT)   │  │ idempotency_key (PK)   │
│ usage_type (TEXT)      │  │ request_hash (TEXT)    │
│ quantity (INTEGER)     │  │ status_code (INTEGER)  │
│ input_tokens (INT)     │  │ response_body (TEXT)   │
│ cached_input_tokens    │  │ event_id (FK, TEXT)    │
│ output_tokens (INT)    │  │ created_at (TIMESTAMP) │
│ reasoning_tokens (INT) │  └────────────────────────┘
│ cost_micro_units (INT) │
│ idempotency_key (TEXT) │
│ created_at (TIMESTAMP) │
└────────────────────────┘
```

Auxiliary Tables:
- `plans`: Definitions of tier allowances (`id`, `name`, `max_api_calls`, `max_ai_tokens`, `monthly_fee_cents`).
- `processed_events`: Webhook deduplication store (`event_id` PRIMARY KEY, `event_type`, `processed_at`).
- `usage_alerts`: Triggered threshold alerts (`id`, `tenant_id`, `threshold_percent`, `triggered_at`).

---

## 4. Plans & Quota Definitions

The platform standardizes on two production plans with explicit, documented limits:

| Plan | Monthly API Calls | Monthly AI Tokens | Monthly Cost | Overages Permitted |
| :--- | :--- | :--- | :--- | :--- |
| **Free** | 1,000 calls / month | 100,000 tokens / month | $0.00 | No (strict block at limit) |
| **Pro** | 50,000 calls / month | 5,000,000 tokens / month | $29.00 | Soft limit with alert & overage tracking |

### Quota Boundary Rules:
- **Boundary Condition**: Let $U_{current}$ be tenant usage in the current monthly billing period, and $U_{requested}$ be the requested unit increment.
  - If $U_{current} + U_{requested} \le \text{Quota Limit}$: **ALLOW** and atomically record event.
  - If $U_{current} + U_{requested} > \text{Quota Limit}$: **REJECT**.
- **At 999 of 1,000**: A request of quantity 1 results in $999 + 1 = 1,000 \le 1,000 \rightarrow$ **ALLOWED (200 OK)**.
- **At 1,000 of 1,000**: A subsequent request of quantity 1 results in $1,000 + 1 = 1,001 > 1,000 \rightarrow$ **BLOCKED (429 Too Many Requests)** with header `Retry-After: <seconds_until_next_month>` and a descriptive JSON body.
- **Subscription Inactive / Canceled / Unpaid**: Requests return **402 Payment Required** instructing the client to upgrade or reactivate their subscription.

---

## 5. Idempotent Metering Strategy

Every billable request may submit an `Idempotency-Key` header (e.g. `Idempotency-Key: req_01HX9...`).

### Idempotency Lifecycle:
1. **Fingerprinting**: Compute SHA-256 hash of `(method, endpoint, request_payload)`.
2. **Lookup**: Query `idempotency_keys` with `(tenant_id, idempotency_key)`.
3. **Replay Detection**:
   - If record exists AND payload hash matches: Return cached `status_code` and `response_body` with header `X-Idempotent-Replay: true`. No new usage event is recorded.
   - If record exists AND payload hash differs: Return `409 Conflict` (or `422 Unprocessable Entity`) indicating idempotency key collision with mismatched payload.
4. **First-Execution Atomicity**:
   - Evaluate quota checks.
   - Execute in an atomic transaction: write row to `usage_events` and insert entry into `idempotency_keys`.
   - Return generated response with `X-Idempotent-Replay: false`.

---

## 6. High-Precision Token Pricing Math

### The Real-World Token Rules:
Modern AI foundation models (such as Gemini 1.5/2.0 and Claude 3.5) distinguish between different token modalities:
1. **Standard Input Tokens**: Fresh prompt input.
2. **Cached Input Tokens**: Prompt cache hits billed at a significant discount (typically 75% discount vs standard input).
3. **Standard Output Tokens**: Generated completion tokens.
4. **Reasoning / Thinking Tokens**: Internal reasoning tokens produced by reasoning models. They are **billed at the higher output rate**, not as input or a separate free tier.

### Elimination of Floating-Point Errors:
All financial calculations use **integer micro-units** ($\mu\$$, where $1 \text{ USD} = 1,000,000\text{ micro-units} = 100\text{ cents}$).

Pinned Model Pricing (per 1,000,000 tokens):
- Standard Input Rate ($R_{in}$): $\$0.50$ per 1M tokens ($0.50\mu\$$ / token).
- Cached Input Rate ($R_{cache}$): $\$0.125$ per 1M tokens ($0.125\mu\$$ / token).
- Output Rate ($R_{out}$): $\$1.50$ per 1M tokens ($1.50\mu\$$ / token).
- Reasoning Rate ($R_{reason}$): Equivalent to Output Rate ($\$1.50$ per 1M tokens).

**Exact Integer Formula**:
$$\text{Cost}(\mu\$) = \left\lfloor \frac{500 \cdot T_{in} + 125 \cdot T_{cache} + 1500 \cdot T_{out} + 1500 \cdot T_{reason}}{1000} \right\rfloor$$

Total tenant monthly cost rolls up API call costs + aggregate token costs into an integer figure, formatted as standard currency strings for UI/read endpoints.

---

## 7. Stripe Subscription Synchronization

The billing engine delegates payment custody entirely to Stripe Test Mode, maintaining local state as an event-driven mirror:

```
┌──────────────────┐               ┌──────────────────┐               ┌──────────────────┐
│  Stripe Checkout │──(Webhook)───►│  /webhooks/stripe│──(Atomic Sync)►│ Local SQLite DB  │
└──────────────────┘               └─────────┬────────┘               └──────────────────┘
                                             │
                        ┌────────────────────┴────────────────────┐
                        │ 1. Verify HMAC-SHA256 (whsec_...)       │
                        │    → Invalid signature: 400 Bad Request │
                        │ 2. Deduplicate against processed_events │
                        │    → Duplicate ID: 200 (Replay Ignored) │
                        │ 3. Execute State Transition:            │
                        │    checkout.session.completed → Pro     │
                        │    customer.subscription.updated → Sync │
                        │    customer.subscription.deleted → Free │
                        └─────────────────────────────────────────┘
```

---

## 8. Background Jobs & Resilience

A dedicated background worker runs independently of the request path:
1. **Reconciliation Job**: Periodically audits tenant subscription states against Stripe's subscription records to heal any missed webhook events, utilizing retry mechanisms with backoff.
2. **Threshold Alert Dispatcher**: Monitors tenant month-to-date usage and logs/dispatches alert events when tenants cross 80% and 100% of their quotas.
