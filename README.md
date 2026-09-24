# Usage Metering & Billing Engine

[![CI Tests](https://img.shields.io/badge/tests-19%20passed-brightgreen.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)]()
[![Python 3.13](https://img.shields.io/badge/Python-3.13+-blue.svg)]()
[![Stripe Test Mode](https://img.shields.io/badge/Stripe-Test%20Mode-635BFF.svg)]()
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)]()

An enterprise-grade, deterministic usage metering and subscription billing engine designed for modern AI and SaaS platforms. Built to answer three fundamental questions reliably:
1. **How much has this tenant consumed?**
2. **What does it cost?**
3. **Have they exceeded their plan quota?**

Engineered with **guaranteed exactly-once metering under network retries**, **honest quota boundary enforcement (429/402)**, **float-free AI token pricing (cached & reasoning rules)**, and **cryptographically verified Stripe webhook synchronization**.

---

## Architecture Overview

```
                                  Client Request
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │        HTTP Presentation Tier           │
                   │  FastAPI Boundary Validation & Headers  │
                   └────────────────────┬────────────────────┘
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
              [POST /api/v1/meter/record]       [POST /generate]
                         │                             │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │          MeterService.record            │
                   │   1. Inspect Idempotency-Key & Hash     │
                   │      → Duplicate Match? Replay Original │
                   │   2. Pre-Action Quota Validation        │
                   │      → Exceeded? 429 Too Many Requests  │
                   │      → Delinquent? 402 Payment Required │
                   │   3. Compute Integer Token/API Cost     │
                   │   4. Atomic Transaction: Event + Key    │
                   └────────────────────┬────────────────────┘
                                        │
                        ┌───────────────┴───────────────┐
                        ▼                               ▼
       ┌────────────────────────────────┐ ┌───────────────────────────┐
       │   Stripe Webhook Sync Engine   │ │     GET /usage Rollup     │
       │  - HMAC-SHA256 Verification    │ │  - API Calls & Tokens     │
       │  - Event Deduplication (200)   │ │  - Itemized Breakdown     │
       │  - Plan Flip (Free <-> Pro)    │ │  - Pinned Micro-Unit Cost │
       └────────────────────────────────┘ └───────────────────────────┘
```

---

## Subscription Plans & Quotas

The engine configures two production subscription tiers:

| Tier | Monthly API Calls | Monthly AI Tokens | Monthly Price | Quota Exhaustion Rule |
| :--- | :--- | :--- | :--- | :--- |
| **Free** | **1,000 calls** | **100,000 tokens** | **$0.00** | Strict block (`429 Too Many Requests` + `Retry-After`) |
| **Pro** | **50,000 calls** | **5,000,000 tokens** | **$29.00** | Scaled capacity with overage monitoring & alerts |

---

## AI Token Pricing Rules & Integer Math

Modern foundation models price token modalities differently. The engine encodes these rules strictly using **integer micro-units** ($\mu\$ = 10^{-6}\text{ USD} = 1/10,000\text{th of a cent}$) to completely prevent floating-point drift:

| Token Modality | Rate per 1,000,000 Tokens | Scaled Rate / 1k Tokens | Description |
| :--- | :--- | :--- | :--- |
| **Standard Input** | **$0.50** | **500 $\mu\$$** | Fresh prompt context tokens |
| **Cached Input** | **$0.125** | **125 $\mu\$$** | Prompt cache hits (**75% discount**) |
| **Standard Output** | **$1.50** | **1,500 $\mu\$$** | Model completion tokens |
| **Reasoning Tokens** | **$1.50** | **1,500 $\mu\$$** | Thinking tokens (**billed at output rate**) |

### Formula:
$$\text{Cost}(\mu\$) = \left\lfloor \frac{500 \cdot T_{in} + 125 \cdot T_{cache} + 1500 \cdot T_{out} + 1500 \cdot T_{reason}}{1000} \right\rfloor$$

---

## Pre-Seeded Scenarios & Test Tenants

Run the seed script to instantly configure deterministic test scenarios:

| Tenant ID | Name | Plan | Baseline State | Demonstrates |
| :--- | :--- | :--- | :--- | :--- |
| `tenant_free` | Acme Free Corp | Free | 10 API calls used | Idempotent metering & Stripe checkout upgrades |
| `tenant_pro` | Globex Pro Systems | Pro | 50 API calls used | High-volume AI generation & token pricing rules |
| `tenant_boundary` | Boundary Test Labs | Free | **999 / 1,000 calls** | **Boundary Honesty**: Call 1,000 succeeds; call 1,001 returns `429` |
| `tenant_past_due` | Lapsed Payments LLC | Free | Subscription `past_due` | **Delinquency**: Requests immediately blocked with `402` |

---

## Quickstart & Installation

### Option 1: Local Setup with Python Virtual Environment

```bash
# 1. Clone the repository
git clone https://github.com/lucky1405/capstone_two.git
cd capstone_two

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. Initialize schema and seed demo tenants
python -m app.db.seed

# 6. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Option 2: Docker & Docker Compose

```bash
docker compose up -d --build
```
The application will be running at `http://localhost:8000`.

---

## Verification & Acceptance Probes

Run the complete deterministic test suite:

```bash
pytest -v
```

All 19 tests verify the five evaluator acceptance probes:
- **PROBE 1**: Same request sent twice with `Idempotency-Key` creates exactly 1 event; second mirrors the first.
- **PROBE 2**: Driving `tenant_boundary` to 1,000 succeeds; subsequent request triggers `429 Too Many Requests` with `Retry-After`. `tenant_past_due` returns `402 Payment Required`.
- **PROBE 3**: Stripe test Checkout webhook `checkout.session.completed` flips tenant from Free -> Pro; `GET /usage` shows updated limits (50k calls, 5M tokens).
- **PROBE 4**: Forged webhook signature returns `400 Bad Request`; replaying a valid event returns `200 OK` with `status: ignored`.
- **PROBE 5**: Cached-input (75% off) and reasoning tokens (output rate) match pinned constants exactly on `GET /usage`.

See [EVIDENCE.md](file:///Users/lucky/.gemini/antigravity/scratch/capstone_two/EVIDENCE.md) for full transcripts and proofs.

---

## API Endpoints Reference

### 1. Billable AI Generation: `POST /generate`
```bash
curl -X POST http://localhost:8000/generate \
  -H "X-Tenant-Id: tenant_pro" \
  -H "Idempotency-Key: req_demo_01" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain quantum computing in simple terms.",
    "input_tokens": 1000,
    "cached_input_tokens": 500,
    "output_tokens": 200,
    "reasoning_tokens": 100
  }'
```

### 2. Usage Rollup: `GET /usage`
```bash
curl -X GET http://localhost:8000/usage \
  -H "X-Tenant-Id: tenant_pro"
```

### 3. Stripe Checkout Session: `POST /checkout/create-session`
```bash
curl -X POST http://localhost:8000/checkout/create-session \
  -H "X-Tenant-Id: tenant_free" \
  -H "Content-Type: application/json" \
  -d '{"plan_id": "pro"}'
```

### 4. Background Auditing & Resilience
- **Reconciliation Audit Job**: `POST /admin/reconcile` (Syncs local subscriptions against Stripe source-of-truth with exponential retries).
- **Quota Alert Dispatcher Job**: `POST /admin/alerts/evaluate` (Identifies and alerts on tenants at $\ge 80\%$ and $100\%$ quota).

---

## Honest Limitations

1. **Storage Concurrency**: Uses SQLite in Write-Ahead-Logging (WAL) mode with asynchronous transactions via `aiosqlite`. This provides exceptional reliability and zero configuration for medium throughput SaaS workloads. For ultra-high write concurrency (>10,000 writes/sec), transitioning persistence to PostgreSQL with a distributed Redis sliding-window cache is recommended.
2. **Stripe Test Mode Only**: Intentionally decoupled from live production Stripe banking networks. All payments, checkout sessions, and webhook lifecycles use Stripe test mode (`sk_test_*`, `whsec_*`) and test credit card numbers. Real credit cards are never billed.
3. **Simulated AI Inference**: The dummy billable endpoint `/generate` meters token arithmetic deterministically without invoking costly third-party LLM APIs, allowing zero-cost validation and repeatable tests.
