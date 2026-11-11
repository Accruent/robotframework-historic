---
date: 2026-11-11
author: Neil Howell
domain: database-performance
jira: QE-7617
scope: "robotframework_historic/app.py, robotframework_historic/templates/deleconf.html, docker/init.sql, scripts/migrate_qe7360.py, scripts/rollback_qe7360.py, docker-compose.yml, Dockerfile"
status: draft
---

# Research: Execution Delete Latency and Missing Execution_Id Indexes
## Jira: QE-7617 — RF Historic | Reduce slow execution deletes and add missing Execution_Id indexes

### Research Question
What do we need to know to close QE-7617? Specifically: where project schemas are created, how execution deletion works, which queries filter on `Execution_Id`, what migration conventions exist, and what constraints apply to adding `Execution_Id` indexes to `TB_SUITE` and `TB_TEST`.

### Summary
Project databases have no secondary index on `Execution_Id` in `TB_SUITE` or `TB_TEST` in any schema-creation path in this repo: the `/newdb` route (`app.py:115-131`), the local seed (`docker/init.sql`), or the QE-7360 migration. Only `TB_DELETION_LOG` declares indexes (`execution_id`, `deleted_at`). The delete handler `delete_eid` (`app.py:236-277`) runs an audit `INSERT ... SELECT`, three `DELETE ... WHERE Execution_Id=...` statements, two `TB_EXECUTION` reads, and a `robothistoric.TB_PROJECT` update in a single transaction, committed once, followed by a 302 to `ehistoric`. The confirmation page triggers it via a plain `<a href>` GET link. A precedent exists for idempotent, per-project migrations (`scripts/migrate_qe7360.py` and `scripts/rollback_qe7360.py`). It iterates `robothistoric.TB_PROJECT` and runs DDL in each project DB. Local dev uses MySQL 5.7. The production engine/version is not recorded in this repo. Suite/test rows are not written by this repo. Ingestion happens elsewhere.

---

### Detailed Findings

#### 1. Ticket Context (from Jira)
- Observed on `Famis360Full`, Execution_Id 1135, 2026-11-11. About 85 s elapsed between the `TB_DELETION_LOG.deleted_at` timestamp (18:31:28) and the `edelete` 302 (18:32:53). The delete was confirmed persisted.
- Production row estimates: `TB_SUITE` ~1.04M, `TB_TEST` ~5.34M (~1.2 GB data). Only PRIMARY keys exist. `EXPLAIN` on both `WHERE Execution_Id=1135` predicates showed `type=ALL`.
- Scope: inventory indexes per DB, add idempotent migration with rollback, update new-project creation, measure before/after timing (≥3 runs, agreed numeric target), verify ingress timeout and post-delete UX, and keep lead-only enforcement.

#### 2. Project Schema Creation — `/newdb`
- `app.py:91-156` `add_db()` is lead-gated (`app.py:93-94`). It creates the database, inserts the `robothistoric.TB_PROJECT` row, then creates tables:
  - `TB_EXECUTION` (`app.py:117-121`): PK `Execution_Id` only.
  - `TB_SUITE` (`app.py:122-125`): PK `Suite_Id`. `Execution_Id INT` (nullable), no index.
  - `TB_TEST` (`app.py:126-131`): PK `Test_Id`. `Execution_Id INT` (nullable), no index.
  - `TB_DELETION_LOG` (`app.py:132-146`): `INDEX (execution_id)`, `INDEX (deleted_at)`. This is the only inline index pattern in the codebase.
- Errors are swallowed (`except Exception: print`) and the handler always redirects to index (`app.py:148-152`).

#### 3. Local Seed Schema — `docker/init.sql`
- Three project DBs: `rf_full_data`, `roomba_sync_data`, `empty_project`. Each has identical `TB_EXECUTION`/`TB_SUITE`/`TB_TEST` definitions without `Execution_Id` indexes (e.g. `init.sql:70-96`, `167-193`, `240-266`).
- `TB_DELETION_LOG` in each has the two indexes (`init.sql:128-144`, `201-217`, `268-284`).
- Seed data is tiny (3 executions, 6 suites, 12 tests in `rf_full_data`). It does not reproduce large-table behaviour.
- The seed runs only on first container init (`docker-entrypoint-initdb.d`, `docker-compose.yml:9`). Existing `db_data` volumes keep the old schema.

