---
date: 2026-05-12
author: Neil Howell
domain: access-control
jira: QE-7360
parent-research: 2026-05-12-role-based-deletion-permissions.md
scope: "app.py SQL queries, docker/init.sql TB_EXECUTION DDL, templates/ehistoric.html"
status: validated
---

# Research: TB_DELETION_LOG vs TB_EXECUTION Columns — Schema Strategy
## Jira: QE-7360 (Follow-up to role-based-deletion-permissions research)

### Research Question
What codebase facts are relevant to choosing between Option A (nullable columns on TB_EXECUTION) and Option B (separate TB_DELETION_LOG table) for tracking soft-deleted test runs?

### Summary
The codebase contains 14 SELECT queries against TB_EXECUTION across 7 routes, all using either SELECT * or named column subsets with no existing WHERE clause filtering on row attributes — only by Execution_Id. Four of these are full-table-scan aggregates (dashboard statistics). The ehistoric template uses hard-coded positional indexing (item[0]…item[9]), meaning any column insertion into TB_EXECUTION breaks display. No JOINs exist between TB_EXECUTION and other tables. The per-project DDL lives inline in the `/newdb` route handler.

---

### Findings

#### TB_EXECUTION Query Patterns

| Line | Route | Query | Type | WHERE on data? |
|------|-------|-------|------|---------------|
| 136 | `/<db>/dashboard` | `SELECT COUNT(Execution_Id) from TB_EXECUTION` | Aggregate | No |
| 145 | `/<db>/dashboard` | `SELECT Execution_Pass, Execution_Fail, Execution_Total, Execution_Time ... LIMIT 1` | Named cols | No |
| 148 | `/<db>/dashboard` | `SELECT SUM(...), COUNT(...) from (... LIMIT 10) AS T` | Aggregate subquery | No |
| 151 | `/<db>/dashboard` | `SELECT SUM(...), COUNT(Execution_Id) from TB_EXECUTION` | **Full table scan aggregate** | No |
| 154 | `/<db>/dashboard` | `SELECT Execution_Id, Execution_Pass, Execution_Fail, Execution_Time ... LIMIT 10` | Named cols | No |
| 157 | `/<db>/dashboard` | `select execution_pass, ROUND(MIN(...)), ROUND(AVG(...)), ROUND(MAX(...)) ...` | **Full table scan aggregate** | No |
| 160 | `/<db>/dashboard` | `select execution_fail, ROUND(MIN(...)), ROUND(AVG(...)), ROUND(MAX(...)) ...` | **Full table scan aggregate** | No |
| 163 | `/<db>/dashboard` | `select execution_time, ROUND(MIN(...)), ROUND(AVG(...)), ROUND(MAX(...)) ...` | **Full table scan aggregate** | No |
| 185 | `/<db>/ehistoric` | `SELECT * from TB_EXECUTION order by Execution_Id desc LIMIT 500` | SELECT * | No |
| 203 | `/<db>/edelete/<eid>` | `SELECT Execution_Pass, Execution_Total ... ORDER BY Execution_Id DESC LIMIT 1` | Named cols | No |
| 206 | `/<db>/edelete/<eid>` | `SELECT COUNT(*) from TB_EXECUTION` | Aggregate | No |
| 234 | `/<db>/tmetrics` | `SELECT Execution_Id from TB_EXECUTION order by Execution_Id desc LIMIT 1` | Single col | No |
| 255 | `/<db>/metrics/<eid>` | `SELECT * from TB_EXECUTION WHERE Execution_Id=%s` | SELECT * | Yes — by Execution_Id only |
| 305 | `/<db>/flaky` | Subquery selecting Execution_Id with LIMIT 5 window | Single col | No |
| 307 | `/<db>/flaky` | `SELECT COUNT(Execution_Id) from TB_EXECUTION` | Aggregate | No |

**Key observations:**
- 4 full-table-scan aggregate queries (lines 151, 157, 160, 163) — dashboard statistics covering all-time data
- 2 SELECT * queries (lines 185, 255) — both would silently include new columns
- WHERE filtering by row attribute is absent in all queries except by Execution_Id exact match
- **14 query sites would require `WHERE is_deleted = 0` added** if Option A is chosen

#### Per-Project Database Creation

