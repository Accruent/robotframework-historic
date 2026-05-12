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

**Check 1 — Fresh `init.sql` creates correct schema**
1. Wipe all volumes and restart: `wsl -d Ubuntu -- bash -c "docker -H unix:///mnt/wsl/shared-docker/docker.sock compose -f /mnt/c/Git/robotframework-historic/docker-compose.yml down -v && docker -H unix:///mnt/wsl/shared-docker/docker.sock compose -f /mnt/c/Git/robotframework-historic/docker-compose.yml up -d"`
2. Wait ~10 seconds for MySQL init to finish.
3. Open phpMyAdmin at [http://localhost:8081](http://localhost:8081) — login as `root` / `password`.
4. Navigate: **accounts** → **TB_USERS** → **Structure** tab.
   - Confirm `role` column exists with type `varchar(20)`, Not Null, Default `viewer`.
5. Navigate: **accounts** → **TB_USERS** → **Browse** tab.
   - Confirm the `Admin` row shows `role = lead`.
6. Navigate: **rf_full_data** → confirm `TB_DELETION_LOG` table exists in the left sidebar.
- [x] `role` column visible in TB_USERS structure with DEFAULT 'viewer'
- [x] Admin row has `role = lead`
- [x] `TB_DELETION_LOG` table exists in rf_full_data

**Check 2 — Migration against pre-existing container preserves data**
*(This was run during automated verification. Confirm data was not dropped.)*
1. Run: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT COUNT(*) FROM rf_full_data.TB_EXECUTION;"`
   - Expected: `3` (original seed rows unchanged)
2. Run: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT COUNT(*) FROM accounts.TB_USERS;"`
   - Expected: `1` (Admin row still present, not duplicated)
- [x] TB_EXECUTION row count unchanged after migration
- [x] TB_USERS row count unchanged after migration

**Check 3 — Migration script is idempotent**
1. Re-copy and re-run the migration script:
   ```
   wsl -d Ubuntu -- bash -c "docker -H unix:///mnt/wsl/shared-docker/docker.sock cp /mnt/c/Git/robotframework-historic/scripts/migrate_qe7360.py robotframework-historic-rfhistoric-1:/tmp/migrate_qe7360.py && docker -H unix:///mnt/wsl/shared-docker/docker.sock exec robotframework-historic-rfhistoric-1 python /tmp/migrate_qe7360.py --host db --port 3306 --user root --password password"
   ```
2. Confirm output shows:
   - `[SKIP] role column already exists`
   - `[SKIP] admin@local already has a non-viewer role`
   - `[OK] TB_DELETION_LOG ready` for each project (CREATE IF NOT EXISTS is a no-op)
   - `Migration complete.` with no errors or tracebacks
- [x] All steps SKIP or report already-up-to-date, no errors

**Phase 1 confirmed. ✅ Proceeding to Phase 2.**

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

**Check 1 — Login populates role in session**
*(Full UI confirmation of session['role'] requires Phase 3 delete button. Verify indirectly via DB query.)*
1. Open [http://localhost:5001](http://localhost:5001) and log in as `admin@local` / `admin`.
2. Confirm the app loads without errors after login.
3. In a separate terminal, verify the DB role: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT name, email, role FROM accounts.TB_USERS WHERE email='admin@local';"`
   - Expected: `role = lead`
- [x] Login succeeds, app loads, DB confirms admin@local has role='lead'

**Check 2 — Register a new Viewer user**
1. While logged in as `admin@local`, navigate to [http://localhost:5001/register](http://localhost:5001/register).
2. Fill in: name = `Test Viewer`, email = `viewer@local`, password = `viewer123`.
3. In the Role dropdown, select **Viewer** and submit.
4. Verify in DB: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT name, email, role FROM accounts.TB_USERS WHERE email='viewer@local';"`
   - Expected: `role = viewer`
- [x] viewer@local appears in TB_USERS with role='viewer'

**Check 3 — Register a new Lead user**
1. While still logged in, navigate to [http://localhost:5001/register](http://localhost:5001/register).
2. Fill in: name = `Test Lead`, email = `lead@local`, password = `lead123`.
3. In the Role dropdown, select **Lead** and submit.
4. Verify in DB: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT name, email, role FROM accounts.TB_USERS WHERE email='lead@local';"`
   - Expected: `role = lead`
- [x] lead@local appears in TB_USERS with role='lead'

**Check 4 — Registration form hidden when logged out**
1. Log out of the app (navigate to [http://localhost:5001/logout](http://localhost:5001/logout) or use the logout button).
2. Navigate directly to [http://localhost:5001/register](http://localhost:5001/register).
3. Confirm the registration form does not appear (page should be blank or show no form — existing behavior).
- [x] Registration form not visible when logged out

**Phase 2 confirmed. ✅ Proceeding to Phase 3.**

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

**Check 1 — Viewer does not see delete link**
1. Log in as `viewer@local` / `viewer123` (created in Phase 2).
2. Navigate to [http://localhost:5001/rf_full_data/ehistoric](http://localhost:5001/rf_full_data/ehistoric).
3. Confirm no **Delete** link appears in any row of the execution history table.
- [x] Delete link absent from all rows when logged in as Viewer

**Check 2 — Lead sees delete link**
1. Log out, then log in as `admin@local` / `admin`.
2. Navigate to [http://localhost:5001/rf_full_data/ehistoric](http://localhost:5001/rf_full_data/ehistoric).
3. Confirm a **Delete** link appears on each execution row.
- [x] Delete link visible on rows when logged in as Lead

**Check 3 — Viewer blocked from direct URL access**
1. Log out, then log in as `viewer@local` / `viewer123`.
2. Note an execution ID from the ehistoric page (e.g., `1`).
3. Navigate directly to [http://localhost:5001/rf_full_data/deleconf/1](http://localhost:5001/rf_full_data/deleconf/1).
4. Confirm a **403 Forbidden** response (not a redirect to login, not a deletion).
- [x] Direct URL to deleconf returns 403 for Viewer

**Check 4 — Lead completes a deletion; audit log written**
1. Log out, then log in as `admin@local` / `admin`.
2. On [http://localhost:5001/rf_full_data/ehistoric](http://localhost:5001/rf_full_data/ehistoric), note the total number of rows and the EID of the **last** row.
3. Click **Delete** on that row → confirm on the deleconf page → submit.
4. Confirm the run no longer appears in the ehistoric list (row count decreased by 1).
5. Verify audit log: `docker exec robotframework-historic-db-1 mysql -uroot -ppassword -e "SELECT execution_id, deleted_by, deleted_at FROM rf_full_data.TB_DELETION_LOG;"`
   - Expected: one row with `deleted_by = admin@local` and a recent `deleted_at` timestamp.
- [x] Deleted run disappears from ehistoric list
- [x] TB_DELETION_LOG contains one row with correct deleted_by and timestamp

**Check 5 — Dashboard metrics still correct after deletion**
1. Navigate to [http://localhost:5001/rf_full_data/dashboard](http://localhost:5001/rf_full_data/dashboard).
2. Confirm the page loads without errors.
3. Confirm the execution count reflects the deletion (one fewer run than before).
- [x] Dashboard loads without errors and shows updated counts

**Phase 3 confirmed. ✅ Proceeding to Phase 4.**

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

**Check 1 — Deleted Runs link visible to Viewer**
1. Log in as `viewer@local` / `viewer123`.
2. Navigate to [http://localhost:5001/rf_full_data/ehistoric](http://localhost:5001/rf_full_data/ehistoric).
3. Confirm a **Deleted Runs** navigation link is visible (all users, not just Leads).
- [ ] Deleted Runs link visible when logged in as Viewer

**Check 2 — Deleted Runs page renders with correct columns**
1. Click the **Deleted Runs** link (or navigate to [http://localhost:5001/rf_full_data/deleted](http://localhost:5001/rf_full_data/deleted)).
2. Confirm the page loads without errors.
3. Confirm the table has these column headers in order: **EID**, **Deleted By**, **Deleted At**, **Date**, **Description**, **Test Total**, **Test Pass**, **Test Fail**, **Time (m)**, **Suite Total**, **Suite Pass**, **Suite Fail**.
4. Confirm the run deleted in Phase 3 Check 4 appears in the table.
- [ ] Page loads, correct columns present, deleted run visible

**Check 3 — Snapshot data is accurate**
1. On the Deleted Runs page, find the row for the run deleted in Phase 3.
2. Confirm:
   - **Deleted By** = `admin@local`
   - **Deleted At** = a recent timestamp (today's date)
   - **Description**, **Test Total/Pass/Fail**, **Time**, **Suite Total/Pass/Fail** match the values that were visible on the ehistoric page before deletion
- [ ] Snapshot data matches what was in TB_EXECUTION before deletion

**Check 4 — Delete a second run and confirm newest-first ordering**
1. Log out, log in as `admin@local` / `admin`.
2. Delete another run from ehistoric (different EID from Phase 3).
3. Navigate to [http://localhost:5001/rf_full_data/deleted](http://localhost:5001/rf_full_data/deleted).
4. Confirm the most recently deleted run appears at the **top** of the table.
- [ ] Deleted runs ordered newest-first

**Check 5 — Regression: other pages unaffected**
1. Navigate to [http://localhost:5001/rf_full_data/dashboard](http://localhost:5001/rf_full_data/dashboard) — confirm it loads.
2. Navigate to [http://localhost:5001/rf_full_data/metrics](http://localhost:5001/rf_full_data/metrics) — confirm it loads.
3. Navigate to [http://localhost:5001/rf_full_data/ehistoric](http://localhost:5001/rf_full_data/ehistoric) — confirm remaining runs still display.
4. Log out and log back in — confirm login/logout still works.
- [ ] Dashboard, metrics, ehistoric, login/logout all unaffected

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

**One-time migration script** (`scripts/migrate_qe7360.py`) must be run **before** deploying the updated application code.

### Production Deployment Order

1. **Run migration script** (see QE-7370 for full steps)
2. **Audit users and assign Lead roles** (see QE-7369)
3. **Deploy updated application code** (`docker compose pull && docker compose up -d`)
4. **Smoke test**: log in, confirm role in session, attempt deletion as Lead and as Viewer

### Running the Migration Script

**Option A — Inside the rfhistoric container (recommended if Python/mysqlclient not on host):**
```
docker cp scripts/migrate_qe7360.py <rfhistoric-container>:/tmp/migrate_qe7360.py
docker exec <rfhistoric-container> python /tmp/migrate_qe7360.py \
  --host <db-host> --port 3306 --user <db-user> --password <db-password>
```

**Option B — On the host directly (requires Python 3 + mysqlclient):**
```
python scripts/migrate_qe7360.py --host <db-host> --port 3306 --user <db-user> --password <db-password>
```

**Expected output (all lines must appear, no tracebacks):**
```
[OK] role column added   (or [SKIP] role column already exists)
[OK] admin@local set to lead   (or [SKIP] already non-viewer)
[OK] TB_DELETION_LOG ready — <project1>
[OK] TB_DELETION_LOG ready — <project2>
...
Migration complete.
```

**Post-migration verification queries:**
```sql
SHOW COLUMNS FROM accounts.TB_USERS LIKE 'role';
SELECT name, email, role FROM accounts.TB_USERS ORDER BY created_at;
SHOW TABLES IN <project_db> LIKE 'TB_DELETION_LOG';
```

### Rollback Script

`scripts/rollback_qe7360.py` reverses the migration. Same connection args, same idempotent pattern.

**WARNING:** Drops TB_DELETION_LOG and its audit data permanently. Only run before go-live or to fully revert the feature.

**Same execution options as migration:**
```
docker cp scripts/rollback_qe7360.py <rfhistoric-container>:/tmp/rollback_qe7360.py
docker exec <rfhistoric-container> python /tmp/rollback_qe7360.py \
  --host <db-host> --port 3306 --user <db-user> --password <db-password>
```

**Expected output (first run):**
```
[OK] Dropped role column from accounts.TB_USERS
[OK] Dropped TB_DELETION_LOG from project db: <project1>
[OK] Dropped TB_DELETION_LOG from project db: <project2>
...
Rollback complete.
```

**Expected output (idempotent re-run):**
```
[SKIP] role column does not exist on accounts.TB_USERS
[OK] Dropped TB_DELETION_LOG from project db: <project1>   ← DROP IF EXISTS, always safe
...
Rollback complete.
```

### Rollback Script Verification (dev — 2026-05-12)

All three checks were run against the dev container (`robotframework-historic-rfhistoric-1` / `db:3306`).

**Check 1 — First run drops everything cleanly**
```
[OK] Dropped role column from accounts.TB_USERS
[OK] Dropped TB_DELETION_LOG from project db: rf_full_data
[OK] Dropped TB_DELETION_LOG from project db: roomba_sync_data
[OK] Dropped TB_DELETION_LOG from project db: empty_project
Rollback complete.
```
- [x] No errors, no tracebacks

**Check 2 — Idempotent re-run**
```
[SKIP] role column does not exist on accounts.TB_USERS
[OK] Dropped TB_DELETION_LOG from project db: rf_full_data   ← DROP IF EXISTS no-op
...
Rollback complete.
```
- [x] Step 1 SKIPs, Step 2 completes without error

**Check 3 — Migration round-trip: rollback → re-migrate → verify data**

Re-ran `migrate_qe7360.py` after rollback. Output:
```
[OK] Added role column to accounts.TB_USERS
[OK] Set role='lead' for admin@local
[OK] TB_DELETION_LOG ready in project db: rf_full_data
[OK] TB_DELETION_LOG ready in project db: roomba_sync_data
[OK] TB_DELETION_LOG ready in project db: empty_project
Migration complete.
```

Post-restore data verification:
```
SELECT COUNT(*) AS execution_rows FROM rf_full_data.TB_EXECUTION  → 2  (1 deleted in Phase 3 testing, expected)
SELECT COUNT(*) AS user_rows FROM accounts.TB_USERS               → 3  (Admin + 2 test users, unchanged)
admin@local role                                                   → lead  (restored by migration)
```
- [x] Seed data survived rollback + re-migration intact
- [x] admin@local role correctly restored to 'lead'
- [x] Non-admin users reset to 'viewer' default (expected — prod role assignments handled by QE-7369)

The script is idempotent — safe to re-run if interrupted.

---

## References

- Research (foundations): `.context/domains/access-control/research/current/2026-05-12-role-based-deletion-permissions.md`
- Research (schema strategy): `.context/domains/access-control/research/current/2026-05-12-deletion-log-schema-strategy.md`
- Jira ticket: [QE-7360](https://accruent.atlassian.net/browse/QE-7360)
