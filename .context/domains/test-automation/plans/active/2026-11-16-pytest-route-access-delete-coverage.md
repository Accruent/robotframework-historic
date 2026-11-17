---
date: 2026-11-16
author: Neil Howell
domain: test-automation
jira: QE-7619
research: .context/domains/test-automation/research/current/2026-11-16-pytest-route-access-delete-coverage.md
status: draft
phases: 4
---

# QE-7619: Lightweight pytest Coverage for Routes, Access Control and Delete Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan phase by phase. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview
Add a pytest suite that uses Flask `test_client` against the real docker-compose MySQL seed. The suite covers read-only page smoke checks, lead-only access control, the `edelete` transaction, and schema/migration idempotence. pytest runs in a dedicated `tests` compose service on the `rf` network, so no venv or host Python is needed. The existing required `build-and-smoke` PR job runs the suite as an extra step. `app.py` is not refactored.

---

## Current State Analysis

*(Full details in research artifact. Key facts for implementation:)*

- The repo has no tests, no pytest config, and no pytest dependency.
- `app = Flask(...)` and `mysql = MySQL(app)` are created at module level (`app.py:13-15`). `MYSQL_*` config and `secret_key` are only set in `main()` (`app.py:465-481`).
- The compose `db` service (`docker-compose.yml:5-18`) publishes no port and has no healthcheck. It is reachable as `db:3306` on network `rf`, with root password `password`.
- `docker/init.sql` seeds `rf_full_data` (3 executions, with suites and tests), `roomba_sync_data` (2 executions, executions only) and `empty_project` (0 rows). The only user is `admin@local` / `admin`, role `lead`. No viewer user is seeded.
- Lead guards (`session.get('role') != 'lead'` → `'Forbidden', 403`) are on `/<db>/deldbconf`, `/<db>/delete`, `/register`, `/newdb`, `/<db>/deleconf/<eid>` and `/<db>/edelete/<eid>`.
- `delete_eid` (`app.py:241-314`): audit `INSERT ... SELECT`. If `rowcount == 0` it rolls back and returns 302. Otherwise it runs 3 DELETEs, updates the `TB_PROJECT` summary and commits once. A `MySQLdb.Error` triggers a rollback and returns `'Delete failed; no changes were saved', 500`.
- `add_db` (`app.py:99-158`) swallows exceptions and always returns 302. Results must be checked in `information_schema`.
- `scripts/migrate_qe7617.py` supports `--host/--port/--user`, `--db`/`--all` and `--dry-run`. Its output uses `[OK]/[SKIP]/[DRY-RUN]/[WARN]/[ERROR]` and it exits 1 on error. The password comes from `MYSQL_PWD` → `PASSWORD`.
- `.github/workflows/pr-build.yml` job `build-and-smoke` (the required check on `master`) does build → `up -d` → curl smoke → dump logs on failure → `down -v`.

---

## Desired End State

- `docker compose up -d db` followed by `docker compose --profile test run --rm tests` runs the full suite on any machine with Docker and exits 0. No venv or host Python is used.
- Every ticket case has a named test: smoke, access control (unauthenticated/viewer/lead), delete flow (rows removed, one audit row, summary updated, repeat is a no-op, forced error → 500 + rollback), `/newdb` indexes, and migrate dry-run and rerun idempotence.
- Seed DBs are only read. Destructive tests use throwaway `pytest_<hex>` project DBs that fixtures create and drop.
- `build-and-smoke` runs pytest after the curl smoke. A failing test fails the required check and blocks the merge.

---

## What We're NOT Doing

- No browser/UI automation and no coverage targets.
- No changes to `robotframework_historic/app.py`, `args.py`, or templates. No app factory. Bugs found during testing are reported, not fixed here.
- No `pytest` in `requirements.txt` or `setup.py`. The runtime image is unchanged.
- No new seed users in `docker/init.sql`. Viewer and lead sessions are injected.
- No host port on `db` and no new required status check.
- No SQL mocking. The forced DB error uses real schema sabotage in a throwaway DB.

---

## Implementation Approach

