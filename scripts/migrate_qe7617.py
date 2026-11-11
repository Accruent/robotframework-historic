"""
migrate_qe7617.py — Idempotent migration for QE-7617 (Execution_Id indexes)

Adds an Execution_Id secondary index to TB_SUITE and TB_TEST in each project DB
registered in robothistoric.TB_PROJECT, unless an index led by Execution_Id exists.

Usage:
    python scripts/migrate_qe7617.py (--all | --db NAME [--db NAME ...]) [--dry-run]
        [--host HOST] [--port PORT] [--user USER] [--password PASSWORD]
"""

import argparse
import sys
import time

import MySQLdb


INDEXES = [("TB_SUITE", "idx_suite_execution_id"), ("TB_TEST", "idx_test_execution_id")]


def parse_args(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host",     default="localhost")
    parser.add_argument("--port",     type=int, default=3306)
    parser.add_argument("--user",     default="root")
    parser.add_argument("--password", default="password")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--db", action="append", metavar="NAME")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def get_connection(args):
    return MySQLdb.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        passwd=args.password,
        charset='utf8',
    )


def quote_ident(name):
    return "`%s`" % name.replace("`", "``")


def list_projects(cursor, selected):
    """Return registered project names, filtered by `selected` when given. Returns (projects, warn_count)."""
    cursor.execute("SELECT Project_Name FROM robothistoric.TB_PROJECT")
    registered = [row[0] for row in cursor.fetchall()]
    if not selected:
        return registered, 0
    warns = 0
    for name in selected:
        if name not in registered:
            print("  [WARN] %s: not registered in robothistoric.TB_PROJECT" % name)
            warns += 1
    return [p for p in registered if p in selected], warns


def db_exists(cursor, db):
    cursor.execute("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (db,))
    return cursor.fetchone()[0] > 0


def has_leading_execution_id_index(cursor, db, table):
    cursor.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "AND COLUMN_NAME = 'Execution_Id' AND SEQ_IN_INDEX = 1 "
        "ORDER BY INDEX_NAME LIMIT 1",
        (db, table),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def print_inventory(cursor, db):
    cursor.execute(
        "SELECT TABLE_NAME, TABLE_ROWS, ROUND((DATA_LENGTH + INDEX_LENGTH) / 1048576, 1) "
        "FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ('TB_SUITE', 'TB_TEST') ORDER BY TABLE_NAME",
        (db,),
    )
    for table, rows, size_mb in cursor.fetchall():
        print("  [INFO] %s.%s rows~%s size=%sMB" % (db, table, rows, size_mb))


def add_index(cursor, db, table, name, dry_run):
    sql = "ALTER TABLE %s.%s ADD INDEX %s (Execution_Id), ALGORITHM=INPLACE, LOCK=NONE" % (
        quote_ident(db), quote_ident(table), quote_ident(name))
    if dry_run:
        print("  [DRY-RUN] %s.%s %s" % (db, table, name))
        return
    start = time.monotonic()
    cursor.execute(sql)
    print("  [OK] %s.%s %s (%.1fs)" % (db, table, name, time.monotonic() - start))


def main():
    args = parse_args("QE-7617 Execution_Id index migration")
    print("Connecting to MySQL at %s:%d as %s ..." % (args.host, args.port, args.user))
    try:
        conn = get_connection(args)
    except MySQLdb.Error as exc:
        print("ERROR: Could not connect to MySQL: %s" % exc)
        sys.exit(1)

    cursor = conn.cursor()
    counts = {"ok": 0, "skip": 0, "warn": 0, "error": 0}
    try:
        projects, counts["warn"] = list_projects(cursor, args.db)
        for db in projects:
            if not db_exists(cursor, db):
                print("  [WARN] %s: database does not exist" % db)
                counts["warn"] += 1
                continue
            try:
                print_inventory(cursor, db)
                for table, name in INDEXES:
                    existing = has_leading_execution_id_index(cursor, db, table)
                    if existing:
                        print("  [SKIP] %s.%s existing index %s" % (db, table, existing))
                        counts["skip"] += 1
                    else:
                        add_index(cursor, db, table, name, args.dry_run)
                        counts["ok"] += 1
            except MySQLdb.Error as exc:
                print("  [ERROR] %s: %s" % (db, exc))
                counts["error"] += 1
    finally:
        cursor.close()
        conn.close()

    print("ok=%(ok)d skip=%(skip)d warn=%(warn)d error=%(error)d" % counts)
    sys.exit(1 if counts["error"] else 0)


if __name__ == "__main__":
    main()
