# Implementation Plan: SaaS Multi-Tenant Refactor

## Overview

This plan converts the multi-tenant SaaS design into incremental, test-driven coding
steps for the existing NCMS Monitor codebase (FastAPI + SQLAlchemy 2.0 backend, Vue 3 +
Tailwind + Pinia frontend). Work proceeds backend-first: configuration, ORM models, and
schemas form the foundation; then the pure plan-resolution/enforcement logic; then
tenancy/auth, Turnstile, payments, scheduler/alerter changes; then router/API wiring;
then the frontend; and finally end-to-end integration plus the migration/backward-
compatibility verification. New behavior is added as new modules (`plans.py`,
`payments/`, `turnstile.py`, `tenancy.py`, `migration.py`) and new routers so the
existing check → persist → alert path keeps behaving as before (Requirement 24).

Property tests follow the existing Hypothesis convention in
`backend/tests/test_properties.py`: each test is tagged
`# Feature: saas-multi-tenant, Property N: <text>` and configured with
`@settings(max_examples=100)`. External services (Cloudflare, SePay, Telegram) are
stubbed; tests run against in-memory SQLite with `PRAGMA foreign_keys=ON` active.

## Tasks

- [ ] 1. Backend data foundation (config, models, schemas)
  - [ ] 1.1 Extend `config.py` Settings with Turnstile and SePay configuration
    - Add `turnstile_secret_key`, `turnstile_verify_url`, `sepay_api_key`,
      `sepay_webhook_secret`, `sepay_bank_code`, `sepay_account_number`,
      `sepay_qr_base_url`, `free_plan_name` fields, all sourced from `.env` with
      safe dev defaults; add Turnstile (10 s) and QR (3 s) timeout module constants
    - Update `.env.example` with the new variable names (no secret values)
    - _Requirements: 11.1, 12.1, 13.2, 14.1, 14.2_

  - [ ] 1.2 Extend `models.py` with Plan, Transaction, and user/monitor columns
    - Add `Plan` and `Transaction` ORM models using the existing typed
      `Mapped`/`mapped_column` style
    - Add `email`, `telegram_chat_id`, `plan_id` (FK→plans, SET NULL),
      `plan_expires_at`, `is_admin`, `created_at` columns to `User`
    - Add non-null `user_id` FK (ON DELETE CASCADE) to `Monitor` with the `owner`
      relationship; keep `CheckResult` unchanged
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.6, 2.7, 2.8, 3.1, 15.1, 15.2, 15.3, 15.5_

  - [ ] 1.3 Extend `schemas.py` with plan, auth, settings, payment, and admin schemas
    - Add `PlanBase`/`PlanCreate`/`PlanUpdate`/`PlanOut`, `RegisterRequest`,
      `LoginRequest`, `TokenResponse`, extended `MonitorCreate`/`MonitorOut`,
      `TelegramUpdate` (with format validator), `ActivePlanOut`,
      `DashboardSettingsOut`, `PaymentInitiateRequest`/`PaymentInitiateOut`,
      `SepayWebhookIn`, `AdminUserOut`, `AdminTransactionOut`
    - Enforce bounds via `Field` constraints and `EmailStr`; `AdminUserOut`/
      `AdminTransactionOut` expose only the permitted projection (never credentials)
    - _Requirements: 1.2, 1.3, 1.4, 2.10, 6.5, 10.1, 10.4, 13.1, 18.1, 18.2, 18.3_

  - [ ]* 1.4 Write property test for Plan bounds validation round-trip
    - **Property 26: Plan bounds validation round-trip**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 17.1, 17.2**
    - Exercise `PlanCreate`/`PlanUpdate` accept within-bounds attribute sets and
      reject out-of-bounds / duplicate-name sets, naming the offending attribute

  - [ ]* 1.5 Write unit tests for schema field validators
    - Email-format rejection (Req 2.10) and Telegram_Chat_Id format/length rules
      (empty clears; `-?\d+` up to 32 chars otherwise)
    - _Requirements: 2.10, 10.1, 10.4_

