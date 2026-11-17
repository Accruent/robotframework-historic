---
date: 2026-11-16
author: Neil Howell
domain: test-automation
jira: QE-7619
scope: "robotframework_historic/app.py, robotframework_historic/args.py, docker/init.sql, docker-compose.yml, Dockerfile, requirements.txt, setup.py, scripts/migrate_qe7617.py, scripts/rollback_qe7617.py, .github/workflows/pr-build.yml, .github/workflows/build-and-publish.yml"
status: complete
---

# Research: Lightweight pytest Coverage for Routes, Access Control and Delete Flow
## Jira: QE-7619 — RF Historic | Add lightweight pytest coverage for routes, access control and delete flow

### Research Question
What do we need to know to close QE-7619?

### Summary
The repo has no tests, no `tests/` directory, no pytest config, and pytest is not in `requirements.txt`. The app is one module-level Flask object (`app.py:13`) with `MySQL(app)` bound at import (`app.py:15`). MySQL config and `secret_key` are only set inside `main()` (`app.py:465-481`), so a test fixture must set them on the imported `app` itself. The compose `db` service publishes no host port (`docker-compose.yml:5-18`), so a host-side `test_client` cannot reach MySQL without a port mapping or running pytest inside the compose network. `docker/init.sql` seeds three project DBs and one `lead` user (`admin@local`/`admin`). No `viewer` user is seeded. All five ticket areas map to existing code: lead guards on 6 routes, the `edelete` transaction with audit, idempotence and 500 rollback, `/newdb` index DDL, and an idempotent `migrate_qe7617.py` with `--dry-run`. The PR workflow `pr-build.yml` exists. Its job `build-and-smoke` runs curl smoke checks against compose. The QE-7618 plan records it as the required status check on `master`.

---

### Detailed Findings

#### 1. Ticket Context (from Jira)
- Status: Develop.
- Approach: pytest + Flask `test_client` against the docker-compose MySQL seed. No SQL mocking.
- Scope: `tests/conftest.py` app fixture pointed at the compose DB, with helpers for unauthenticated, viewer and lead sessions. Smoke tests return 200 for read-only pages on every seed DB. Access-control tests cover 403/allowed. Delete-flow tests cover rows removed, one audit row, summary updated, a repeat writing no second audit row, and a forced DB error giving 500 with rollback. Schema tests cover `/newdb` indexes and `migrate_qe7617` dry-run/rerun idempotence. Tests run in the PR workflow on compose services.
- Out of scope: browser/UI automation, coverage targets, refactoring `app.py`.
- AC: pytest passes locally against docker compose with no venv. Every access-control and delete-flow case has a test. Tests run on every PR to master and block the merge on failure.

#### 2. App Construction and Configuration (`robotframework_historic/app.py`)
- `app = Flask(...)` at module level, `app.py:13`. `mysql = MySQL(app)` at `app.py:15`. There is no app factory.
- `main()` at `app.py:465` parses args (`args.py`) and sets `MYSQL_HOST/PORT/USER/PASSWORD` (`app.py:469-472`) and `auth_plugin` (`app.py:475`). It sets a random 12-char `app.secret_key` (`app.py:479`) and calls `app.run` (`app.py:481`).
- Importing `robotframework_historic.app` does not set DB config or a secret key. Sessions need `secret_key` set. Flask `test_client().session_transaction()` can then inject `role`/`email` directly.
- Every DB route switches DB with `use_db(cursor, name)` → `USE <name>` (`app.py:438-439`), so one MySQL connection serves registry, accounts and project DBs.
- `import config` (`app.py:10`) refers to the `config~=0.5.1` package.

#### 3. Routes and Guards
| Line | Route | Methods | Guard |
|---|---|---|---|
| 18 | `/` | GET | none |
| 27 | `/redirect` | GET | none |
| 31 | `/<db>/deldbconf` | GET | lead (`:33`) |
| 37 | `/<db>/delete` | GET | lead (`:39`) — `DROP DATABASE` |
| 48 | `/login` | GET, POST | none |
| 73 | `/logout` | GET, POST | none |
| 78 | `/register` | GET, POST | lead (`:80`) |
| 99 | `/newdb` | GET, POST | lead (`:101`) |
| 161 | `/<db>/dashboard` | GET | none |
| 211 | `/<db>/ehistoric` | GET | none |
| 220 | `/<db>/deleted` | GET | none |
| 235 | `/<db>/deleconf/<eid>` | GET | lead (`:237`) |
| 241 | `/<db>/edelete/<eid>` | GET | lead (`:243`) |
| 316 | `/<db>/tmetrics` | GET, POST | none (POST commits, `:324`) |
| 334 | `/<db>/metrics/<eid>` | GET | none |
| 352 | `/<db>/tmetrics/<eid>` | GET, POST | none (POST commits, `:360`) |
| 367 | `/<db>/failures/<eid>` | GET, POST | none (POST commits, `:375`) |
| 382 | `/<db>/search` | GET, POST | none |
| 394 | `/<db>/flaky` | GET | none |
| 417 | `/<db>/compare` | GET, POST | none |
- Guard pattern: `if session.get('role') != 'lead': return 'Forbidden', 403`. It blocks unauthenticated and viewer sessions alike.
- `/login` POST (`app.py:49-70`) does `len(user)` on `fetchone()`. An unknown email gives `None`, so that path raises. A known user with a wrong password redirects to `/login`.
- `/register` POST (`app.py:81-97`) inserts into `accounts.TB_USERS` with `role` from the form (default `viewer`). It overwrites `session['name']`/`['email']` but not `role`.

