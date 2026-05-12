---
date: 2026-05-12
author: Neil Howell
domain: access-control
jira: QE-7360
scope: "robotframework_historic/app.py, docker/init.sql, robotframework_historic/templates/"
status: draft
---

# Research: Role-Based Access Control Foundations in RFHistoric
## Jira: QE-7360 — Add Role-Based Permissions for Test Run Deletion

### Research Question
How is the existing authentication, user model, test run deletion, and database schema structured in RFHistoric, in preparation for adding role-based delete permissions and a deleted-runs visibility tab?

### Summary
RFHistoric uses Flask session-based authentication with a simple single-table user model (`accounts.TB_USERS`). Sessions are checked in templates, not via route decorators. The application has two deletion flows: test run execution deletion and entire project/database deletion. Both deletion routes currently lack any authentication checks — they are accessible via direct URL without verifying session state. The database schema has no role, permission, or soft-delete columns; deletion is immediate via SQL DELETE statements with no audit trail.

---

### Detailed Findings

#### 1. User Model & Authentication

**User Storage:**
- Table: `accounts.TB_USERS` (`docker/init.sql:19`)
- Columns: `id` (INT AUTO_INCREMENT PRIMARY KEY), `name` (VARCHAR 255), `email` (VARCHAR 255), `password` (VARCHAR 255)
- Password storage: Bcrypt-hashed (example seed: `$2b$12$/3e9h/RIPYK2xIKOoIVXd.mpHrBT4AsWkv8wJYXTrQWJEu4Ah3v8u`)
- Default test account: `admin@local` / `admin`

**Session Management:**
- Framework: Flask `session` object (`app.py:1`)
- Session variables set at login (`app.py:47-48`):
  - `session['name']` — user's display name
  - `session['email']` — user's email
- Session cleared on logout (`app.py:67`): `session.clear()`
- Session secret key: Random 12-character alphanumeric salt generated at app startup (`app.py:632`)

**Login Flow:**
- Route: `@app.route('/login', methods=["GET","POST"])` (`app.py:37`)
- Method: POST form submission (email + password)
- Password verification via `bcrypt.hashpw()`
- No existing role/permission field in TB_USERS — all users are treated equally post-login

**Registration Flow:**
- Route: `@app.route('/register', methods=["GET", "POST"])` (`app.py:69`)
- Protection: Checks `{% if session['name'] %}` in template — only logged-in users can register new users (`templates/register.html:51`)
- Password hashing: `bcrypt.hashpw(password, bcrypt.gensalt())`

**Authentication Pattern:**
- **No route decorator pattern** (e.g., `@login_required`) — Flask-Login is not used
- Session checks occur **in templates only**, not in route handlers
- Example: `index.html:64-66` shows logout/register buttons only if `session['name']` is truthy
- Delete buttons rendered only if `{% if session['name'] %}` (`index.html:77`)
- **Critical gap:** Route handlers do NOT verify session state before executing deletion logic

---

#### 2. Current Test Run Deletion Flow

**Execution (Test Run) Deletion:**

1. **Confirmation Page Route:**
   - Path: `GET /<db>/deleconf/<eid>`
   - Handler: `delete_eid_conf(db, eid)` at `app.py:255`
   - Action: Renders `templates/deleconf.html`
   - No session check in handler

2. **Actual Deletion Route:**
   - Path: `GET /<db>/edelete/<eid>`
   - Handler: `delete_eid(db, eid)` at `app.py:259`
   - HTTP method: GET (not POST or DELETE)
   - SQL operations (`app.py:260-261`):
     ```sql
     DELETE FROM TB_EXECUTION WHERE Execution_Id='%s';
     DELETE FROM TB_SUITE WHERE Execution_Id='%s';
     DELETE FROM TB_TEST WHERE Execution_Id='%s';
     ```
   - Post-deletion: Recalculates and updates `robothistoric.TB_PROJECT` metrics (`app.py:273`)
   - Redirects to: `ehistoric` view
   - **No session check before deletion**

**Project/Database Deletion:**

1. **Confirmation Page Route:**
   - Path: `GET /<db>/deldbconf`
   - Handler: `delete_db_conf(db)` at `app.py:26`
   - Action: Renders `templates/deldbconf.html`
   - No session check

2. **Actual Deletion Route:**
   - Path: `GET /<db>/delete`
   - Handler: `delete_db(db)` at `app.py:29`
   - HTTP method: GET
   - SQL operations (`app.py:30-31`):
     ```sql
     DROP DATABASE <db>;
     DELETE FROM robothistoric.TB_PROJECT WHERE Project_Name='<db>';
     ```
   - Redirects to: `index`
   - **No session check before deletion**

**Deletion Characteristics:**
- Hard delete — immediate, permanent
- No soft-delete flag or archive state
- No audit trail or `deleted_at` timestamp
- No restoration capability

---

#### 3. Database Schema

**Core Registry Database: `robothistoric`**