**Decisions (agreed in design discussion):**
1. **Runner:** a dedicated `tests` compose service (profile `test`) built from `tests/Dockerfile`, on network `rf`.
2. **CI:** add a pytest step to the existing `build-and-smoke` job.
3. **Sessions:** use `client.session_transaction()` for viewer and lead. One real `/login` test uses the seeded `admin@local`. Test dependencies go in `requirements-test.txt`.
4. **Isolation:** destructive tests use throwaway DBs created through a lead `POST /newdb` and dropped in teardown.

**Approaches rejected:** host Python plus a published `3306` port (machine-specific MySQL client setup on Windows, and it exposes the DB). Exec into `rfhistoric` (would put test dependencies in the runtime image or install them on every run).

**File map:**

| File | Action | Responsibility |
|---|---|---|
| `requirements-test.txt` | Create | `pytest` pin |
| `tests/Dockerfile` | Create | `python:3.14` + `pip install .` + test deps |
| `tests/conftest.py` | Create | App config, DB wait, client/session and throwaway-DB fixtures |
| `tests/test_smoke.py` | Create | Read-only pages return 200 on seed DBs |
| `tests/test_access_control.py` | Create | 403 / allowed matrix + login |
| `tests/test_delete_flow.py` | Create | `edelete` transaction cases |
| `tests/test_schema.py` | Create | `/newdb` indexes, migrate dry-run and rerun |
| `pytest.ini` | Create | `testpaths = tests`, `-ra` |
| `docker-compose.yml` | Modify | Add `tests` service (profile `test`) |
| `.github/workflows/pr-build.yml` | Modify | Add `Run pytest` step |
| `README.md` | Modify | Add a "Running tests" section |

Run everything with Docker. Do not create virtual environments.

---

## Phase 1: Test Runner Scaffolding

### Changes Required

#### 1. `requirements-test.txt` (new)
```
pytest~=8.4
```

#### 2. `tests/Dockerfile` (new)
```dockerfile
FROM python:3.14
WORKDIR /app
COPY . /app
RUN pip install . -r requirements-test.txt
CMD ["pytest"]
```

#### 3. `pytest.ini` (new)
```ini
[pytest]
testpaths = tests
addopts = -ra
```

#### 4. `docker-compose.yml` — add service after `rfhistoric`
```yaml
  # tests - run with: docker compose --profile test run --rm tests
  tests:
    profiles: ["test"]
    depends_on:
      - db
    build:
      context: .
      dockerfile: tests/Dockerfile
    environment:
      SQLHOST: db
      PORT: 3306
      USERNAME: root
      PASSWORD: password
    volumes:
      - ./:/app
    networks:
      - rf
```
The `./:/app` mount runs local edits without a rebuild. `pip install .` installs the package into site-packages. `tests` imports `robotframework_historic` from `/app` first because pytest's rootdir is on `sys.path`, so the mounted source is the code under test.

#### 5. `tests/conftest.py` (new) — fixtures and helpers
- Module constants are read from the environment: `DB_HOST = os.environ.get('SQLHOST', 'db')`, `DB_PORT = int(os.environ.get('PORT', 3306))`, `DB_USER = os.environ.get('USERNAME', 'root')`, `DB_PASSWORD = os.environ.get('PASSWORD', 'password')`.
- `SEED_DBS = ['rf_full_data', 'roomba_sync_data', 'empty_project']`.
- `wait_for_db(timeout=120)`: retries `MySQLdb.connect(...)` every 2 s until `SELECT COUNT(*) FROM robothistoric.TB_PROJECT` returns ≥ 3 (init.sql has finished). Calls `pytest.fail` on timeout.
- `@pytest.fixture(scope='session') app_config`: calls `wait_for_db()`, imports `from robotframework_historic.app import app`, then sets `app.config.update(MYSQL_HOST=..., MYSQL_PORT=..., MYSQL_USER=..., MYSQL_PASSWORD=..., TESTING=True)` and `app.config['auth_plugin'] = 'mysql_native_password'`, with the same keys `main()` uses (`app.py:469-475`), plus `app.secret_key = 'pytest'`. Returns `app`.
- `@pytest.fixture client(app_config)`: `app_config.test_client()`.
- `login_as(client, role, email='pytest@local')`: in `client.session_transaction()`, sets `sess['role']`, `sess['email']` and `sess['name']`.
- `@pytest.fixture viewer(client)` / `lead(client)`: return a client with that session injected.
- `@pytest.fixture db_conn()`: a direct `MySQLdb.connect(..., autocommit=True)` with `DictCursor`, used for setup and assertions. Closed in teardown.
- `@pytest.fixture throwaway_db(lead, db_conn)`:
  - `name = f'pytest_{uuid.uuid4().hex[:8]}'`.
  - `lead.post('/newdb', data={'dbname': name, 'dbdesc': 'pytest', 'dbimage': ''})`, then asserts 302 and that `information_schema.SCHEMATA` has `name`.
  - Seeds 2 executions: eid 1 with 2 suites + 3 tests, and eid 2 with 1 suite + 1 test, with distinct pass/fail counts so `Recent_Pass_Perc` changes are visible.
  - Sets `robothistoric.TB_PROJECT.Total_Executions=2` for `name`.
  - Yields `name`.
  - Teardown: ``DROP DATABASE IF EXISTS `name` `` and `DELETE FROM robothistoric.TB_PROJECT WHERE Project_Name=%s`. Uses SQL, not the `/delete` route, so teardown does not depend on code under test.