#### 4. Delete Flow (`/<db>/edelete/<eid>`, `app.py:241-314`)
- Audit row: `INSERT INTO TB_DELETION_LOG ... SELECT ... FROM TB_EXECUTION WHERE Execution_Id=%s` with `deleted_by=session['email']` (`:250-260`).
- Idempotence: `rowcount == 0` → rollback and 302 to `ehistoric` (`:261-264`). No second audit row and no summary update.
- Deletes from `TB_EXECUTION`, `TB_SUITE` and `TB_TEST` by `Execution_Id` (`:268-279`).
- Summary: recomputes count and recent pass % from the last remaining execution. `UPDATE robothistoric.TB_PROJECT SET Total_Executions, Last_Updated, Recent_Pass_Perc WHERE Project_Name=%s` (`:294-298`). Zero executions → `Recent_Pass_Perc=0` (`:286-292`).
- One commit (`:301`). Any `MySQLdb.Error` → rollback, `logger.exception`, `'Delete failed; no changes were saved', 500` (`:303-306`). Non-MySQL exceptions are not caught.
- Success logs one INFO timing line (`:308-313`) and returns 302 to `ehistoric`.
- The error path needs a `MySQLdb.Error` raised inside the `try`. The DB is real, so this can be done by monkeypatching the cursor/connection or by schema-level sabotage (e.g. a missing table).

#### 5. `/newdb` Schema Creation (`app.py:99-158`)
- `CREATE DATABASE <name>`, then insert the `TB_PROJECT` row (`%`-interpolated). Then create `TB_EXECUTION`, and `TB_SUITE` with `INDEX idx_suite_execution_id (Execution_Id)` (`:129`). Then `TB_TEST` with `INDEX idx_test_execution_id (Execution_Id)` (`:136`), and `TB_DELETION_LOG`. One commit (`:152`).
- Exceptions are printed and swallowed. `finally` always redirects to index (`:153-156`). A failure still returns 302, so a test must check `information_schema` for the result.
- Created DBs persist in the `db_data` volume until `docker compose down -v` or `/<db>/delete`.

#### 6. Seed Data (`docker/init.sql`)
- Creates `robothistoric` and `accounts` (`:12-13`). `accounts.TB_USERS` (`:17-23`) has a single user, `Admin`, `admin@local`, password `admin`, role `lead` (`:25-27`). No viewer user.
- `robothistoric.TB_PROJECT` seeds `rf_full_data` (3 executions), `roomba_sync_data` (2) and `empty_project` (0) (`:43-46`).
- Project DBs at `:52` (`rf_full_data`: executions + suites + tests), `:151` (`roomba_sync_data`: executions only) and `:226` (`empty_project`: no rows). Each has `TB_DELETION_LOG` and the Execution_Id indexes.
- init.sql runs only when the `db_data` volume is first initialised. Destructive tests (edelete, newdb) change seed state across runs unless the volume is reset or the tests restore state.

#### 7. Docker Compose / Dockerfile
- `db`: `mysql:5.7`, strict SQL mode, root password `password`, init.sql mounted, network `rf`, **no `ports`** and no healthcheck (`docker-compose.yml:5-18`).
- `rfhistoric`: local build, `5001:5000`, env `SQLHOST=db`, `USERNAME=root`, `PASSWORD=password` (`:32-46`). `depends_on: db` has no health condition.
- `Dockerfile`: `python:3.14`, `pip install .`, entrypoint `rfhistoric -s ... -a ...`. The image does not contain pytest or the tests.

#### 8. Migration Scripts
- `scripts/migrate_qe7617.py`: `--host/--port/--user`, password from `MYSQL_PWD` → `PASSWORD` → `getpass`. `--db NAME` (repeatable) or `--all`, plus `--dry-run`. Idempotence comes from `information_schema.STATISTICS` checks for a leading `Execution_Id` index. Output `[OK]/[SKIP]/[WARN]/[ERROR]`, exit 1 on any ERROR.
- `scripts/rollback_qe7617.py`: drops only `idx_suite_execution_id`/`idx_test_execution_id` if present, otherwise `[SKIP]`.
- Both connect to MySQL from wherever they run, so they need DB reachability (same constraint as §7).

#### 9. CI
- `.github/workflows/pr-build.yml`: `pull_request` to `master`, job `build-and-smoke`. It runs `docker compose build rfhistoric`, then `up -d`, then curl smoke (`/` with retries, then dashboard/metrics/tmetrics/compare 200, `edelete/1` 403). Logs are dumped on failure and `down -v` always runs.
- `.github/workflows/build-and-publish.yml`: push to `master` / dispatch / merged PR. It builds and pushes `:latest` and `:<version>` to ProGet.
- The QE-7618 plan (`.context/domains/dependency-management/plans/archive/2026-11-12-dependency-update-process.md`) records `build-and-smoke` as the required status check on `master`.

