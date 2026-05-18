# Access Control Domain

**Last Updated:** 2026-05-13
**Domain Owner:** Neil Howell
**Related Domains:** N/A (standalone — no cross-domain dependencies in current scope)

---

## Current State (As of 2026-05-13)

RFHistoric uses Flask session-based authentication with a two-role model (`lead` / `viewer`). The `role` column was added to `accounts.TB_USERS` in QE-7360 and is populated into `session['role']` at login. Route-level guards use the pattern `if session.get('role') != 'lead': return 'Forbidden', 403`.

**QE-7360 (Done):** Gated test run deletion and project deletion to Lead role. Added `TB_DELETION_LOG` per-project table for soft audit of deleted runs. Added `/deleted` route per project showing deleted run history.

**QE-7371 (Done):** `/register` and `/newdb` routes gated to Lead role. Nav links hidden from non-Lead users. Automated (12 checks) and manual verification complete.

---

## Active Research

- [Register and New-Project Route Gating](research/current/2026-05-13-register-newdb-route-gating.md) — QE-7371 pre-implementation investigation
  - **Status:** Validated
  - **Key Findings:** `/register` GET+POST and `/newdb` GET+POST all lack route-level guards. QE-7360 pattern (`session.get('role') != 'lead'`) is the correct fix. Index.html "New User" link needs narrowing from `session['name']` to `session.get('role') == 'lead'`; "New Project" link is currently outside all auth blocks.

## Completed Research

- [Role-Based Deletion Permissions Foundations](research/current/2026-05-12-role-based-deletion-permissions.md) — QE-7360 pre-implementation investigation
  - **Status:** Implemented (QE-7360 merged)
  - **Key Decisions:** Inline `session.get('role')` guards (no Flask-Login); `TB_DELETION_LOG` per-project (no soft-delete columns on `TB_EXECUTION`); `role` column default `'viewer'`
- [Deletion Log Schema Strategy](research/current/2026-05-12-deletion-log-schema-strategy.md) — QE-7360 schema options investigation
  - **Status:** Implemented (TB_DELETION_LOG approach selected)

---

## Active Plans

- [QE-7371: Gate Register and New-Project Routes to Lead Role Only](plans/active/2026-05-13-register-newdb-route-gating.md)
  - **Status:** Complete — all verification passed (2026-05-14)
  - **Phases:** 2 (Phase 1: route guards in `app.py`; Phase 2: template UI guards)

- [QE-7360: Role-Based Permissions for Test Run Deletion](plans/active/2026-05-12-role-based-deletion-permissions.md)
  - **Status:** Complete (all 4 phases merged) — pending move to `completed/`
  - **Note:** Plan file not yet archived; implementation is in `master`

---

## Key Constraints

- **Unauthenticated is the primary user type.** Most app users view test results without ever logging in. Guards must be verified unauthenticated first; authenticated-viewer and authenticated-lead scenarios are secondary.
- No decorator-based auth (`@login_required`) — all guards are inline per-route; this is the established codebase pattern
- `session.get('role')` returns `None` for unauthenticated sessions — guards correctly reject both Viewer and unauthenticated via `!= 'lead'`
- No migration framework — schema changes require manual migration scripts (see `scripts/migrate_qe7360.py`)
- Role values in use: `'lead'` and `'viewer'` (default); no additional roles planned

---

## Deferred Decisions

- **Admin role for user creation (deferred post-QE-7371):** Considered introducing a separate `admin` role so that user creation requires higher privilege than project/data management. Decision: defer until Leads have real usage time with the app to determine if the distinction is needed in practice. QE-7371 gates both `/register` and `/newdb` to `lead` as written.

## Open Questions

- Should a base template or shared `require_lead()` helper be introduced to centralize auth guards, or continue with the inline pattern? (Out of scope for QE-7371 but a recurring question as the number of guarded routes grows.)
