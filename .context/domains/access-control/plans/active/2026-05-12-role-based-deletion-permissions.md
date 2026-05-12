---
date: 2026-05-12
author: Neil Howell
domain: access-control
jira: QE-7360
research: >
  .context/domains/access-control/research/current/2026-05-12-role-based-deletion-permissions.md
  .context/domains/access-control/research/current/2026-05-12-deletion-log-schema-strategy.md
status: active
phases: 4
---

# QE-7360: Role-Based Permissions for Test Run Deletion — Implementation Plan

## Overview
Add a global Lead role to RFHistoric that gates test run deletion. Non-Lead users can view all test runs but cannot delete them. All users can view a new per-project "Deleted Runs" tab showing soft-deleted runs with audit metadata. Deletion is tracked in a new `TB_DELETION_LOG` table per project database, keeping the core `TB_EXECUTION` table unchanged.

---

## Current State Analysis

*(Full details in research artifacts. Key facts for planning:)*

- **Auth:** Flask session-based; `session['name']` and `session['email']` set at login (`app.py:47-48`). No role field exists anywhere.
- **Deletion routes:** `GET /<db>/edelete/<eid>` (`app.py:259`) and `GET /<db>/delete` (`app.py:29`). Neither checks session state server-side — auth is template-only.
- **Schema:** `accounts.TB_USERS` has no `role` column. Per-project `TB_EXECUTION` has no soft-delete or audit columns.
- **Per-project DB creation:** Inline CREATE TABLE statements in `POST /<db>/newdb` route handler (`app.py`). No migration framework.
- **Template pattern:** Standalone HTML files using `{% if session['name'] %}` for conditional rendering. No base template.
- **Ticket scope:** Test run deletion only — project deletion (`/<db>/delete`) is explicitly out of scope.

---

## Desired End State

- A `role` column exists on `accounts.TB_USERS` with values `'lead'` or `'viewer'` (default `'viewer'`)
- `session['role']` is populated at login and available in all templates
- `GET /<db>/edelete/<eid>` returns HTTP 403 if `session.get('role') != 'lead'`
- The delete link on `ehistoric.html` is only rendered for Lead users
- Deletion writes a snapshot row to `TB_DELETION_LOG` before hard-deleting from `TB_EXECUTION`
- A new `GET /<db>/deleted` route renders all `TB_DELETION_LOG` rows for the project, newest first
- New project databases include `TB_DELETION_LOG` table by default
- Existing project databases receive `TB_DELETION_LOG` via one-time migration script
- All existing non-deletion functionality is unaffected

---

## What We're NOT Doing

- **Not** adding role protection to project/database deletion (`/<db>/delete`) — ticket explicitly scopes to test run deletion only
- **Not** implementing Flask-Login or a `@login_required` decorator — inline session checks consistent with existing codebase pattern
- **Not** adding soft-delete columns to `TB_EXECUTION` — `TB_DELETION_LOG` approach chosen (see schema strategy research)
- **Not** modifying dashboard statistics — deleted runs excluded from aggregates automatically (hard-delete preserved)
- **Not** adding role-based project visibility — all users see all projects
- **Not** implementing restoration of deleted runs in this ticket

---

## Implementation Approach

Four sequential phases, each independently deployable and verifiable:

1. **Schema & Migration** — establish data foundations before any app logic changes
2. **Role Integration in Auth Flow** — wire role into session so subsequent phases can use it
3. **Delete Route Access Control + Audit Log** — the core access control change + deletion snapshot write
4. **Deleted Runs Tab** — new route and template for the audit visibility requirement

Each phase has its own success criteria. No phase depends on anything not completed in a prior phase.

---

## Phase 1: Schema Changes & Migration Script
*Jira Subtask: QE-7360 — Phase 1*

### Overview
Establish the database foundations: add `role` to `TB_USERS`, add `TB_DELETION_LOG` DDL to new-project creation, and write a one-time migration script for existing installations.

### Changes Required

#### 1. `docker/init.sql`
- Add `role VARCHAR(20) NOT NULL DEFAULT 'viewer'` column to `accounts.TB_USERS` table definition
- Update the seed user row to include `role = 'lead'` (the default admin account should be a Lead)