- `count(db_conn, sql, args=())`: returns the scalar `COUNT(*)`.



### Success Criteria

#### Automated Verification
- [x] `docker compose up -d db` → `db` running
- [x] `docker compose --profile test build tests` → image builds, exit 0
- [x] Add a temporary `tests/test_placeholder.py` containing `def test_db(app_config): pass`. Run `docker compose --profile test run --rm tests` → `1 passed`. Then delete the placeholder.
- [x] `docker compose build rfhistoric ; docker compose up -d` → `rfhistoric` unaffected; `(Invoke-WebRequest http://localhost:5001/).StatusCode` → `200`
- [x] `docker compose config --services` (without a profile) → `tests` not listed, so a plain `up -d` does not start it

---

## Phase 2: Smoke and Access-Control Tests

### Changes Required

#### 1. `tests/test_smoke.py` (new)
- `test_index_200(client)` → `GET /` 200.
- `@pytest.mark.parametrize('db', SEED_DBS)` and `@pytest.mark.parametrize('path', ['dashboard', 'ehistoric', 'deleted', 'tmetrics', 'flaky', 'compare', 'search'])`: `test_project_page_200(client, db, path)` → `GET /{db}/{path}` 200.
- Execution-scoped pages are parametrized over `[('rf_full_data', <first eid>), ('roomba_sync_data', <first eid>)]` × `['metrics', 'tmetrics', 'failures']`. Each eid is read from the DB at collection time in a fixture (`SELECT MIN(Execution_Id)`) and is not hard-coded. `test_execution_page_200` → 200. `empty_project` has no executions and is excluded from eid pages.
- Every smoke request asserts that the response contains no Python traceback text (`b'Traceback' not in resp.data`).

#### 2. `tests/test_access_control.py` (new)
- `GUARDED = [('GET','/register'), ('GET','/newdb'), ('GET','/rf_full_data/deldbconf'), ('GET','/rf_full_data/delete'), ('GET','/rf_full_data/deleconf/1'), ('GET','/rf_full_data/edelete/1'), ('POST','/register'), ('POST','/newdb')]`.
- `test_unauthenticated_forbidden(client, method, path)` → 403 for every `GUARDED` entry.
- `test_viewer_forbidden(viewer, method, path)` → 403 for every `GUARDED` entry.
- After each test, a `db_conn` assertion checks that the seed is intact: `rf_full_data` still exists and `rf_full_data.TB_EXECUTION` count is unchanged. This proves a 403 had no side effect.
- Lead allowed, non-destructive only:
  - `GET /register`, `GET /newdb`, `GET /rf_full_data/deldbconf` and `GET /rf_full_data/deleconf/1` → 200.
  - Lead `edelete` and `newdb` POST are covered in Phases 3–4.
  - Lead `GET /<db>/delete` → 302, and the DB is gone from `SCHEMATA` and `TB_PROJECT`. Run it against `throwaway_db`, never a seed DB.
  - Lead `POST /register` → 302 and the user exists in `accounts.TB_USERS`. Uses a unique `pytest_<hex>@local` email; teardown deletes the row.
