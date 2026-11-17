import os
import time
import uuid

import MySQLdb
import MySQLdb.cursors
import pytest

DB_HOST = os.environ.get("SQLHOST", "db")
DB_PORT = int(os.environ.get("PORT", 3306))
DB_USER = os.environ.get("USERNAME", "root")
DB_PASSWORD = os.environ.get("PASSWORD", "password")

SEED_DBS = ["rf_full_data", "roomba_sync_data", "empty_project"]

# (eid, total, pass, fail) for throwaway_db executions
SEED_EXECUTIONS = [(1, 3, 2, 1), (2, 1, 1, 0)]


def _connect(**kwargs):
    return MySQLdb.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, passwd=DB_PASSWORD, **kwargs
    )


def wait_for_db(timeout=120):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM robothistoric.TB_PROJECT")
                if cur.fetchone()[0] >= 3:
                    return
            finally:
                conn.close()
        except MySQLdb.Error as e:
            last_error = e
        time.sleep(2)
    pytest.fail(f"DB not ready after {timeout}s: {last_error}")


def count(db_conn, sql, args=()):
    cur = db_conn.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    return list(row.values())[0]


def login_as(client, role, email="pytest@local"):
    with client.session_transaction() as sess:
        sess["role"] = role
        sess["email"] = email
        sess["name"] = "pytest"
    return client


@pytest.fixture(scope="session")
def app_config():
    wait_for_db()
    from robotframework_historic.app import app

    app.config.update(
        MYSQL_HOST=DB_HOST,
        MYSQL_PORT=DB_PORT,
        MYSQL_USER=DB_USER,
        MYSQL_PASSWORD=DB_PASSWORD,
        TESTING=True,
    )
    app.config["auth_plugin"] = "mysql_native_password"
    app.secret_key = "pytest"
    return app


@pytest.fixture
def client(app_config):
    return app_config.test_client()


@pytest.fixture
def viewer(client):
    return login_as(client, "viewer")


@pytest.fixture
def lead(client):
    return login_as(client, "lead")


@pytest.fixture
def db_conn():
    conn = _connect(autocommit=True, cursorclass=MySQLdb.cursors.DictCursor)
    yield conn
    conn.close()


@pytest.fixture
def throwaway_db(lead, db_conn):
    name = f"pytest_{uuid.uuid4().hex[:8]}"
    try:
        resp = lead.post(
            "/newdb", data={"dbname": name, "dbdesc": "pytest", "dbimage": ""}
        )
        assert resp.status_code == 302
        assert (
            count(
                db_conn,
                "SELECT COUNT(*) FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME=%s",
                (name,),
            )
            == 1
        )
        assert (
            count(
                db_conn,
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s",
                (name,),
            )
            == 4
        )

        cur = db_conn.cursor()
        for eid, total, passed, failed in SEED_EXECUTIONS:
            cur.execute(
                f"INSERT INTO `{name}`.TB_EXECUTION (Execution_Id, Execution_Date, "
                "Execution_Desc, Execution_Total, Execution_Pass, Execution_Fail, "
                "Execution_Time, Execution_STotal, Execution_SPass, Execution_SFail, "
                "Execution_Skip, Execution_SSkip) "
                "VALUES (%s, NOW(), %s, %s, %s, %s, 1.5, %s, %s, %s, 0, 0)",
                (
                    eid,
                    f"exec {eid}",
                    total,
                    passed,
                    failed,
                    2 if eid == 1 else 1,
                    1,
                    1 if eid == 1 else 0,
                ),
            )
            suites = 2 if eid == 1 else 1
            for s in range(suites):
                cur.execute(
                    f"INSERT INTO `{name}`.TB_SUITE "
                    "(Execution_Id, Suite_Name, Suite_Status, Suite_Total, "
                    "Suite_Pass, Suite_Fail, Suite_Time, Suite_Skip) "
                    "VALUES (%s, %s, 'PASS', 1, 1, 0, 0.5, 0)",
                    (eid, f"Suite {eid}.{s}"),
                )
            statuses = ["PASS"] * passed + ["FAIL"] * failed
            for t, status in enumerate(statuses):
                cur.execute(
                    f"INSERT INTO `{name}`.TB_TEST "
                    "(Execution_Id, Test_Name, Test_Status, Test_Time, Test_Error) "
                    "VALUES (%s, %s, %s, 0.1, '')",
                    (eid, f"Test {eid}.{t}", status),
                )
        cur.execute(
            "UPDATE robothistoric.TB_PROJECT SET Total_Executions=2 "
            "WHERE Project_Name=%s",
            (name,),
        )
        yield name
    finally:
        cur = db_conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.execute(
            "DELETE FROM robothistoric.TB_PROJECT WHERE Project_Name=%s", (name,)
        )