#### 2. `robotframework_historic/app.py` — `/newdb` route
- Add `CREATE TABLE TB_DELETION_LOG` statement to the new-project database creation block alongside the existing `TB_EXECUTION`, `TB_SUITE`, `TB_TEST` creates
- DDL:
  ```sql
  CREATE TABLE TB_DELETION_LOG (
      log_id                   INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      execution_id             INT NOT NULL,
      deleted_at               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      deleted_by               VARCHAR(255),
      snapshot_execution_date  DATETIME,
      snapshot_execution_desc  TEXT,
      snapshot_execution_pass  INT,
      snapshot_execution_fail  INT,
      snapshot_execution_total INT,
      snapshot_execution_time  FLOAT,
      snapshot_execution_stotal INT,
      snapshot_execution_spass  INT,
      snapshot_execution_sfail  INT,
      INDEX (execution_id),
      INDEX (deleted_at)
  );
  ```

#### 3. `scripts/migrate_qe7360.py` (new file)
- Standalone Python script using same MySQL connection parameters as `args.py`
- Steps:
  1. Connect to MySQL using host/port/user/password from CLI args (mirror `args.py` pattern)
  2. Add `role` column to `accounts.TB_USERS` if it does not already exist (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`)
  3. Set `role = 'lead'` for the seed admin user (`admin@local`) if role is still `'viewer'`
  4. Query all project names from `robothistoric.TB_PROJECT`
  5. For each project database: `CREATE TABLE IF NOT EXISTS TB_DELETION_LOG (...)` using same DDL as above
  6. Print a summary: projects migrated, projects already up-to-date, any errors
- Script must be idempotent — safe to run multiple times

### Success Criteria

#### Automated Verification
- [ ] `docker/init.sql` contains `role` column in `TB_USERS` definition: `grep -i "role" docker/init.sql`
- [ ] `docker/init.sql` contains `TB_DELETION_LOG` CREATE statement: `grep "TB_DELETION_LOG" docker/init.sql`
- [ ] Migration script exists: `Test-Path scripts/migrate_qe7360.py`
- [ ] Migration script runs without error against a local instance: `python scripts/migrate_qe7360.py --host localhost --port 3306 --user root --password <pw>`
- [ ] After migration: `SHOW COLUMNS FROM accounts.TB_USERS LIKE 'role'` returns one row
- [ ] After migration: `SHOW TABLES IN <project_db> LIKE 'TB_DELETION_LOG'` returns one row per existing project

#### Manual Verification
- [ ] `docker-compose up` with fresh `init.sql` creates `TB_USERS` with `role` column and seed user with `role = 'lead'`
- [ ] Migration script run against pre-existing container adds `role` column and `TB_DELETION_LOG` to all projects without dropping existing data
- [ ] Running migration script a second time produces no errors and reports "already up-to-date"

**Pause for human confirmation before proceeding to Phase 2.**

---

## Phase 2: Role Integration in Auth Flow
*Jira Subtask: QE-7360 — Phase 2*

### Overview
Wire `role` into the session at login so all subsequent routes and templates can check `session['role']`. Update registration to support role assignment by Lead users.

### Changes Required

#### 1. `robotframework_historic/app.py` — login route (`app.py:37-66`)
- After successful password verification and before redirect, query `role` from `TB_USERS`:
  ```python
  session['role'] = user['role']  # 'lead' or 'viewer'
  ```
- Add alongside existing `session['name']` and `session['email']` assignments (`app.py:47-48`)

#### 2. `robotframework_historic/app.py` — register route (`app.py:69-85`)
- Add `role` field to the form data read (default `'viewer'` if not submitted)
- Include `role` in the `INSERT INTO TB_USERS` statement

#### 3. `robotframework_historic/templates/register.html`
- Add a `<select name="role">` field with options `viewer` (default, selected) and `lead`
- Wrap in the existing `{% if session['name'] %}` block (registration already gated to logged-in users)

### Success Criteria

#### Automated Verification
- [ ] Login with seed admin account sets `session['role'] = 'lead'` — verify by checking that the Lead-only delete button appears on `ehistoric.html` after login (manual step, but triggered by code change)
- [ ] Login with a Viewer account sets `session['role'] = 'viewer'`
- [ ] New user registered via form is stored with correct role in `TB_USERS`: `SELECT role FROM accounts.TB_USERS WHERE email='<new_email>'`

#### Manual Verification
- [ ] Log in as `admin@local` — confirm `session['role']` is `'lead'` (can be verified via Flask debug or by observing role-gated UI in Phase 3)
- [ ] Register a new user as Viewer — confirm they appear in `TB_USERS` with `role = 'viewer'`
- [ ] Register a new user as Lead — confirm they appear in `TB_USERS` with `role = 'lead'`
- [ ] Registration form is not accessible when logged out (existing behavior preserved)

**Pause for human confirmation before proceeding to Phase 3.**

---

## Phase 3: Delete Route Access Control + Audit Log Write
*Jira Subtask: QE-7360 — Phase 3*

### Overview
Add server-side role enforcement to the test run deletion route and convert deletion from a pure hard-delete into an audit-log write followed by a hard-delete. Update the ehistoric template to only show the delete link for Lead users.

### Changes Required

#### 1. `robotframework_historic/app.py` — `delete_eid_conf` route (`app.py:255-258`)
- At the top of the handler, add session role check:
  ```python
  if session.get('role') != 'lead':
      return 'Forbidden', 403
  ```

#### 2. `robotframework_historic/app.py` — `delete_eid` route (`app.py:259-274`)
- At the top of the handler, add session role check:
  ```python
  if session.get('role') != 'lead':
      return 'Forbidden', 403
  ```
- Before the three DELETE statements, INSERT a snapshot row into `TB_DELETION_LOG`:
  ```python
  cursor.execute(
      "INSERT INTO TB_DELETION_LOG "
      "(execution_id, deleted_by, snapshot_execution_date, snapshot_execution_desc, "
      "snapshot_execution_pass, snapshot_execution_fail, snapshot_execution_total, "
      "snapshot_execution_time, snapshot_execution_stotal, snapshot_execution_spass, snapshot_execution_sfail) "
      "SELECT Execution_Id, %s, Execution_Date, Execution_Desc, "
      "Execution_Pass, Execution_Fail, Execution_Total, "
      "Execution_Time, Execution_STotal, Execution_SPass, Execution_SFail "
      "FROM TB_EXECUTION WHERE Execution_Id=%s",
      (session.get('email'), eid)
  )
  ```
- The existing three DELETE statements remain unchanged after this INSERT

#### 3. `robotframework_historic/templates/ehistoric.html` — delete link (`ehistoric.html:75`)
- Wrap the existing delete link in a role check:
  ```html
  {% if session.get('role') == 'lead' %}
  <a href="./deleconf/{{item[0]}}">Delete</a>
  {% endif %}
  ```

#### 4. `robotframework_historic/templates/deleconf.html`
- Add a check at the top of the confirmation page body: if `session.get('role') != 'lead'`, display an "Insufficient permissions" message instead of the confirmation form. (Belt-and-suspenders; the route handler is the true enforcement point.)

### Success Criteria

#### Automated Verification
- [ ] Unauthenticated GET to `/<db>/edelete/<eid>` returns HTTP 403 (no session at all)
- [ ] Authenticated Viewer GET to `/<db>/edelete/<eid>` returns HTTP 403
- [ ] Authenticated Lead GET to `/<db>/edelete/<eid>` returns redirect (HTTP 302) — deletion proceeds
- [ ] After Lead deletes a run: `SELECT * FROM TB_DELETION_LOG WHERE execution_id=<eid>` returns one row with correct `deleted_by` and snapshot data

#### Manual Verification
- [ ] Log in as Viewer — delete link is absent from ehistoric page
- [ ] Log in as Lead — delete link is present on ehistoric page
- [ ] Attempt direct URL navigation to `/<db>/deleconf/<eid>` as Viewer — confirm 403
- [ ] Lead completes a deletion — confirm the run disappears from ehistoric and a log row exists in `TB_DELETION_LOG`
- [ ] Dashboard metrics update correctly after deletion (no regression in `TB_PROJECT` total count)

**Pause for human confirmation before proceeding to Phase 4.**

---

## Phase 4: Deleted Runs Tab
*Jira Subtask: QE-7360 — Phase 4*

### Overview
Add a new per-project route and template that displays `TB_DELETION_LOG` rows in descending order, visible to all authenticated users. Add navigation to the tab from the execution history page.

### Changes Required

#### 1. `robotframework_historic/app.py` — new route
- Add `GET /<db>/deleted` route handler:
  ```python
  @app.route('/<db>/deleted')
  def deleted_runs(db):
      # Connect to project database
      # SELECT * FROM TB_DELETION_LOG ORDER BY deleted_at DESC
      # Render deletedhistoric.html with results
  ```
- No role check — all users (authenticated or not) can view deleted runs per ticket requirements

#### 2. `robotframework_historic/templates/deletedhistoric.html` (new file)
- Model structure after `ehistoric.html` (same nav, same project header)
- Table columns in this order (per decision in schema strategy research):
  | Column Header | Data Source |
  |---|---|
  | EID | `item['execution_id']` |
  | Deleted By | `item['deleted_by']` |
  | Deleted At | `item['deleted_at']` |
  | Date | `item['snapshot_execution_date']` |
  | Description | `item['snapshot_execution_desc']` |
  | Test Total | `item['snapshot_execution_total']` |
  | Test Pass | `item['snapshot_execution_pass']` |
  | Test Fail | `item['snapshot_execution_fail']` |
  | Time (m) | `item['snapshot_execution_time']` |
  | Suite Total | `item['snapshot_execution_stotal']` |
  | Suite Pass | `item['snapshot_execution_spass']` |
  | Suite Fail | `item['snapshot_execution_sfail']` |
- Display "No deleted runs" message when `TB_DELETION_LOG` is empty
- No delete controls on this page

#### 3. `robotframework_historic/templates/ehistoric.html` — navigation
- Add a navigation link to the Deleted Runs tab, visible to all users:
  ```html
  <a href="./deleted">Deleted Runs</a>
  ```
- Position consistent with existing navigation links in the template

### Success Criteria

#### Automated Verification
- [ ] `GET /<db>/deleted` returns HTTP 200 for an authenticated user
- [ ] `GET /<db>/deleted` returns HTTP 200 for an unauthenticated user (public read)
- [ ] After a Lead deletes a run, `GET /<db>/deleted` response body contains the deleted EID
- [ ] Empty project returns page with "No deleted runs" (or equivalent empty state)

#### Manual Verification
- [ ] Log in as Viewer — "Deleted Runs" navigation link is visible on ehistoric page
- [ ] Click "Deleted Runs" — page renders correctly with all expected columns
- [ ] Delete a run as Lead — navigate to Deleted Runs tab — confirm run appears with correct `Deleted By` (email), `Deleted At` timestamp, and snapshot data
- [ ] Deleted runs are ordered newest-first
- [ ] Existing ehistoric, dashboard, and metrics pages unaffected

**All phases complete. Ready for PR.**

---

## Testing Strategy

### Per-Phase Verification
Each phase has explicit automated and manual success criteria defined above. No phase proceeds until its criteria are met and human-confirmed.

### Regression Checks (after Phase 4)
- [ ] Login / logout flow unchanged
- [ ] New user registration works end-to-end
- [ ] New project creation succeeds and includes `TB_DELETION_LOG`
- [ ] Dashboard metrics (pass %, total count) correct after test run deletion
- [ ] Ehistoric page loads correctly with LIMIT 500

### Edge Cases
- Project database with zero executions — Deleted Runs tab shows empty state
- Lead user session expires mid-deletion — 403 returned cleanly
- Migration script run against a project DB that already has `TB_DELETION_LOG` — no error, reports already-up-to-date
- Viewer attempts direct URL deletion — 403 returned (not a redirect to login)

---

## Migration Notes

**One-time migration script** (`scripts/migrate_qe7360.py`) must be run **before** deploying the updated application code. Running order:

1. Run `scripts/migrate_qe7360.py` against the target MySQL instance
2. Set existing Lead users' `role` to `'lead'` manually (or update the migration script with known email addresses)
3. Deploy updated application code
4. Verify with smoke test: login, confirm role in session, attempt deletion as Lead and Viewer

The seed `admin@local` account is automatically set to `role = 'lead'` by the migration script.

---

## References

- Research (foundations): `.context/domains/access-control/research/current/2026-05-12-role-based-deletion-permissions.md`
- Research (schema strategy): `.context/domains/access-control/research/current/2026-05-12-deletion-log-schema-strategy.md`
- Jira ticket: [QE-7360](https://accruent.atlassian.net/browse/QE-7360)