- Public routes stay public: `test_public_routes_no_session(client)` → `/`, `/login`, `/rf_full_data/dashboard` 200.
- `test_login_seeded_lead(client)`: `POST /login` with `admin@local`/`admin` → 302 to `/`. `session['role'] == 'lead'` (read via `session_transaction`). A following `GET /newdb` → 200.
- `test_login_wrong_password(client)` → 302 to `/login`, no `role` in the session.
- `test_logout_clears_session(lead)` → `GET /logout` 302, then `GET /newdb` 403.

### Success Criteria

#### Automated Verification
- [x] `docker compose --profile test run --rm tests pytest tests/test_smoke.py tests/test_access_control.py` → all pass, exit 0 (dashboard redirects asserted as 302; `empty_project` tmetrics/flaky are strict xfail app bugs)
- [x] Negative control: temporarily change the `/register` guard to `!= 'viewer'` in the local working tree. Rerun → `test_unauthenticated_forbidden`/`test_viewer_forbidden[GET-/register]` fail. Revert, and confirm with `git diff --stat robotframework_historic/` that nothing is changed.
- [x] After the run: `docker compose exec db mysql -uroot -ppassword -e "SELECT Project_Name FROM robothistoric.TB_PROJECT;"` → only the 3 seed projects (no leftover `pytest_*`)

> Outcome: `roomba_sync_data` and `empty_project` dashboards return 302 by design (to `ehistoric` and `/redirect`). They are asserted as redirects in `test_dashboard_redirects_without_full_data`. On `empty_project`, `tmetrics` (QE-7656) and `flaky` (QE-7657) return 500. Both are marked `xfail(strict=True)` with the ticket key in the reason. Remove the marker when the ticket is fixed.
> pytest.ini sets `pythonpath = .` so the mounted `/app` source is under test, not the installed copy in site-packages.

**If any smoke page returns non-200 on a seed DB, stop and report it to the user. It is an app bug found by the test. Do not change `app.py` and do not silently exclude the page.**

---

## Phase 3: Delete-Flow and Schema Tests

### Changes Required

#### 1. `tests/test_delete_flow.py` (new) — all tests use `throwaway_db`
- `test_lead_delete_removes_rows_and_audits(lead, throwaway_db, db_conn)`:
  - `GET /{db}/edelete/1` → 302 to `/{db}/ehistoric`.
  - `TB_EXECUTION`/`TB_SUITE`/`TB_TEST` have 0 rows where `Execution_Id=1`. Eid 2 rows are untouched.
  - `TB_DELETION_LOG` has exactly 1 row with `execution_id=1`, `deleted_by='pytest@local'`, and snapshot pass/fail/total equal to the seeded eid 1 values.
  - `robothistoric.TB_PROJECT` for `db`: `Total_Executions=1` and `Recent_Pass_Perc` equal to eid 2's pass % (computed as `app.py:286-298` does, rounded the same way).
- `test_repeat_delete_is_noop(lead, throwaway_db, db_conn)`: delete eid 1 twice → both return 302. `TB_DELETION_LOG` count for eid 1 is still 1. The `TB_PROJECT` row (`Total_Executions`, `Recent_Pass_Perc`, `Last_Updated`) is identical before and after the second request.
- `test_delete_last_execution_zeroes_summary(lead, throwaway_db, db_conn)`: delete eid 1 and then eid 2 → `Total_Executions=0`, `Recent_Pass_Perc=0`, and `GET /{db}/ehistoric` → 200.
- `test_delete_execution_without_children(lead, throwaway_db, db_conn)`: insert eid 3 with no suite/test rows, delete it → 302 and 1 audit row.
- `test_db_error_returns_500_and_rolls_back(lead, throwaway_db, db_conn)`:
  - Before: count rows for eid 1 in `TB_EXECUTION`/`TB_SUITE`, count `TB_DELETION_LOG` rows, and read the `TB_PROJECT` row.
  - ``RENAME TABLE `{db}`.TB_TEST TO `{db}`.TB_TEST_x``. The DELETE on `TB_TEST` raises `MySQLdb.ProgrammingError`, a subclass of `MySQLdb.Error`, after the audit INSERT and the suite/execution deletes.
  - `GET /{db}/edelete/1` → 500 and the body contains `Delete failed; no changes were saved`.
  - Assert the audit count is unchanged, the eid 1 `TB_EXECUTION` and `TB_SUITE` rows are still present, and the `TB_PROJECT` row is unchanged.
  - Rename the table back in `finally`.
