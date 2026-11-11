"""
rollback_qe7617.py — Rollback for QE-7617

Drops only idx_suite_execution_id / idx_test_execution_id created by migrate_qe7617.py.
Equivalent indexes with other names are left in place.

Usage:
    python scripts/rollback_qe7617.py (--all | --db NAME [--db NAME ...]) [--dry-run]
        [--host HOST] [--port PORT] [--user USER] [--password PASSWORD]
"""

import sys
import time

import MySQLdb

from migrate_qe7617 import (INDEXES, db_exists, get_connection, list_projects,
                            parse_args, quote_ident)


def index_exists(cursor, db, table, name):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s",
        (db, table, name),
    )
    return cursor.fetchone()[0] > 0


def drop_index(cursor, db, table, name, dry_run):
    sql = "ALTER TABLE %s.%s DROP INDEX %s, ALGORITHM=INPLACE, LOCK=NONE" % (
        quote_ident(db), quote_ident(table), quote_ident(name))
    if dry_run:
        print("  [DRY-RUN] drop %s.%s %s" % (db, table, name))
        return
    start = time.monotonic()
    cursor.execute(sql)
    print("  [OK] dropped %s.%s %s (%.1fs)" % (db, table, name, time.monotonic() - start))


def main():
    args = parse_args("QE-7617 Execution_Id index rollback")
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
                for table, name in INDEXES:
                    if index_exists(cursor, db, table, name):
                        drop_index(cursor, db, table, name, args.dry_run)
                        counts["ok"] += 1
                    else:
                        print("  [SKIP] %s.%s %s not present" % (db, table, name))
                        counts["skip"] += 1
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
