import os
import subprocess
import sys

from conftest import DB_HOST, DB_PASSWORD, DB_PORT, DB_USER, count

INDEXES = [("TB_SUITE", "idx_suite_execution_id"), ("TB_TEST", "idx_test_execution_id")]


def leading_indexes(db_conn, db, table):
    cur = db_conn.cursor()
    cur.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
        "AND COLUMN_NAME='Execution_Id' AND SEQ_IN_INDEX=1",
        (db, table),
    )
    return [r["INDEX_NAME"] for r in cur.fetchall()]


def drop_indexes(db_conn, db):
    cur = db_conn.cursor()
    for table, name in INDEXES:
        cur.execute(f"ALTER TABLE `{db}`.{table} DROP INDEX {name}")


def migrate(db, *extra):
    return subprocess.run(
        [
            sys.executable,
            "scripts/migrate_qe7617.py",
            "--host",
            DB_HOST,
            "--port",
            str(DB_PORT),
            "--user",
            DB_USER,
            "--db",
            db,
            *extra,
        ],
        env={**os.environ, "MYSQL_PWD": DB_PASSWORD},
        capture_output=True,
        text=True,
    )


def lines_with(out, tag):
    return [line for line in out.splitlines() if tag in line]


def test_newdb_creates_execution_id_indexes(throwaway_db, db_conn):
    for table, name in INDEXES:
        assert leading_indexes(db_conn, throwaway_db, table) == [name]
    assert (
        count(
            db_conn,
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='TB_DELETION_LOG'",
            (throwaway_db,),
        )
        == 1
    )


def test_newdb_registers_project(throwaway_db, db_conn):
    assert (
        count(
            db_conn,
            "SELECT COUNT(*) FROM robothistoric.TB_PROJECT WHERE Project_Name=%s",
            (throwaway_db,),
        )
        == 1
    )


def test_migrate_dry_run_no_change(throwaway_db, db_conn):
    drop_indexes(db_conn, throwaway_db)
    result = migrate(throwaway_db, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    for table, _ in INDEXES:
        assert lines_with(result.stdout, f"[DRY-RUN] {throwaway_db}.{table}")
        assert leading_indexes(db_conn, throwaway_db, table) == []


def test_migrate_then_rerun_idempotent(throwaway_db, db_conn):
    drop_indexes(db_conn, throwaway_db)
    first = migrate(throwaway_db)
    assert first.returncode == 0, first.stdout + first.stderr
    assert len(lines_with(first.stdout, "[OK]")) == 2
    for table, name in INDEXES:
        assert leading_indexes(db_conn, throwaway_db, table) == [name]

    second = migrate(throwaway_db)
    assert second.returncode == 0, second.stdout + second.stderr
    assert len(lines_with(second.stdout, "[SKIP]")) == 2
    assert lines_with(second.stdout, "[OK]") == []
    for table, name in INDEXES:
        assert leading_indexes(db_conn, throwaway_db, table) == [name]


def test_migrate_on_already_indexed_db_skips(throwaway_db):
    result = migrate(throwaway_db)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(lines_with(result.stdout, "[SKIP]")) == 2