- `test_viewer_and_unauth_cannot_delete(client, viewer, throwaway_db, db_conn)`: both get 403, and the rows and audit count are unchanged.

> Verified: the DELETE order is `TB_EXECUTION` (`app.py:268`) → `TB_SUITE` (`:272`) → `TB_TEST` (`:276`), so the `TB_TEST` rename fails after the audit INSERT and two DELETEs.

#### 2. `tests/test_schema.py` (new)
- `test_newdb_creates_execution_id_indexes(throwaway_db, db_conn)`: `information_schema.STATISTICS` for `throwaway_db` has `idx_suite_execution_id` on `TB_SUITE` and `idx_test_execution_id` on `TB_TEST`, each with `COLUMN_NAME='Execution_Id'` and `SEQ_IN_INDEX=1`. `TB_DELETION_LOG` exists.
- `test_newdb_registers_project(throwaway_db, db_conn)`: there is 1 `robothistoric.TB_PROJECT` row for the name.
- Migration tests run the script as a subprocess: `subprocess.run([sys.executable, 'scripts/migrate_qe7617.py', '--host', DB_HOST, '--port', str(DB_PORT), '--user', DB_USER, '--db', name, *extra], env={**os.environ, 'MYSQL_PWD': DB_PASSWORD}, capture_output=True, text=True)`.
  - `test_migrate_dry_run_no_change(throwaway_db, db_conn)`: drop both indexes from the throwaway DB. Run with `--dry-run` → exit 0 and stdout has `[DRY-RUN]` for both tables. STATISTICS still shows no `Execution_Id` index.
  - `test_migrate_then_rerun_idempotent(throwaway_db, db_conn)`: drop both indexes. The first run exits 0 with 2 `[OK]` lines and the indexes are present. The second run exits 0 with 2 `[SKIP]` lines and no `[OK]`. STATISTICS still shows exactly one `Execution_Id`-leading index per table.
  - `test_migrate_on_already_indexed_db_skips(throwaway_db)`: a fresh `/newdb` DB → 2 `[SKIP]` lines, exit 0.

> Verified: `--port` (`migrate_qe7617.py:31`); output strings `[DRY-RUN]` (`:109`), `[OK]` (`:113`) and `[SKIP] ... existing index` (`:140`).

### Success Criteria

#### Automated Verification
- [x] `docker compose --profile test run --rm tests pytest tests/test_delete_flow.py tests/test_schema.py -v` → all pass
- [x] `docker compose --profile test run --rm tests` (full suite) → all pass. Run it **3 times in a row** without `down -v`, and each run passes, which proves the seed is untouched.
- [x] Negative control: temporarily comment out `mysql.connection.rollback()` in the `except` of `delete_eid`. `test_db_error_returns_500_and_rolls_back` should fail; if it passes, the test is not proving rollback. Revert, then `git diff --stat robotframework_historic/` → empty.
  - Result: the test still passed. Flask-MySQLdb closes the connection at request teardown and MySQL discards the uncommitted transaction, so removing the explicit rollback does not change the outcome. Substitute control: replacing the rollback with `commit()` makes the test fail (audit row persisted). Reverted; the diff is empty.
- [x] After the runs: `docker compose exec db mysql -uroot -ppassword -e "SHOW DATABASES LIKE 'pytest_%';"` → empty

**Pause for human confirmation before Phase 4.**

---

## Phase 4: CI Integration and Docs

### Changes Required

#### 1. `.github/workflows/pr-build.yml`
Insert after the `Smoke test` step and before `Dump logs`:
```yaml
      - name: Run pytest
        run: docker compose --profile test run --rm tests
```
The curl smoke already waited for MySQL init, and `conftest.wait_for_db` also retries. The existing `Dump logs` (`if: failure()`) and `Tear down` (`if: always()`, `down -v`) steps cover this step. The job name `build-and-smoke` is unchanged, so branch protection needs no change.

#### 2. `README.md`
Add a short "Running tests" section:
```
docker compose up -d db
docker compose --profile test run --rm tests
docker compose --profile test run --rm tests pytest tests/test_delete_flow.py -v
```
Note that no venv or host Python is needed and that tests leave the seed DBs unchanged. Note the two known `xfail` app bugs, QE-7656 and QE-7657.

