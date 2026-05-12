"""
rollback_qe7360.py — Idempotent rollback for QE-7360 (Role-Based Deletion Permissions)

Reverses the changes made by migrate_qe7360.py:
  1. accounts.TB_USERS: drop `role` column if present
  2. Every project DB in robothistoric.TB_PROJECT: DROP TABLE IF EXISTS TB_DELETION_LOG

WARNING: Dropping TB_DELETION_LOG permanently destroys any audit log data.
         Only run this before the new application code has been deployed, or if you
         intend to fully revert the QE-7360 feature.

Usage:
    python scripts/rollback_qe7360.py [--host HOST] [--port PORT] [--user USER] [--password PASSWORD]

Defaults match the docker-compose dev environment (root / password / localhost:3306).
"""

import argparse
import sys

import MySQLdb


def parse_args():
    parser = argparse.ArgumentParser(description="QE-7360 schema rollback")
    parser.add_argument("--host",     default="localhost")
    parser.add_argument("--port",     type=int, default=3306)
    parser.add_argument("--user",     default="root")
    parser.add_argument("--password", default="password")
    return parser.parse_args()


def get_connection(args):
    return MySQLdb.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        passwd=args.password,
        charset='utf8',
    )


def drop_role_column(cursor):
    """Drop role column from accounts.TB_USERS if it exists."""
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = 'accounts' AND TABLE_NAME = 'TB_USERS' AND COLUMN_NAME = 'role'"
    )
    (count,) = cursor.fetchone()
    if count:
        cursor.execute("ALTER TABLE accounts.TB_USERS DROP COLUMN role")
        print("  [OK] Dropped role column from accounts.TB_USERS")
    else:
        print("  [SKIP] role column does not exist on accounts.TB_USERS")


def drop_deletion_log_tables(cursor):
    """Drop TB_DELETION_LOG from every project database listed in robothistoric.TB_PROJECT."""
    cursor.execute("SELECT Project_Name FROM robothistoric.TB_PROJECT")
    projects = [row[0] for row in cursor.fetchall()]

    if not projects:
        print("  [WARN] No projects found in robothistoric.TB_PROJECT — nothing to roll back")
        return

    for project in projects:
        cursor.execute("USE `%s`" % project)
        cursor.execute("DROP TABLE IF EXISTS TB_DELETION_LOG")
        print("  [OK] Dropped TB_DELETION_LOG from project db: %s" % project)


def main():
    args = parse_args()
    print("Connecting to MySQL at %s:%d as %s ..." % (args.host, args.port, args.user))

    try:
        conn = get_connection(args)
    except MySQLdb.Error as exc:
        print("ERROR: Could not connect to MySQL: %s" % exc)
        sys.exit(1)

    cursor = conn.cursor()

    try:
        print("\n--- Step 1: Drop role column from accounts.TB_USERS ---")
        drop_role_column(cursor)

        conn.commit()

        print("\n--- Step 2: Drop TB_DELETION_LOG from project databases ---")
        drop_deletion_log_tables(cursor)

        conn.commit()
        print("\nRollback complete.")

    except MySQLdb.Error as exc:
        conn.rollback()
        print("\nERROR: %s" % exc)
        print("Rollback aborted — database left in its pre-rollback state.")
        sys.exit(1)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