Table: `TB_PROJECT` (`docker/init.sql`)
| Column | Type | Notes |
|--------|------|-------|
| Project_Id | INT AUTO_INCREMENT PK | Unique identifier |
| Project_Name | VARCHAR(255) | Database name for project |
| Project_Desc | TEXT | Pipeline link or description |
| Project_Image | TEXT | Logo/image URL |
| Created_Date | DATETIME | Creation timestamp |
| Last_Updated | DATETIME | Last metric update |
| Total_Executions | INT | Count of test runs |
| Recent_Pass_Perc | FLOAT | Most recent pass % |
| Overall_Pass_Perc | FLOAT | Aggregate pass % |

**User Accounts Database: `accounts`**

Table: `TB_USERS`
| Column | Type | Notes |
|--------|------|-------|
| id | INT AUTO_INCREMENT PK | Unique user identifier |
| name | VARCHAR(255) | Display name |
| email | VARCHAR(255) | Login email (no unique constraint) |
| password | VARCHAR(255) | Bcrypt-hashed password |

**Per-Project Databases: `{project_name}`**

Table: `TB_EXECUTION`
| Column | Type | Notes |
|--------|------|-------|
| Execution_Id | INT AUTO_INCREMENT PK | Test run identifier |
| Execution_Date | DATETIME | Timestamp of run |
| Execution_Desc | TEXT | Run description |
| Execution_Total | INT | Total test count |
| Execution_Pass | INT | Passed test count |
| Execution_Fail | INT | Failed test count |
| Execution_Time | FLOAT | Total execution time |
| Execution_STotal | INT | Total suite count |
| Execution_SPass | INT | Passed suite count |
| Execution_SFail | INT | Failed suite count |
| Execution_Skip | INT | Skipped test count |
| Execution_SSkip | INT | Skipped suite count |

Table: `TB_SUITE`
| Column | Type | Notes |
|--------|------|-------|
| Suite_Id | INT AUTO_INCREMENT PK | Suite identifier |
| Execution_Id | INT | FK to TB_EXECUTION (implicit) |
| Suite_Name | TEXT | Test suite name |
| Suite_Status | CHAR(4) | PASS or FAIL |
| Suite_Total/Pass/Fail/Skip | INT | Test counts |
| Suite_Time | FLOAT | Suite execution time |

Table: `TB_TEST`
| Column | Type | Notes |
|--------|------|-------|
| Test_Id | INT AUTO_INCREMENT PK | Test identifier |
| Execution_Id | INT | FK to TB_EXECUTION (implicit) |
| Test_Name | TEXT | Test case name |
| Test_Status | CHAR(4) | PASS or FAIL |
| Test_Time | FLOAT | Execution time |
| Test_Error | TEXT | Error message if failed |
| Test_Comment | TEXT | User-added note |
| Test_Assigned_To | TEXT | Assigned person (currently unused) |
| Test_ETA | TEXT | Estimated fix time (currently unused) |
| Test_Review_By | TEXT | Review assignment (currently unused) |
| Test_Issue_Type | TEXT | Issue classification (currently unused) |
| Test_Tag | TEXT | Test tag/category |
| Test_Updated | TEXT | Last update timestamp |

**Foreign Key Relationships:**
- `TB_SUITE.Execution_Id` → `TB_EXECUTION.Execution_Id` (implicit only — no FK constraint defined)
- `TB_TEST.Execution_Id` → `TB_EXECUTION.Execution_Id` (implicit only)
- No explicit relationship between `TB_PROJECT` and test tables (linked implicitly via database name)

**Missing Columns Relevant to This Ticket:**
- No `role` or `permission` column in `TB_USERS`
- No `owner_id` or `creator_id` in `TB_PROJECT`
- No `deleted_at`, `is_deleted`, or `deleted_by` flag in `TB_EXECUTION`
- No audit or deletion log table

---

#### 4. Template & UI Patterns

**Session Variable Usage in Templates:**

`templates/index.html` — Project list page
- Lines 64-66: Conditionally show logout/register buttons on `session['name']`
  ```html
  {% if session['name'] %}
    <a href="/logout">Logout</a>
    <a href="/register">New User</a>
  {% else %}
    <a href="/login">Login</a>
  {% endif %}
  ```
- Line 77: Delete button gated on `session['name']`
  ```html
  {% if session['name'] %}
    <a href="{{item[1]}}/deldbconf" class="btn btn-danger">Delete</a>
  {% endif %}
  ```

`templates/register.html` — User registration
- Line 51: Entire form wrapped in `{% if session['name'] %}` — non-logged-in users see blank page

`templates/ehistoric.html` — Execution history
- Line 75: Delete link rendered for each execution **without** session check:
  ```html
  <a href="./deleconf/{{item[0]}}">Delete</a>
  ```

`templates/login.html` — Login form
- No session check (publicly accessible)

**Template Inheritance:**
- **No base template** — each HTML file is standalone (no `{% extends %}` pattern)
- No Jinja2 macros for shared UI components
- Navigation bar and styling repeated in each template independently

---

#### 5. Project/User Relationships