#### 4. Execution Delete Flow
- `deleconf.html:79`: `<a href="../edelete/{{eid}}" ...>Delete</a>`. This is a plain GET navigation with no AJAX or pending-state handling.
- `app.py:230-234` `delete_eid_conf`: lead-gated, renders confirmation.
- `app.py:236-277` `delete_eid`:
  1. Lead guard → `'Forbidden', 403` (`app.py:238-239`).
  2. `use_db(cursor, db)`.
  3. Audit `INSERT INTO TB_DELETION_LOG ... SELECT ... FROM TB_EXECUTION WHERE Execution_Id=%s`, parameterized, with `session.get('email')` as actor (`app.py:242-253`).
  4. `DELETE FROM TB_EXECUTION WHERE Execution_Id='%s'` (`app.py:255`) uses the PK.
  5. `DELETE FROM TB_SUITE WHERE Execution_Id='%s'` (`app.py:256`). There is no index, so this is a full scan.
  6. `DELETE FROM TB_TEST WHERE Execution_Id='%s'` (`app.py:257`). There is no index, so this is a full scan.
  7. Latest execution + `COUNT(*)` from `TB_EXECUTION` (`app.py:259-263`).
  8. `recent_pass_perf` calculation with bare `except` fallback to 0 (`app.py:265-271`).
  9. `UPDATE robothistoric.TB_PROJECT SET Total_Executions, Last_Updated=now(), Recent_Pass_Perc` (`app.py:274`).
  10. Single `mysql.connection.commit()` (`app.py:276`), then `redirect(url_for('ehistoric', db=db))` (`app.py:277`).
- DELETE statements interpolate `eid` with `%` string formatting inside quotes. The `Execution_Id` comparison is INT column vs quoted literal.
- The route has no explicit error handling or rollback around the statements. An exception propagates to Flask.
- `TB_DELETION_LOG.deleted_at` defaults to `CURRENT_TIMESTAMP` at INSERT time (statement time within the open transaction). This explains why the audit timestamp precedes completion.

#### 5. Other Queries Filtering TB_SUITE/TB_TEST by Execution_Id
These read paths also have no index on the predicate column:
- `app.py:293` `tmetrics`: `TB_TEST WHERE Execution_Id=%s`.
- `app.py:302`, `app.py:305` `metrics`: `TB_TEST` / `TB_SUITE WHERE Execution_Id=%s`.
- `app.py:326` (`eidtmetrics`), `app.py:341` (`failures`, plus `Test_Status='FAIL'`).
- `app.py:351` search: `Execution_Id LIKE '%...%'`, which cannot use a B-tree index.
- `app.py:365` flaky: `TB_TEST WHERE Execution_Id >= %s ORDER BY Execution_Id DESC`.
- `app.py:388`, `app.py:391` compare: `TB_TEST WHERE Execution_Id=%s`.
- `app.py:163-165` dashboard: `COUNT(Suite_Id)` / `COUNT(Test_Id)` full-table counts.

#### 6. Migration Conventions
- `scripts/migrate_qe7360.py`:
  - argparse `--host/--port/--user/--password` with docker-compose defaults (`:43-49`).
  - `MySQLdb.connect` (`:51-58`).
  - Idempotency via `information_schema.COLUMNS` check (`:61-75`) and `CREATE TABLE IF NOT EXISTS`.
  - Per-project loop over `SELECT Project_Name FROM robothistoric.TB_PROJECT`, `USE \`%s\``, printing `[OK]`/`[SKIP]`/`[WARN]` (`:90-102`).
  - Commit after each step. On `MySQLdb.Error` it rolls back and exits 1 (`:120-140`).
- `scripts/rollback_qe7360.py`: mirror script with the same connection/loop pattern (`:34`, `:58-69`).
- The repo has no migration framework. Scripts are run manually (per `.github/copilot-instructions.md`).
- `TB_PROJECT` may list projects whose database does not exist (e.g. `/newdb` failure after INSERT). The QE-7360 loop does not guard `USE` failures per project.

#### 7. Runtime / Environment
- `Dockerfile:1` `python:3.9`. `Dockerfile:18` starts via `rfhistoric` CLI with SQL host/port/user/password args.
- `app.py:430-444` maps args to `MYSQL_*` config and runs the Flask dev server via `app.run(host=...)`. The repo has no WSGI server or request timeout config.
- `requirements.txt:5` `flask-mysqldb~=2.0.0`.
- `docker-compose.yml:6` `mysql:5.7`. Online DDL `ALTER TABLE ... ADD INDEX, ALGORITHM=INPLACE, LOCK=NONE` is supported for secondary indexes on InnoDB in 5.6+.
- Production is K8s namespace `legion-historic` (from ticket). There are no manifests or ingress config in this repo.
- Production DB (verified 2026-11-11 via read-only `SELECT VERSION()` from the rfhistoric pod): `5.7.44-azure-log`, MySQL Community Server (GPL), InnoDB 5.7.44, default engine InnoDB. The `-azure` suffix indicates Azure Database for MySQL (external managed service; no MySQL pod exists in `legion-historic`). This matches local dev `mysql:5.7`.

---

