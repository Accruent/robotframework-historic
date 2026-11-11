---
date: 2026-11-11
author: Neil Howell
domain: database-performance
jira: QE-7617
research: .context/domains/database-performance/research/current/2026-11-11-execution-delete-latency-indexes.md
status: draft
phases: 4
---

# QE-7617: Reduce Slow Execution Deletes and Add Missing Execution_Id Indexes — Implementation Plan

## Overview
Add `Execution_Id` secondary indexes to `TB_SUITE` and `TB_TEST` in every project database through an idempotent migration with rollback. Add the same indexes to new-project DDL and the local seed. Harden `delete_eid` (rollback on failure, parameterized deletes, per-statement timing logs, single-click link). Measure before and after on a non-production copy of `Famis360Full`. Then roll out to production one database at a time. Asynchronous deletion (Approach 3) is a fallback only if the target is missed.

---

## Current State Analysis

*(Full details in research artifact. Key facts for implementation:)*

- `add_db()` (`app.py:91-156`) creates `TB_SUITE` and `TB_TEST` with `Execution_Id INT` and no index (`app.py:122-131`). `TB_DELETION_LOG` uses inline `INDEX (...)` (`app.py:145-146`), which is the style precedent.
- `docker/init.sql` seeds three project DBs with the same unindexed tables. The seed runs only on a fresh `db_data` volume.
- `delete_eid()` (`app.py:236-277`) runs the audit INSERT, three DELETEs using `'%s' % eid` interpolation, two `TB_EXECUTION` reads, and a `robothistoric.TB_PROJECT` UPDATE in one transaction. It has no rollback on exception, commits once and redirects to `ehistoric`.
- `deleconf.html:79` uses a plain GET `<a href="../edelete/{{eid}}">`. Nothing prevents a second click.
- Production: Azure Database for MySQL 5.7.44, InnoDB. `Famis360Full` has about 1.04M `TB_SUITE` rows and about 5.34M `TB_TEST` rows (~1.2 GB). `EXPLAIN` shows `type=ALL` for both predicates.
- Migration precedent: `scripts/migrate_qe7360.py` / `rollback_qe7360.py` (argparse connection args, `TB_PROJECT` loop, `[OK]/[SKIP]/[WARN]` output).
- The repo has no automated test suite. Verification is done with PowerShell HTTP checks and SQL.

---

## Desired End State

- Every project DB has an index whose leading column is `Execution_Id` on `TB_SUITE` and `TB_TEST`, named `idx_suite_execution_id` and `idx_test_execution_id` unless an equivalent already exists. No duplicate indexes.
- `scripts/migrate_qe7617.py` is safe to rerun, supports `--db NAME` / `--all` / `--dry-run`, and reports per-DB `[OK]/[SKIP]/[WARN]/[ERROR]`. `scripts/rollback_qe7617.py` drops only the indexes the migration created.
- `/newdb` and `docker/init.sql` create both indexes.
- `delete_eid` rolls back on any DB error and returns a 500 without committing a partial audit or delete. It uses parameterized DELETEs, logs per-statement and total timings, and still enforces lead-only access.
- On a non-production copy of `Famis360Full`, at least 3 deletions show a **median end-to-end `edelete` time of ≤ 5 s, with no run over 10 s**, and indexed `EXPLAIN` plans (`type=ref`, `key=idx_*`).
- Production is migrated `Famis360Full` first, then the remaining DBs, with monitoring.

---

## What We're NOT Doing

- No asynchronous or background delete job, unless Phase 3 misses the target (see Fallback).
- No indexes beyond `Execution_Id` on `TB_SUITE` and `TB_TEST`. The `search` `LIKE '%...%'` query and the dashboard `COUNT`s are unchanged.
- No changes to the ingestion tool (outside this repo).
- No conversion of the `edelete` GET into a POST and no CSRF work. Keep the scope tight.
- No foreign keys or `NOT NULL` changes on `Execution_Id`.
- No changes to other routes' `%`-interpolated SQL.

---

## Implementation Approach

Phase 1 (migration) and Phase 2 (app changes) are independent and can be reviewed separately. Phase 3 measures both on a non-production copy and gates Phase 4 (production rollout). Run all commands with the system Python or inside the Docker containers. Do not use virtual environments.