- **Route:** `POST /<db>/newdb` (`app.py` — inline CREATE TABLE statements in handler)
- **Schema method:** Inline DDL in Python route; no stored procedures, migration files, or templates
- **TB_EXECUTION DDL (exact, from newdb handler):**
  ```sql
  CREATE TABLE TB_EXECUTION (
      Execution_Id    INT NOT NULL auto_increment primary key,
      Execution_Date  DATETIME,
      Execution_Desc  TEXT,
      Execution_Total INT,
      Execution_Pass  INT,
      Execution_Fail  INT,
      Execution_Time  FLOAT,
      Execution_STotal INT,
      Execution_SPass  INT,
      Execution_SFail INT,
      Execution_Skip  INT,
      Execution_SSkip INT
  );
  ```
- **12 columns total.** PRIMARY KEY on `Execution_Id` only — no other indexes.
- Both new project databases AND the one-time migration script must be updated for either option.

#### Multi-Table JOIN Patterns

**No JOINs exist** between TB_EXECUTION and any other table. The cascade delete at `app.py:260-261` uses three separate DELETE statements, not a JOIN. Dashboard, ehistoric, tmetrics, and flaky routes all query TB_EXECUTION in isolation.

#### ehistoric Template Column Mapping

Feed query: `SELECT * from TB_EXECUTION order by Execution_Id desc LIMIT 500` (`app.py:185`)

Positional mapping in `templates/ehistoric.html`:

| Index | Column | Displayed? |
|-------|--------|-----------|
| `item[0]` | `Execution_Id` | Yes — "EID" |
| `item[1]` | `Execution_Date` | Yes — "Date" |
| `item[2]` | `Execution_Desc` | Yes — "Description" |
| `item[3]` | `Execution_Total` | Yes — "Test Total" |
| `item[4]` | `Execution_Pass` | Yes — "Test Pass" |
| `item[5]` | `Execution_Fail` | Yes — "Test Fail" |
| `item[6]` | `Execution_Time` | Yes — "Time (m)" |
| `item[7]` | `Execution_STotal` | Yes — "Suite Total" |
| `item[8]` | `Execution_SPass` | Yes — "Suite Pass" |
| `item[9]` | `Execution_SFail` | Yes — "Suite Fail" |
| `item[10]` | `Execution_Skip` | Not displayed |
| `item[11]` | `Execution_SSkip` | Not displayed |

**Template impact:** Inserting columns anywhere in TB_EXECUTION shifts all `item[N]` indices and breaks the ehistoric display. Appending columns at the end (indices 12+) is safe for ehistoric, but the SELECT * at `app.py:255` (metrics route) would also pick them up without display issues.

#### Snapshot Value Analysis

Columns worth capturing in a deletion log for the deleted-runs tab:

| Column | Type | Value if Snapshotted |
|--------|------|---------------------|
| `Execution_Date` | DATETIME | **High** — source timestamp; user-meaningful; non-derivable |
| `Execution_Desc` | TEXT | **High** — user-provided text; only copy |
| `Execution_Total` | INT | Medium — fixed at execution time; useful for summary display |
| `Execution_Pass` | INT | Medium — historical pass rate; useful for deleted-runs tab |
| `Execution_Fail` | INT | Medium — historical fail rate |
| `Execution_Time` | FLOAT | Medium — runtime; useful for historical comparison |
| `Execution_STotal` | INT | Low-Medium — suite counts not displayed in ehistoric by default |
| `Execution_SPass` | INT | Low |
| `Execution_SFail` | INT | Low |
| `Execution_Skip` | INT | Low — not currently displayed anywhere |
| `Execution_SSkip` | INT | Low — not currently displayed anywhere |

---

### Option A Facts (Columns on TB_EXECUTION)

**New columns required:**
```sql
ALTER TABLE TB_EXECUTION
  ADD COLUMN is_deleted TINYINT NOT NULL DEFAULT 0,
  ADD COLUMN deleted_at DATETIME NULL,
  ADD COLUMN deleted_by VARCHAR(255) NULL;
```

**Query change surface:** 14 SELECT query sites require `WHERE is_deleted = 0` added
- 4 are full-table-scan aggregates — require index on `(is_deleted, Execution_Id)` for performance
- 2 use SELECT * — silently include new columns, no template breakage if appended

**Template changes:** None if columns appended at end (items[12], [13], [14]); ehistoric indices item[0]…item[11] unchanged

**Hard-delete route change:** `DELETE FROM TB_EXECUTION WHERE Execution_Id='%s'` must become:
```sql
UPDATE TB_EXECUTION SET is_deleted=1, deleted_at=NOW(), deleted_by=%s WHERE Execution_Id=%s
```