#### 10. Prior Manual Verification (source for test cases)
- `.github/copilot-instructions.md`: PowerShell checks for unauthenticated 403, public 200, viewer 403 and lead 200.
- QE-7617 plan (`.context/domains/database-performance/plans/archive/2026-11-11-execution-delete-latency-indexes.md`) covers these cases: unauth/viewer `edelete` 403, and lead 302 + audit + children deleted + summary. It also covers empty suite/test data, last execution → `Total_Executions=0`, a repeat writing no duplicate audit row, a DB error giving 500 + rollback, `/newdb` indexes, and read-only pages loading.

---

### Code References
- `robotframework_historic/app.py:13-15` - module-level `app` and `mysql`
- `robotframework_historic/app.py:31-46` - `deldbconf` / `delete` (DROP DATABASE)
- `robotframework_historic/app.py:48-71` - login
- `robotframework_historic/app.py:78-97` - register
- `robotframework_historic/app.py:99-158` - newdb DDL incl. Execution_Id indexes
- `robotframework_historic/app.py:235-314` - deleconf / edelete transaction
- `robotframework_historic/app.py:438-439` - `use_db`
- `robotframework_historic/app.py:465-481` - `main()` config and secret key
- `robotframework_historic/args.py` - CLI args (`-s/-t/-u/-p/-a`)
- `docker/init.sql:25-27` - lead seed user
- `docker/init.sql:43-46` - seeded projects
- `docker-compose.yml:5-18` - `db` service (no host port)
- `.github/workflows/pr-build.yml:11-43` - `build-and-smoke` job
- `scripts/migrate_qe7617.py` - idempotent index migration with `--dry-run`

### Architecture Patterns
- Single Flask module, raw SQL via flask-mysqldb, `USE <db>` switching per request.
- Session-only auth (`name`, `email`, `role`). Guards are inline `!= 'lead'` checks.
- One MySQL database per project, with the registry in `robothistoric.TB_PROJECT` and users in `accounts.TB_USERS`.
- Migrations are standalone `scripts/migrate_<ticket>.py` / `rollback_<ticket>.py` with `--dry-run` and `[OK]/[SKIP]` output.
- CI uses docker compose services in GitHub Actions.

### Constraints Discovered
- No app factory. The fixture must set `MYSQL_*` and `secret_key` on the module-level `app`, and refactoring `app.py` is out of scope.
- No host port on `db`, so pytest on the host or the Actions runner cannot reach MySQL as-is.
- "No venv" means pytest and the app deps (`flask-mysqldb` needs the MySQL client C library) must come from the system interpreter or a container.
- No viewer user is seeded. Viewer coverage needs session injection or a new seed row.
- Delete and newdb tests change the persistent volume. Test order and isolation matter. `down -v` resets state.
- `/newdb` swallows errors and always returns 302.
- `edelete` catches only `MySQLdb.Error`.
- `depends_on` has no health condition. MySQL init time needs retries (as `pr-build.yml` does).
- `/login` with an unknown email raises (`len(None)`).
- Found during implementation: on a project with no executions, `/<db>/tmetrics` (QE-7656) and `/<db>/flaky` (QE-7657) return 500.
- Found during implementation: Flask-MySQLdb closes the connection at request teardown, so uncommitted work is discarded even without the explicit `rollback()` in `edelete`.

### Potential Approaches
- **DB access:** add a `ports` mapping on `db` (e.g. `3306:3306`) or a compose override for tests. Alternatively run pytest in a container on the `rf` network (e.g. a test service or `docker compose run` with the app image plus pytest).
- **Sessions:** `client.session_transaction()` to set `role`/`email` directly. Alternatively POST `/login` as `admin@local` for lead, and seed or register a viewer user.
- **State isolation:** reset the volume per run (`down -v`). Alternatively target deletes at IDs/DBs reserved for tests, or create throwaway DBs via `/newdb` and drop them in teardown.
- **Forced DB error:** monkeypatch the cursor `execute` to raise `MySQLdb.OperationalError` mid-transaction, or drop or rename a table in a throwaway DB.
- **CI:** add a pytest step to the existing `build-and-smoke` job, or add a second job and make it a required check.
- **Migration tests:** run `scripts/migrate_qe7617.py --db <name> --dry-run` and the rerun via `subprocess`, then assert `[SKIP]` and exit 0.

### Open Questions
- Where should pytest run locally without a venv: the host system Python, or inside a container?
- Should pytest and test deps go in `requirements.txt` (which ships in the image) or in a separate file?
- Should the viewer user be seeded in `init.sql` or created per test?
- Should tests be added to the existing required `build-and-smoke` job or to a separate job? A separate job would need branch protection updated.
- What is the "linked dependency-process ticket" (QE-7618) PR workflow scope? `pr-build.yml` already exists from it.