---

## Phase 1: Index Migration and Rollback Scripts

### Changes Required

#### 1. `scripts/migrate_qe7617.py` (new)
Follow the `migrate_qe7360.py` structure.
- `parse_args()`: `--host/--port/--user/--password` (same defaults), plus a mutually exclusive required group `--db NAME` (repeatable) / `--all`, and `--dry-run`.
- `INDEXES = [("TB_SUITE", "idx_suite_execution_id"), ("TB_TEST", "idx_test_execution_id")]`.
- `list_projects(cursor, selected)`: `SELECT Project_Name FROM robothistoric.TB_PROJECT`, filtered by `--db`. Print `[WARN]` for requested names not in the registry.
- `db_exists(cursor, db)`: checks `information_schema.SCHEMATA`. If the DB is missing, print `[WARN]` and continue. This closes the QE-7360 loop gap.
- `has_leading_execution_id_index(cursor, db, table)`: reads `information_schema.STATISTICS` with `TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME='Execution_Id' AND SEQ_IN_INDEX=1` (parameterized) and returns the index name or `None`.
- `add_index(cursor, db, table, name)`: runs ``ALTER TABLE `db`.`table` ADD INDEX `name` (Execution_Id), ALGORITHM=INPLACE, LOCK=NONE``, timed with `time.monotonic()`. Print `[OK] db.table name (N.Ns)`. In dry-run mode, print `[DRY-RUN]` instead.
- `main()`: for each DB and table, print `[SKIP] ... existing index <name>` if an equivalent exists, otherwise add the index. Catch `MySQLdb.Error` per DB, print `[ERROR] db: msg`, and continue. Exit 1 if any DB errored. Finish with a summary line `ok=X skip=Y warn=Z error=W`.
- Before each DB, print the row estimate and size from `information_schema.TABLES` (inventory, ticket scope item 1).
- Validate `--db` names against the registry before any backtick interpolation.

#### 2. `scripts/rollback_qe7617.py` (new)
Mirror the migration's args, loop and `--dry-run`. Drop **only** `idx_suite_execution_id` / `idx_test_execution_id` when they are present (STATISTICS check): ``ALTER TABLE ... DROP INDEX `name`, ALGORITHM=INPLACE, LOCK=NONE``. Print `[SKIP]` for pre-existing equivalent indexes with other names.

### Success Criteria

#### Automated Verification
Copy the scripts into the running container and run them there (the DB port is not published):
- [x] `docker compose up -d` → all services running
- [x] `docker compose cp scripts/migrate_qe7617.py rfhistoric:/tmp/ ; docker compose cp scripts/rollback_qe7617.py rfhistoric:/tmp/`
- [x] `docker compose exec rfhistoric python /tmp/migrate_qe7617.py --host db --all --dry-run` → `[DRY-RUN]` lines for 3 DBs × 2 tables, no schema change
- [x] `docker compose exec rfhistoric python /tmp/migrate_qe7617.py --host db --all` → 6 `[OK]` lines, exit 0
- [x] Rerun the same command → 6 `[SKIP]` lines, exit 0 (idempotent)
- [x] `docker compose exec db mysql -uroot -ppassword -e "SELECT TABLE_SCHEMA,TABLE_NAME,INDEX_NAME FROM information_schema.STATISTICS WHERE COLUMN_NAME='Execution_Id' AND TABLE_NAME IN ('TB_SUITE','TB_TEST');"` → exactly one row per DB/table
- [x] `docker compose exec rfhistoric python /tmp/migrate_qe7617.py --host db --db does_not_exist` → `[WARN]`, exit 0
- [x] Insert a `TB_PROJECT` row for a missing DB, then run `--all` → `[WARN]` for that DB, others `[SKIP]`. Remove the row afterwards.
- [x] `docker compose exec rfhistoric python /tmp/rollback_qe7617.py --host db --all` → 6 `[OK]` drops; rerun → 6 `[SKIP]`
- [x] Manually create `CREATE INDEX ix_existing ON rf_full_data.TB_TEST (Execution_Id)`, then run the migration → `[SKIP] ... existing index ix_existing`; rollback leaves `ix_existing` in place

---

## Phase 2: New-Project Schema and `delete_eid` Hardening