- [ ] 2. Plan resolution and enforcement (`plans.py`)
  - [ ] 2.1 Implement plan seeding and active-plan resolution
    - Add `FREE_PLAN_DEFAULTS`, `seed_free_plan` (idempotent), `get_free_plan`, and
      `resolve_active_plan(db, user, now=None)` returning a concrete Plan using O(1)
      indexed lookups within the 200 ms budget
    - _Requirements: 1.8, 2.5, 16.1, 16.2, 16.3, 16.4, 16.5_

  - [ ]* 2.2 Write property test for plan expiry resolution
    - **Property 20: Plan expiry resolution**
    - **Validates: Requirements 16.1, 16.2, 16.3, 16.4**
    - Inject `now`; also assert each resolution call completes under the 200 ms budget (16.5)

  - [ ] 2.3 Implement monitor count and interval enforcement helpers
    - Add `PlanLimitError`, `NoActivePlanError`, `IntervalTooLowError`;
      `enforce_can_create_monitor(db, user, requested_interval)` performing an atomic
      count+insert guard under a write lock (SQLite `BEGIN IMMEDIATE`); and
      `enforce_interval_for_update(db, user, new_interval)`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.6_

  - [ ]* 2.4 Write property test for monitor count limit invariant
    - **Property 4: Monitor count limit invariant**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - Simulate concurrent creates with threads against file-backed SQLite to exercise `BEGIN IMMEDIATE`

  - [ ]* 2.5 Write property test for interval limit invariant
    - **Property 5: Interval limit invariant**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**

  - [ ]* 2.6 Write unit test for Free-plan seeding idempotence
    - Seeding twice yields exactly one Free Plan with the specified defaults
    - _Requirements: 1.8_

- [ ] 3. Tenant data-access scoping, tenancy dependencies, and auth helpers
  - [ ] 3.1 Add user-scoped CRUD and plan/transaction CRUD to `crud.py`
    - Add owner-scoped monitor read/list/update/delete variants and plan/transaction
      create/list/get functions; listings cap at 100 rows
    - _Requirements: 3.4, 4.1, 4.2, 4.3, 17.4, 18.5_

  - [ ] 3.2 Implement `tenancy.py` dependencies and ownership guard
    - Add `get_current_tenant_user`, `require_admin`, and `get_owned_monitor_or_404`
      returning an identical 404 for cross-tenant and nonexistent monitors
    - _Requirements: 3.5, 3.6, 4.4, 4.5, 4.7, 17.7, 18.6, 18.7_

  - [ ] 3.3 Extend `auth.py` with tenant-resolution helpers (no change to token issue/verify)
    - Add a helper that resolves the JWT subject username to a `User` row; reuse the
      existing password hashing/verification
    - _Requirements: 2.4, 11.5_

  - [ ]* 3.4 Write property test for tenant isolation
    - **Property 1: Tenant isolation**
    - **Validates: Requirements 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**

  - [ ]* 3.5 Write property test for monitor deletion cascade atomicity
    - **Property 3: Monitor deletion cascade atomicity**
    - **Validates: Requirements 3.3**
    - Run with `PRAGMA foreign_keys=ON`; assert all-or-nothing and no cross-tenant impact

- [ ] 4. Cloudflare Turnstile verification (`turnstile.py`)
  - [ ] 4.1 Implement `verify_token` and `TurnstileResult`
    - Empty token → FAILED; success → SUCCESS; failure → FAILED;
      timeout/network/non-200 → UNAVAILABLE; never raise; 10 s `httpx` timeout;
      empty secret (dev) treats non-empty token as SUCCESS
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3, 12.4_

  - [ ]* 4.2 Write unit tests for `verify_token` branch mapping
    - Stub the HTTP layer to cover SUCCESS / FAILED / UNAVAILABLE and dev-mode bypass
    - _Requirements: 11.2, 11.4, 12.3, 12.4_

