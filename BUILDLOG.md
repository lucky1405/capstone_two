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