### Changes Required

#### 1. `add_db()` — `robotframework_historic/app.py:122-131`
Append `, INDEX idx_suite_execution_id (Execution_Id)` to the `TB_SUITE` DDL and `, INDEX idx_test_execution_id (Execution_Id)` to the `TB_TEST` DDL, before the closing `);`.

#### 2. `docker/init.sql`
Add the same named indexes to `TB_SUITE` and `TB_TEST` in all three project DBs (`rf_full_data`, `roomba_sync_data`, `empty_project`).

#### 3. `delete_eid()` — `robotframework_historic/app.py:236-277`
- Keep the lead guard as the first statement, unchanged.
- Wrap everything from `use_db` through `commit()` in `try:` / `except MySQLdb.Error:` (catch `Exception` if `MySQLdb` is not imported in `app.py`). On error: `mysql.connection.rollback()`, `app.logger.exception(...)`, `return 'Delete failed; no changes were saved', 500`.
- Parameterize the three DELETEs: `cursor.execute("DELETE FROM TB_SUITE WHERE Execution_Id=%s", (eid,))`, and the same for `TB_EXECUTION` and `TB_TEST`.
- Parameterize the `TB_PROJECT` UPDATE values and `Project_Name`.
- Time each statement and commit with `time.monotonic()`. Log one line: `app.logger.info("edelete db=%s eid=%s rows exec=%d suite=%d test=%d t_audit=%.3f t_exec=%.3f t_suite=%.3f t_test=%.3f t_summary=%.3f t_commit=%.3f total=%.3f", ...)`, with row counts taken from `cursor.rowcount`. This gives the ticket its statement and commit timings.
- Repeat or already-deleted requests: if the audit `INSERT` affects 0 rows (execution absent), roll back and redirect to `ehistoric` without writing a log row or touching the summary.

#### 4. `robotframework_historic/templates/deleconf.html:79`
Add `onclick="this.classList.add('disabled');this.style.pointerEvents='none';this.innerText='Deleting…';"` to the Delete link. This stops repeated clicks and shows that the delete is pending. The link stays a GET navigation.

### Success Criteria

#### Automated Verification
- [x] `python -m py_compile robotframework_historic/app.py` → no output, exit 0
- [x] `docker compose build rfhistoric ; docker compose up -d rfhistoric` → container healthy
- [x] Fresh volume: `docker compose down -v ; docker compose up -d` → the STATISTICS query from Phase 1 shows both indexes in all 3 seed DBs
- [x] Unauthenticated: `try { Invoke-WebRequest http://localhost:5001/rf_full_data/edelete/1 } catch { $_.Exception.Response.StatusCode.value__ }` → `403`
- [x] Viewer session (per `.github/copilot-instructions.md` snippet) → `403`
- [x] Lead session: `Invoke-WebRequest http://localhost:5001/rf_full_data/edelete/<eid> -WebSession $session -MaximumRedirection 0 -SkipHttpErrorCheck` → `302` to `/rf_full_data/ehistoric`
- [x] `docker compose logs rfhistoric | Select-String edelete` → one timing line with row counts

#### Manual Verification
Use the seed data. Record before/after SQL counts for each case:
- [x] Lead deletes an execution with suites/tests: one `TB_DELETION_LOG` row with snapshot and `deleted_by`; 0 rows left in all three tables for that eid; other executions untouched; `TB_PROJECT.Total_Executions` / `Recent_Pass_Perc` match the new latest execution
- [x] Delete an execution with no suite/test rows (`roomba_sync_data`) → succeeds, counts correct
- [x] Delete the last remaining execution (`empty_project` after seeding one) → `Total_Executions=0`, `Recent_Pass_Perc=0`, history page loads empty
- [x] Repeat the same `edelete` URL → 302, no second log row, summary unchanged
- [x] Failure path: `docker compose exec db mysql -uroot -ppassword -e "RENAME TABLE rf_full_data.TB_TEST TO rf_full_data.TB_TEST_x;"`, then delete → 500 "Delete failed"; no new log row; `TB_EXECUTION` row still present; rename back afterwards
- [x] Click Delete on the confirmation page → button shows "Deleting…" and cannot be clicked again; lands on refreshed history without the deleted row
- [x] New project via `/newdb` as Lead → `SHOW INDEX FROM <db>.TB_TEST` lists `idx_test_execution_id`
- [x] Dashboard, ehistoric, metrics, tmetrics, failures, flaky and compare still load