- [ ] 5. Authentication router (register / login with Turnstile)
  - [ ] 5.1 Implement `routers/auth.py` register and login
    - Verify Turnstile before any credential work; map enum to 400/503; create users
      on the Free Plan with hashed password; map duplicate → 409, bad creds → 401,
      success → 201/200 (token); leave records unchanged on every rejection
    - _Requirements: 2.5, 2.9, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ]* 5.2 Write property test for password secrecy
    - **Property 10: Password secrecy**
    - **Validates: Requirements 2.4, 11.5**

  - [ ]* 5.3 Write property test for credential/identity uniqueness
    - **Property 11: Credential/identity uniqueness**
    - **Validates: Requirements 2.2, 2.3, 2.9, 11.6**

  - [ ]* 5.4 Write property test for Turnstile-gated authentication outcomes
    - **Property 12: Turnstile-gated authentication outcomes**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3, 12.4, 12.6**
    - Stub `verify_token` outcomes; assert no user created and no token issued on rejection

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. SePay payments package (`payments/`)
  - [ ] 7.1 Implement `payments/sepay.py` QR, reference-code, and webhook verification
    - `build_qr_reference(plan, reference_code)` (pure string, < 3 s),
      `generate_reference_code(user_id, plan_id)` (globally unique, URL-safe),
      `verify_webhook(headers, raw_body)` (constant-time API-key or HMAC-SHA256)
    - _Requirements: 13.2, 14.1, 14.2, 15.5_

  - [ ] 7.2 Implement `payments/service.py` initiation and webhook confirmation
    - `initiate_payment(db, user, plan_id)`: 404 missing plan, 400 price 0, return
      existing pending tx else create one with a unique reference code
    - `apply_webhook_confirmation(db, payload)`: match by reference code; amount
      mismatch → unchanged; already completed → unchanged; pending+match → complete
      and set `user.plan_id` / `plan_expires_at = now + duration_days`; no match → 404
    - _Requirements: 13.1, 13.3, 13.4, 13.5, 14.3, 14.4, 14.5, 14.6, 14.7, 15.4, 15.6_

  - [ ]* 7.3 Write property test for payment-initiation single-pending invariant
    - **Property 13: Payment-initiation single-pending invariant**
    - **Validates: Requirements 13.1, 13.2, 13.5**

  - [ ]* 7.4 Write property test for webhook signature rejection
    - **Property 14: Webhook signature rejection**
    - **Validates: Requirements 14.1, 14.2**

  - [ ]* 7.5 Write property test for webhook amount-match completion
    - **Property 15: Webhook amount-match completion**
    - **Validates: Requirements 14.3, 14.7**

  - [ ]* 7.6 Write property test for webhook idempotence
    - **Property 16: Webhook idempotence**
    - **Validates: Requirements 14.5**

  - [ ]* 7.7 Write property test for plan upgrade consistency
    - **Property 17: Plan upgrade consistency**
    - **Validates: Requirements 14.4**

  - [ ]* 7.8 Write property test for unknown-transaction rejection
    - **Property 18: Unknown-transaction rejection**
    - **Validates: Requirements 14.6, 15.6**

  - [ ]* 7.9 Write property test for SePay reference uniqueness
    - **Property 19: SePay reference uniqueness**
    - **Validates: Requirements 15.5**

- [ ] 8. Plan-aware scheduler and per-user alerter
  - [ ] 8.1 Add explicit `chat_id` routing to `alerter.py`
    - `send_telegram_alert(message, chat_id)` skips on empty/whitespace chat id with a
      logged reason; never raises; 10 s timeout; failures logged and swallowed; keep
      `decide_alerts` and the interval-based cooldown unchanged
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 24.3, 24.4, 24.5_

  - [ ] 8.2 Update `scheduler.py` for plan-aware scheduling and SSL gating
    - Compute effective interval = max(configured, owner active plan min); skip and
      log plan-less monitors; blank SSL fields at persist time when SSL disabled;
      route alerts to the owning user's chat id; add a 30 s reconcile job that
      re-registers jobs whose effective interval changed; preserve `is_active` gating
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1_

  - [ ]* 8.3 Write property test for SSL gating invariant
    - **Property 6: SSL gating invariant**
    - **Validates: Requirements 7.1, 7.3, 7.4, 7.5**

  - [ ]* 8.4 Write property test for scheduler effective-interval bound
    - **Property 7: Scheduler effective-interval bound**
    - **Validates: Requirements 8.1**

  - [ ]* 8.5 Write property test for alert routing
    - **Property 8: Alert routing**
    - **Validates: Requirements 9.1, 9.2**

  - [ ]* 8.6 Write property test for down-alert cooldown suppression
    - **Property 25: Down-alert cooldown suppression**
    - **Validates: Requirements 24.3, 24.4, 24.5**

  - [ ]* 8.7 Write property test reaffirming status classification
    - **Property 24: Status classification (backward compatibility)**
    - **Validates: Requirements 24.1, 24.2**

  - [ ]* 8.8 Write unit test for live plan-change re-evaluation
    - Change a user's plan, run the reconcile job once, assert effective intervals
      update within the 60 s window without a restart
    - _Requirements: 8.5_

- [ ] 9. Data migration (`migration.py`)
  - [ ] 9.1 Implement idempotent single-user → multi-tenant migration
    - `migrate(db, *, global_telegram_chat_id)` in one transaction: seed Free Plan,
      promote the existing user to admin on the Free Plan, copy the global telegram id
      iff present/non-empty, and back-fill every monitor's `user_id` without changing
      other fields; idempotency marker; rollback + report on any failure; add
      idempotent `ALTER TABLE ADD COLUMN` guards (via `PRAGMA table_info`) and a
      `python -m migration` CLI
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

  - [ ] 9.2 Wire migration into startup in `main.py`
    - Run `migrate` after `init_db`, reading the legacy global chat id from
      `Settings.telegram_chat_id`; log the `MigrationOutcome`
    - _Requirements: 23.5, 23.7_

  - [ ]* 9.3 Write property test for migration completeness and idempotence
    - **Property 23: Migration completeness and idempotence**
    - **Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7**
    - Generate legacy DB states (zero/some monitors, with/without global chat id)