**Cascade impact:** When a run is soft-deleted, TB_SUITE and TB_TEST rows remain; decision required on whether to also soft-delete or hard-delete them

**Count accuracy impact:** Lines 136, 206 (COUNT queries used to update `TB_PROJECT.Total_Executions`) must filter `WHERE is_deleted = 0` to remain accurate

**Migration scope per existing project DB:** 1 × `ALTER TABLE TB_EXECUTION ADD COLUMN ...`

**Full code change surface:** 1 schema change + 14 query edits + 1 delete→update conversion + 2 count query corrections

---

### Option B Facts (Separate TB_DELETION_LOG)

**New table DDL per project database:**
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
    INDEX (execution_id),
    INDEX (deleted_at)
);
```

**Existing query change surface:** 0 — no existing SELECT, aggregate, or dashboard queries touched

**Write pattern at deletion (app.py:259):** INSERT into TB_DELETION_LOG before or after the existing DELETE:
```sql
INSERT INTO TB_DELETION_LOG (execution_id, deleted_by, snapshot_*)
  SELECT Execution_Id, %s, Execution_Date, Execution_Desc, ...
  FROM TB_EXECUTION WHERE Execution_Id=%s;
DELETE FROM TB_EXECUTION WHERE Execution_Id=%s;
```

**Hard delete:** Unchanged semantics — rows still hard-deleted from TB_EXECUTION

**CASCADE impact:** TB_SUITE and TB_TEST still hard-deleted; no orphan rows

**Count accuracy:** `COUNT(*)` and `COUNT(Execution_Id)` queries remain accurate without modification

**Template impact:** None — no changes to ehistoric.html, dashboard.html, or any existing template

**New route required:** `GET /<db>/deleted` — new handler reading from TB_DELETION_LOG

**New template required:** New `deletedhistoric.html` rendering TB_DELETION_LOG rows

**Migration scope per existing project DB:** 1 × `CREATE TABLE TB_DELETION_LOG (...)`

**Full code change surface:** 1 new table DDL + 1 INSERT added to delete handler + 1 new route + 1 new template

---

### Constraints Relevant to This Decision

1. **Positional template indexing is the hardest constraint for Option A.** Columns must be appended at the end of TB_EXECUTION to avoid breaking item[0]…item[11] references. This is achievable but fragile — any future column insertion breaks it again.

2. **Four full-table-scan aggregate queries (lines 151, 157, 160, 163)** must each gain a `WHERE is_deleted = 0` filter and a composite index under Option A, or they silently include deleted data in dashboard statistics.

3. **LIMIT 500 on ehistoric** means under Option A, if 200 rows are soft-deleted within the top 500, the effective visible window shrinks to 300 without increasing the LIMIT.

4. **No existing soft-delete pattern** — Option A introduces new conditional delete semantics that must be consistently applied; Option B keeps hard-delete semantics unchanged.

5. **Per-project DDL inline in route handler** — both options require updating the `/newdb` handler AND a one-time migration script for existing databases.

6. **TB_DELETION_LOG is write-once/append-only** — simpler concurrency model than Option A's UPDATE-then-read pattern.

---

### Decisions (Open Questions Resolved)

1. **Dashboard statistics scope:** Deleted runs are **excluded** from all-time dashboard aggregates. Option B (TB_DELETION_LOG) achieves this automatically — hard-deleted rows disappear from all existing queries with zero changes.

2. **TB_SUITE / TB_TEST fate on deletion:** **Hard-delete both**, same as current behavior. The deleted-runs tab is a list view only (no drill-down), so suite/test detail rows serve no purpose once a run is deleted. Preserving them as orphans or in archive tables adds complexity for data that is never displayed.

3. **Deleted-runs tab display columns:** All columns from the ehistoric page, plus `Deleted By` and `Deleted At` as the leading identifier columns (positioned after EID to distinguish this view from ehistoric). Full column order:
   - EID (`execution_id`)
   - Deleted By (`deleted_by`)
   - Deleted At (`deleted_at`)
   - Date (`snapshot_execution_date`)
   - Description (`snapshot_execution_desc`)
   - Test Total / Pass / Fail (`snapshot_execution_total/pass/fail`)
   - Time (m) (`snapshot_execution_time`)
   - Suite Total / Pass / Fail (`snapshot_execution_stotal/spass/sfail`)