**Pause for human confirmation before Phase 3.**

---

## Phase 3: Representative Non-Production Measurement

### Steps
1. Restore a `Famis360Full` dump or backup into the local Docker MySQL 5.7 as `Famis360Full`, and insert a matching `robothistoric.TB_PROJECT` row. Record the source timestamp, row estimates and host specs.
2. **Baseline** (no indexes; run the Phase 1 rollback if needed). Run `EXPLAIN SELECT Test_Id FROM Famis360Full.TB_TEST WHERE Execution_Id=<eid>` and the same for `TB_SUITE` → expect `type=ALL`. Delete 3 or more real executions as Lead via `Measure-Command { Invoke-WebRequest http://localhost:5001/Famis360Full/edelete/<eid> -WebSession $session -MaximumRedirection 0 -SkipHttpErrorCheck }`. Record end-to-end time, the app timing log line and the child-row counts.
3. Run `python /tmp/migrate_qe7617.py --host db --db Famis360Full` and record the index build time per table.
4. **After**: EXPLAIN → expect `type=ref`, `key=idx_suite_execution_id` / `idx_test_execution_id`. Delete 3 or more different executions with similar child-row counts and record the same measurements.
5. Record the results table (run, eid, suite rows, test rows, per-statement and total times, load context) in a new section of this plan and as a ticket comment.

### Success Criteria
- [x] Indexed plans confirmed for both predicates
- [x] Median end-to-end ≤ 5 s, and no run > 10 s
- [x] If missed: n/a — target met; Fallback not needed.

### Results (2026-11-11)
Source: `mysqldump --single-transaction` of production `Famis360Full` taken 2026-11-11 14:51 CST, streamed into local Docker MySQL 5.7 (2m45s). Rows: 1,013 executions, 1,285,025 suites, 6,938,546 tests (`TB_TEST` 1.3 GB). Production has `lower_case_table_names=1`, so the restored tables arrived lowercase and were renamed to `TB_*` locally. Host: local Docker on WSL, idle, no concurrent ingestion.

Index build (`migrate_qe7617.py --db Famis360Full`): `TB_SUITE` 5.7 s, `TB_TEST` 24.1 s.

| Run | eid | suites | tests | t_suite | t_test | t_commit | app total | end-to-end |
|---|---|---|---|---|---|---|---|---|
| baseline | 427 | 1690 | 6924 | 1.130 | 6.743 | 0.023 | 7.899 | 7.94 s |
| baseline | 429 | 1690 | 6924 | 2.395 | 7.253 | 0.017 | 9.666 | 9.68 s |
| baseline | 430 | 1690 | 6924 | 0.933 | 6.133 | 0.017 | 7.086 | 7.10 s |
| indexed | 432 | 1690 | 6924 | 0.022 | 0.042 | 0.011 | 0.077 | 0.11 s |
| indexed | 434 | 1690 | 6924 | 0.009 | 0.037 | 0.008 | 0.055 | 0.07 s |
| indexed | 324 | 1690 | 6924 | 0.012 | 0.048 | 0.010 | 0.072 | 0.08 s |

Baseline median 7.94 s (`type=ALL`) → indexed median 0.08 s (`type=ref`, `key=idx_*`). Local baseline is faster than production because the local host is idle and the data is freshly loaded, so production gains are expected to be larger in absolute terms.

### Fallback (Approach 3 — only if target missed)
Write a separate addendum plan that moves child-row deletion to a background worker or batched deletes. Phases 1–2 stay valid.

---

## Phase 4: Production Rollout

### Pre-flight (external)
- [x] Verify the ingress/proxy timeout for `legion-historic` (ingress annotations, Azure front door, if any) and record the value. It must exceed 10 s.
  - `rfhistoric-ingress` has no timeout annotations. The `ingress-nginx/ingress-nginx-controller` ConfigMap sets `proxy-read-timeout=600` and `proxy-send-timeout=600`.