### Code References
- `robotframework_historic/app.py:91-156` - `/newdb` project DB + table creation (no Execution_Id indexes)
- `robotframework_historic/app.py:132-146` - `TB_DELETION_LOG` inline `INDEX` precedent
- `robotframework_historic/app.py:230-234` - `delete_eid_conf` (lead-gated)
- `robotframework_historic/app.py:236-277` - `delete_eid` transaction: audit, 3 deletes, summary update, commit, redirect
- `robotframework_historic/app.py:256-257` - TB_SUITE / TB_TEST deletes by Execution_Id
- `robotframework_historic/app.py:207-213` - `ehistoric` redirect target (`LIMIT 500`)
- `robotframework_historic/app.py:293-391` - read paths filtering TB_TEST/TB_SUITE by Execution_Id
- `robotframework_historic/app.py:400` - `use_db` helper
- `robotframework_historic/app.py:430-444` - MySQL config + Flask dev server
- `robotframework_historic/templates/deleconf.html:79` - GET link to `edelete`
- `docker/init.sql:70-96` - seed TB_SUITE/TB_TEST definitions (no indexes)
- `docker/init.sql:128-144` - seed TB_DELETION_LOG with indexes
- `scripts/migrate_qe7360.py:90-102` - per-project migration loop pattern
- `scripts/rollback_qe7360.py:58-69` - per-project rollback loop pattern
- `docker-compose.yml:6-9` - MySQL 5.7, init.sql mount
- `Dockerfile:1`, `Dockerfile:18` - Python 3.9 image, CLI entrypoint

### Architecture Patterns
- Each RF Historic project is its own MySQL database. `robothistoric.TB_PROJECT` is the registry, and `accounts.TB_USERS` holds users.
- Schema is defined in three places that must be kept in sync by hand: `/newdb` inline DDL, `docker/init.sql`, and ticket-specific migration scripts.
- Migrations are named `migrate_<ticket>.py` / `rollback_<ticket>.py`. They are idempotent and print status per DB.
- Route authorization uses `if session.get('role') != 'lead': return 'Forbidden', 403`.
- Mutations use one cursor and one explicit `commit()` per request. Redirects follow POST/GET mutations.
- SQL is mostly `%`-interpolated. Parameterization is used in the audit INSERT and login/register.

### Constraints Discovered
- No `Execution_Id` index exists on TB_SUITE/TB_TEST in any schema path in this repo. Production DBs may have drifted, so the ticket requires inventory first.
- `Execution_Id` is nullable `INT` on TB_SUITE/TB_TEST, and there is no foreign key to TB_EXECUTION.
- Production engine/version, disk headroom, and ingress/proxy timeouts are not discoverable from this repo.
- Index DDL on ~5.3M-row `TB_TEST` (TEXT-heavy, ~1.2 GB) requires a table rebuild/sort and metadata locks, and affects concurrent ingestion.
- The `delete_eid` statements run inside one transaction. Locks on TB_SUITE/TB_TEST rows scanned by unindexed deletes are held until commit.
- Local seed data is too small to show the latency. A representative dataset is needed for AC 2 timing.
- Changing `init.sql` affects only fresh `db_data` volumes.
- Ingestion writers (suite/test inserts) live outside this repo (separate parser tool) and will incur index maintenance cost.
- No automated test suite exists in the repo. Verification so far is manual or PowerShell HTTP checks.

### Potential Approaches
- **Migration script** `scripts/migrate_qe7617.py` + `scripts/rollback_qe7617.py`, following the QE-7360 loop. Check `information_schema.STATISTICS` for an index with `Execution_Id` at `SEQ_IN_INDEX=1` on each table. Then `ALTER TABLE ... ADD INDEX ..., ALGORITHM=INPLACE, LOCK=NONE` and report per DB. Optionally add a `--db` filter for one-at-a-time rollout. The rollback drops only the named indexes.
- **New-project DDL**: add `INDEX (Execution_Id)` inside the `TB_SUITE`/`TB_TEST` `CREATE TABLE` strings in `app.py:122-131`, mirroring the TB_DELETION_LOG style. Mirror the change in `docker/init.sql`.
- **Measurement**: wrap `delete_eid` statements with timing logs, or measure externally with `EXPLAIN`, `SHOW PROFILE`/`performance_schema`, and request timing against a large non-prod copy.
- **Completion UX**: existing redirect to `ehistoric` is unchanged, or limited feedback (flash message, disabled button) only if evidence warrants. Asynchronous deletion is listed as out-of-default scope in the ticket.

### Open Questions
- Production is MySQL 5.7.44 (Azure managed). Is there enough storage headroom for the index build, and which Azure tier, maintenance and backup settings apply?
- How many project databases exist, and how large are they? Do any already have equivalent indexes (drift)?
- What are the ingress/proxy/browser timeout values in front of the Flask dev server?
- Which component ingests suite/test rows, and what is the write volume during a planned index build window?
- What numeric latency target will be agreed for AC 2?
- Is a representative non-prod copy of a large project DB (e.g. `Famis360Full`) available for before/after measurement?
- Should the migration also cover read-path performance (`metrics`, `compare`, `flaky`), or only the delete predicates? The same indexes serve both.
