"""
migrate_qe7360.py — Idempotent migration for QE-7360 (Role-Based Deletion Permissions)

Changes applied:
  1. accounts.TB_USERS: add `role VARCHAR(20) NOT NULL DEFAULT 'viewer'` if absent
  2. accounts.TB_USERS: set role='lead' for the seed admin (admin@local) if still 'viewer'
  3. Every project DB in robothistoric.TB_PROJECT: CREATE TABLE IF NOT EXISTS TB_DELETION_LOG

Usage:
    python scripts/migrate_qe7360.py [--host HOST] [--port PORT] [--user USER] [--password PASSWORD]

Defaults match the docker-compose dev environment (root / password / localhost:3306).
"""

import argparse
import sys

import MySQLdb


TB_DELETION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS TB_DELETION_LOG (
    log_id                    INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    execution_id              INT          NOT NULL,
    deleted_at                DATETIME     DEFAULT CURRENT_TIMESTAMP,
    deleted_by                VARCHAR(255),
    snapshot_execution_date   DATETIME,
    snapshot_execution_desc   TEXT,
    snapshot_execution_pass   INT,
    snapshot_execution_fail   INT,
    snapshot_execution_total  INT,
    snapshot_execution_time   FLOAT,
    snapshot_execution_stotal INT,
    snapshot_execution_spass  INT,
    snapshot_execution_sfail  INT,
    INDEX (execution_id),
    INDEX (deleted_at)
)
"""


def parse_args():
    parser = argparse.ArgumentParser(description="QE-7360 schema migration")
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


def add_role_column(cursor):
    """Add role column to accounts.TB_USERS if it does not already exist."""
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = 'accounts' AND TABLE_NAME = 'TB_USERS' AND COLUMN_NAME = 'role'"
    )
    (count,) = cursor.fetchone()
    if count == 0:
        cursor.execute(
            "ALTER TABLE accounts.TB_USERS "
            "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'viewer'"
        )
        print("  [OK] Added role column to accounts.TB_USERS")
    else:
        print("  [SKIP] role column already exists on accounts.TB_USERS")


def seed_admin_role(cursor):
    """Promote the seed admin (admin@local) to 'lead' if still on default 'viewer'."""
    cursor.execute(
        "UPDATE accounts.TB_USERS SET role = 'lead' "
        "WHERE email = 'admin@local' AND role = 'viewer'"
    )
    if cursor.rowcount:
        print("  [OK] Set role='lead' for admin@local")
    else:
        print("  [SKIP] admin@local already has a non-viewer role (or does not exist)")


def add_deletion_log_tables(cursor):
    """Create TB_DELETION_LOG in every project database listed in robothistoric.TB_PROJECT."""
    cursor.execute("SELECT Project_Name FROM robothistoric.TB_PROJECT")
    projects = [row[0] for row in cursor.fetchall()]

    if not projects:
        print("  [WARN] No projects found in robothistoric.TB_PROJECT — nothing to migrate")
        return

    for project in projects:
        cursor.execute("USE `%s`" % project)
        cursor.execute(TB_DELETION_LOG_DDL)
        print("  [OK] TB_DELETION_LOG ready in project db: %s" % project)


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
        print("\n--- Step 1: accounts.TB_USERS role column ---")
        add_role_column(cursor)

        print("\n--- Step 2: Seed admin role ---")
        seed_admin_role(cursor)

        conn.commit()

        print("\n--- Step 3: TB_DELETION_LOG in project databases ---")
        add_deletion_log_tables(cursor)

        conn.commit()
        print("\nMigration complete.")

    except MySQLdb.Error as exc:
        conn.rollback()
        print("ERROR: %s" % exc)
        sys.exit(1)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