- [ ] 10. Router and API wiring
  - [ ] 10.1 Update `routers/monitors.py` for ownership scoping and enforcement
    - Replace unscoped CRUD with scoped variants and `get_owned_monitor_or_404`; set
      owner from the authenticated user on create; call enforcement on create/update;
      map limit/interval/no-plan failures to 403 and cross-tenant/missing to 404
    - _Requirements: 3.2, 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 10.2 Update `routers/results.py` for ownership scoping
    - Scope results/stats to owned monitors; return identical 404 for cross-tenant/missing
    - _Requirements: 4.6, 4.7_

  - [ ] 10.3 Implement `routers/settings.py` telegram and dashboard endpoints
    - `GET /api/settings` returns telegram id, active plan limits, usage, expiry;
      `PUT /api/settings/telegram` sets/clears with format validation; reject
      unauthenticated with 401
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 21.1, 21.2, 21.3, 21.4_

  - [ ] 10.4 Implement `routers/payments.py` initiate and webhook endpoints
    - `POST /api/payments/initiate` (JWT) and `POST /api/payments/sepay-webhook`
      reading the raw `Request` body for signature verification; map service outcomes
      to 200/400/401/404
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 14.1, 14.2, 14.3, 14.6, 14.7_

  - [ ] 10.5 Implement `routers/admin.py` plan/user/transaction management
    - Plan CRUD behind `require_admin` with case-insensitive duplicate and bounds
      checks; delete blocked (409) when subscribers exist; user/transaction listings
      capped at 100 with empty-list support and no credential fields
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

  - [ ] 10.6 Register routers and public plans endpoint in `main.py`
    - Mount auth/monitors/results/settings/payments/admin routers under `/api`; add
      public `GET /api/plans` returning active plans (empty list if none)
    - _Requirements: 18.7, 19.1_

  - [ ]* 10.7 Write property test for monitor ownership on creation
    - **Property 2: Monitor ownership on creation**
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 10.8 Write property test for Telegram configuration round-trip
    - **Property 9: Telegram configuration round-trip**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

  - [ ]* 10.9 Write property test for plan deletion subscriber protection
    - **Property 21: Plan deletion subscriber protection**
    - **Validates: Requirements 17.6**

  - [ ]* 10.10 Write property test for admin listing credential secrecy
    - **Property 22: Admin listing credential secrecy**
    - **Validates: Requirements 18.1, 18.2, 18.5**

  - [ ]* 10.11 Write unit tests for status-code mapping per endpoint branch
    - Concrete 201/400/401/403/404/409/503 assertions for auth, monitors, settings,
      payments, and admin routes
    - _Requirements: 4.4, 5.2, 11.2, 14.2, 17.7, 18.6, 18.7_

- [ ] 11. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Frontend API, store, and routing foundation
  - [ ] 12.1 Extend `src/api/index.js` with new method groups
    - Add `plans`, `settings`, `payments`, and `admin` groups reusing the Bearer
      interceptor, 401 handling, and `extractErrorMessage`
    - _Requirements: 19.1, 21.1, 21.5, 22.1, 22.2, 22.4_

  - [ ] 12.2 Extend `src/stores/auth.js` with `isAdmin` and user profile
    - Hydrate id/username/email/is_admin/plan from `GET /api/settings`; expose `isAdmin`
    - _Requirements: 22.5_

  - [ ] 12.3 Add routes and navigation guards in `src/router/index.js`
    - Add landing/register/admin routes with `public`/`admin` meta; guard redirects
      unauthenticated to login and non-admins away from `/admin`
    - _Requirements: 19.6, 22.5, 22.6_

  - [ ]* 12.4 Set up Vitest + Vue Test Utils
    - Add `vitest`, `@vue/test-utils`, and jsdom devDeps and a `test` script;
      configure Vite test environment
    - _Requirements: 19.1, 20.1, 21.1, 22.1_

  - [ ]* 12.5 Write router-guard unit tests
    - Unauthenticated `/admin` redirects to login; non-admin authenticated is sent to
      dashboard; public routes always allowed
    - _Requirements: 22.5, 22.6_