- **No explicit user-project association** — users are global; no membership or team table exists
- All registered users have equal access to all projects
- No concept of project ownership, creator tracking, or per-project roles
- `TB_PROJECT` has no `owner_id` or `created_by` field
- Test runs in `TB_EXECUTION` have no `created_by` or `user_id` field
- Any authenticated user can currently view or delete any project or test run

---

#### 6. Soft-Delete / Deleted Run Patterns

**Current Deletion Behavior:**
- Hard delete only — `DELETE FROM TB_EXECUTION WHERE Execution_Id='%s'` (`app.py:260`)
- No `is_deleted` column, `deleted_at` timestamp, or `deleted_by` field anywhere in schema
- Deletion is immediate and permanent

**Current Listing Queries:**
- Execution history: `SELECT * from TB_EXECUTION order by Execution_Id desc LIMIT 500;` (`app.py:239`)
- Project list: `SELECT * from TB_PROJECT ORDER BY Project_Name ASC;` (`app.py:12`)
- All queries assume all rows are "active" — no filtering on deletion state

**Pagination:**
- Execution history: fixed `LIMIT 500` (`app.py:239`)
- Dashboard trend: fixed `LIMIT 10` (`app.py:141`)
- No offset-based pagination — fixed result caps only

**Restoration Capability:** None — no recovery mechanism exists without database-level binary logs.

**Audit Trail:** None — no log of deletion actor, timestamp, or reason.

---

### Code References

| File | Lines | Description |
|------|-------|-------------|
| `app.py` | 1-11 | Imports: Flask, bcrypt, mysql.connector, session |
| `app.py` | 26-34 | `delete_db_conf` / `delete_db` — project deletion routes |
| `app.py` | 37-66 | Login route — session creation |
| `app.py` | 47-48 | `session['name']` and `session['email']` assignment |
| `app.py` | 67 | `session.clear()` on logout |
| `app.py` | 69-85 | Registration route |
| `app.py` | 87-146 | Dashboard rendering |
| `app.py` | 141 | `LIMIT 10` execution trend query |
| `app.py` | 239 | `LIMIT 500` execution history query |
| `app.py` | 255-258 | `delete_eid_conf` — deletion confirmation route |
| `app.py` | 259-274 | `delete_eid` — actual test run deletion + metrics recalc |
| `app.py` | 632 | Random session secret key generation |
| `docker/init.sql` | 19 | `accounts.TB_USERS` table definition |
| `docker/init.sql` | — | `robothistoric.TB_PROJECT` table definition |
| `docker/init.sql` | — | Per-project `TB_EXECUTION`, `TB_SUITE`, `TB_TEST` definitions |
| `templates/index.html` | 64-66 | Session-gated nav buttons |
| `templates/index.html` | 77 | Session-gated project delete button |
| `templates/ehistoric.html` | 75 | Execution delete link (no session gate) |
| `templates/register.html` | 51 | Session-gated registration form |

---

### Constraints Discovered

**Authentication & Session:**
- Flask default session is signed but not encrypted; tamper-resistant but readable client-side
- Session secret is regenerated on every app restart — all sessions invalidated on redeploy
- No session expiry or timeout mechanism
- No CSRF protection on any form or route
- No `@login_required` decorator or equivalent — all auth enforcement is template-side only

**Database Schema:**
- No FK constraints defined — referential integrity not enforced at DB level
- No unique constraint on `email` in `TB_USERS` — duplicate emails can exist
- Dynamic per-project databases — no centralized schema migration mechanism
- Schema changes to per-project tables require re-running DDL against every project DB

**SQL Safety:**
- String interpolation used in DELETE/DROP queries: `"DELETE FROM TB_EXECUTION WHERE Execution_Id='%s';" % eid`
- Input validation absent on `db` and `eid` URL parameters
- Direct SQL injection risk via malicious URL parameters

**Deletion Model:**
- Hard delete only; no transaction wrapping around the three-table delete cascade
- Metrics recalculation runs after deletion; partial failure leaves metrics stale

---

### Open Questions

1. **Project Ownership Model:** Should Lead role be per-project (only leads of project X can delete in project X) or global (all Leads can delete anywhere)?

2. **Soft-Delete Schema Strategy:** Should `is_deleted` / `deleted_at` / `deleted_by` columns be added to `TB_EXECUTION`, or should a separate audit/tombstone table be created?

3. **Deleted Runs Tab Scope:** Should deleted runs be visible across all projects on one tab, or per-project only (consistent with current project-scoped views)?

4. **Retention Policy:** How long should soft-deleted runs be retained before permanent purge?

5. **Auth Enforcement Layer:** Should route-level protection use a Flask `@login_required`-style decorator, or is session verification inline in each handler sufficient?

6. **Audit Trail Requirement:** Is a `TB_DELETION_LOG` table (actor, target, timestamp) needed, or is the soft-delete row itself sufficient audit?

7. **Per-Project DB Schema Migration:** For soft-delete, who/what runs `ALTER TABLE TB_EXECUTION ADD COLUMN is_deleted...` against every existing project database?