- [x] Confirm Azure MySQL storage headroom of at least 2× the size of `TB_TEST` for `Famis360Full`. Confirm automated backups are current and point-in-time restore is available.
  - `qa-rfhistoric-mysql` (Flexible Server 5.7): 64 GB with autogrow enabled. 11.0 GB used (16%). Backup retention is 12 days; the earliest restore point is 2026-10-30.
- [ ] Agree a low-ingestion window with the ingestion owners.
  - Proposed window, from 30 days of `Execution_Date` data (UTC): Saturday or Sunday, 20:00–22:00 or 16:00–17:00. Busiest hours are 22:00 and 09:00–11:00.
- [ ] Run `--all --dry-run` against production (read-only) → inventory output saved to the ticket.
  - Ran 2026-11-11: 79 DBs and 158 indexes to add, `ok=158 skip=0 warn=0 error=0`. About 7.4 GB of data in total; the largest table is 1.16 GB. Not yet posted to the ticket.

### Steps
1. Merge the PR into `master`. Jenkins builds and pushes the `rfhistoric` image (`latest` and `{BUILD_NUMBER}`), and the deployment pulls it.
2. `kubectl --context Legion-a6d6a7a -n legion-historic cp scripts/migrate_qe7617.py <pod>:/tmp/`, then run it in the pod with the pod's env credentials: `--db Famis360Full`. Monitor the Azure metrics (CPU, IO, storage) and `SHOW PROCESSLIST` for metadata-lock waits.
3. Smoke test: history, metrics and compare pages load; one new ingestion completes; delete one disposable execution and check the timing log line.
4. Run the remaining DBs with `--db` in small batches, or `--all` once confidence is established. Watch for `[ERROR]` lines.
5. Abort plan: `KILL` the ALTER's connection, which leaves the table unchanged, or run `rollback_qe7617.py --db <name>`.

### Success Criteria
- [ ] Migration output shows `[OK]`/`[SKIP]` for every DB and no `[ERROR]`; rerun shows all `[SKIP]`
- [ ] Production `EXPLAIN` on `Famis360Full` uses the new indexes
- [ ] No sustained lock waits or application errors during or after the rollout; ingestion is normal

---

## Testing Strategy
There is no unit test framework in the repo, and this plan does not add one. Coverage comes from scripted SQL checks and PowerShell HTTP checks (lead/viewer/unauthenticated), plus the manual matrix in Phase 2 and the measurements in Phase 3.

| Case | Expected |
|---|---|
| Unauthenticated / Viewer `edelete` | 403, no DB change |
| Lead delete, normal | 302; audit row; children removed; summary updated |
| Empty suite/test data | 302; counts correct |
| Last execution | summary 0 / 0 |
| Repeat request | 302; no new audit row |
| DB error mid-transaction | 500; full rollback |

---

## Risks
- **Index build load on about 5.3M rows**: online DDL still takes brief metadata locks at the start and end, which can stall behind long ingestion transactions. Mitigate with an off-peak window, one DB first, and monitoring.
- **Disk**: the in-place build needs temporary sort space. Check headroom in pre-flight.
- **Ingestion write cost**: there is a small per-insert overhead and no code change on the ingestion side. Check ingestion runtime after rollout.
- **Schema drift**: equivalent indexes under other names. The STATISTICS check reuses them.
- **Dev volumes**: existing `db_data` volumes do not pick up `init.sql` changes. Run the migration locally instead.
- **Behaviour change**: a DB error now returns 500 instead of surfacing a raw Flask error. Repeat deletes no longer write a duplicate audit row.

## External Dependencies
- A `Famis360Full` dump or backup for Phase 3 (Azure backup or `mysqldump` access). This is a blocker for Phase 3.
- Ingress/proxy timeout values for `legion-historic`.
- Azure MySQL storage headroom and backup confirmation.
- Ingestion tool owners for the rollout window.

---

## References
- Research: `.context/domains/database-performance/research/current/2026-11-11-execution-delete-latency-indexes.md`
- Delete handler: `robotframework_historic/app.py:236-277`
- New-project DDL: `robotframework_historic/app.py:122-146`
- Migration precedent: `scripts/migrate_qe7360.py`, `scripts/rollback_qe7360.py`
- Confirmation template: `robotframework_historic/templates/deleconf.html:79`