### Success Criteria

#### Automated Verification
- [x] Locally simulate the CI order: `docker compose down -v ; docker compose build rfhistoric ; docker compose up -d`, then run the curl checks, then `docker compose --profile test run --rm tests` → exit 0
- [x] Push the branch and open a PR to `master` (with user approval) → the `build-and-smoke` check shows a `Run pytest` step listing `N passed` and is green (PR #166: 64 passed, 2 xfailed)
- [x] Negative control on a throwaway branch or commit (with user approval): make one test assert the wrong status → `build-and-smoke` fails and the PR shows merge blocked. Revert. (PR #166: failed and BLOCKED, then reverted)

#### Manual Verification
- [x] PR checks page: `build-and-smoke` is still the only required check and it blocks the merge when red (PR #166: only `PR Build Check / build-and-smoke` is marked Required; 22d1bcb was red and blocked)
- [ ] README instructions work as written from the root of a working copy on Windows (PowerShell)

---

## Testing Strategy

| Ticket item | Test(s) |
|---|---|
| conftest app fixture + unauth/viewer/lead helpers | `conftest.py`: `app_config`, `client`, `viewer`, `lead`, `login_as` |
| Smoke: read-only pages 200 per seed DB | `test_smoke.py` (`test_index_200`, `test_project_page_200`, `test_execution_page_200`) |
| Access: 403 unauth/viewer, works for lead | `test_access_control.py` (`test_unauthenticated_forbidden`, `test_viewer_forbidden`, lead-allowed tests, login/logout) |
| Delete: rows removed, 1 audit row, summary updated | `test_lead_delete_removes_rows_and_audits` |
| Delete: repeat → no second audit row | `test_repeat_delete_is_noop` |
| Delete: DB error → 500 + rollback | `test_db_error_returns_500_and_rolls_back` |
| Schema: `/newdb` indexes | `test_newdb_creates_execution_id_indexes` |
| Schema: migrate dry-run / rerun idempotent | `test_migrate_dry_run_no_change`, `test_migrate_then_rerun_idempotent` |
| Runs locally on compose, no venv | Phase 1/3 commands |
| Runs on every PR and blocks merge | Phase 4 `Run pytest` step in required `build-and-smoke` |

---

## Risks

| Risk | Mitigation |
|---|---|
| A smoke page fails on a seed DB (e.g. `roomba_sync_data` with no suites, or `empty_project`) because of a real bug | Stop and report it (Phase 2 gate). Do not change `app.py` in this ticket. Found: QE-7656 (`tmetrics`) and QE-7657 (`flaky`) on `empty_project`, tracked as strict xfail. |
| The `./:/app` mount shadows the installed package and causes a version mismatch | Both come from the same source tree. CI uses a fresh checkout. |
| Flask-MySQLdb caches the connection per app context, so `session_transaction` and requests share state | Each request gets its own app context in `test_client`. `db_conn` is a separate autocommit connection. |
| The table rename in the error test leaks if an assertion fails | Rename back in `finally`. The throwaway DB is dropped in teardown anyway. |
| `add_db` swallows errors, so the throwaway fixture could yield a half-built DB | The fixture asserts on `SCHEMATA` and the tables before yielding. |
| MySQL init is slow on the CI runner | `wait_for_db` polls for up to 120 s, after the curl smoke retries. |
| Leftover `pytest_*` DBs after an aborted local run | Teardown uses `DROP ... IF EXISTS`. `docker compose down -v` fully resets. |
| `/<db>/delete` interpolates the route value into `DROP DATABASE` | Tests only call it on fixture-generated `pytest_<hex>` names. Hardening it is out of scope; flag it for a follow-up. |

## External Dependencies
- Docker Desktop (local) and Docker on the `ubuntu-latest` GitHub runner. Both are already used by `build-and-smoke`.
- PyPI access during the `tests` image build (`pytest`).
- `master` branch protection with `build-and-smoke` as the required check (set up by QE-7618). It needs no change.

## References
- Research: `.context/domains/test-automation/research/current/2026-11-16-pytest-route-access-delete-coverage.md`
- Manual cases source: `.github/copilot-instructions.md`, `.context/domains/database-performance/plans/archive/2026-11-11-execution-delete-latency-indexes.md`
- CI: `.github/workflows/pr-build.yml`