- [ ] 13. Frontend views and components
  - [ ] 13.1 Implement `TurnstileWidget.vue`
    - Load the Cloudflare script, emit the token via `v-model`, expose `reset()`
    - _Requirements: 20.3_

  - [ ] 13.2 Implement `Register.vue` and extend `Login.vue`
    - Render required fields plus the widget (initially empty); block submit without a
      token or with empty fields (per-field errors, preserve values except password);
      on API error stay on page, show message, reset the widget
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_

  - [ ] 13.3 Implement `Landing.vue`, `PricingTable.vue`, and `PlanCard.vue`
    - Fetch `GET /api/plans` and render one entry per active plan (name, price, billing
      period, features); empty → placeholder; fetch failure → placeholder + error
      banner with the rest intact; single above-the-fold CTA routing to `/register`
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_

  - [ ] 13.4 Implement `SettingsPanel.vue` and `UpgradeModal.vue`; extend `Dashboard.vue`
    - Show active plan name, max monitors, min interval, SSL flag, "used of total"
      usage, expiry for paid plans, and the telegram field; selecting a paid plan calls
      `POST /api/payments/initiate` and renders the QR within 5 s; on failure/timeout
      keep the current plan and show a retry error
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_

  - [ ] 13.5 Implement `Admin.vue` and admin components
    - `admin/PlanForm.vue`, `admin/UserTable.vue`, `admin/TransactionTable.vue` with
      plan create/update controls, user list (identifier + active plan name),
      transaction list, empty-state indicators, and an access-denied panel for non-admins
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

  - [ ]* 13.6 Write component tests for the landing page
    - One entry per active plan; empty and fetch-error placeholders; CTA navigates to register
    - _Requirements: 19.1, 19.3, 19.4, 19.6_

  - [ ]* 13.7 Write component tests for the auth pages
    - Field presence, submit-blocking without token/empty fields, token inclusion,
      widget reset on error
    - _Requirements: 20.1, 20.2, 20.4, 20.5, 20.6_

  - [ ]* 13.8 Write component tests for dashboard settings and upgrade flow
    - Plan limits, "used of total" usage, expiry for paid plans, telegram field, QR
      success render and failure/retry
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_

  - [ ]* 13.9 Write component tests for the admin console
    - Plan controls render, user/transaction empty-states, access-denied panel for non-admin
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

- [ ] 14. End-to-end integration and backward-compatibility verification
  - [ ]* 14.1 Write end-to-end integration test for the full tenant flow
    - register → login → create monitor → initiate payment → simulated webhook upgrade
      → SSL/interval entitlement change, via FastAPI `TestClient`
    - _Requirements: 5.1, 6.1, 7.3, 11.5, 13.1, 14.3, 14.4_

  - [ ]* 14.2 Write integration test for backward-compatible monitoring after migration
    - Migrate a legacy DB, then assert up/down classification, timeout handling,
      cooldown alerting, and full Check_Result persistence behave as before
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6_

  - [ ]* 14.3 Write integration test for webhook signature verification modes
    - Real API-key and HMAC-SHA256 signature computation against `verify_webhook`
    - _Requirements: 14.1, 14.2_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.
- Each task references specific requirement sub-clauses for traceability.
- Property tests reuse the existing Hypothesis convention
  (`# Feature: saas-multi-tenant, Property N: ...`, `@settings(max_examples=100)`) in
  `backend/tests/test_properties.py`; all 26 design properties are covered by tasks
  1.4, 2.2, 2.4, 2.5, 3.4, 3.5, 5.2, 5.3, 5.4, 7.3–7.9, 8.3–8.7, 9.3, 10.7–10.10.
- Frontend UI criteria (Req 19–22) are validated by component and router-guard tests
  rather than property-based tests.
- Checkpoints provide incremental validation between backend phases, after wiring, and
  at the end.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5"] },
    { "id": 2, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2", "3.3", "4.2"] },
    { "id": 4, "tasks": ["2.4", "2.5", "2.6", "3.4", "3.5", "5.1", "7.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "7.2", "8.1", "9.1"] },
    { "id": 6, "tasks": ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9", "8.2", "9.2"] },
    { "id": 7, "tasks": ["8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "9.3", "10.1", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 8, "tasks": ["10.6", "10.7", "10.8", "10.9", "10.10", "10.11"] },
    { "id": 9, "tasks": ["12.1", "12.2", "12.3"] },
    { "id": 10, "tasks": ["12.4", "12.5", "13.1", "13.2", "13.3", "13.4", "13.5"] },
    { "id": 11, "tasks": ["13.6", "13.7", "13.8", "13.9"] },
    { "id": 12, "tasks": ["14.1", "14.2", "14.3"] }
  ]
}
```
