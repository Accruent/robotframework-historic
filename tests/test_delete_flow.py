import pytest

from conftest import SEED_EXECUTIONS, count


def eid_rows(db_conn, db, eid):
    return {
        t: count(
            db_conn, f"SELECT COUNT(*) FROM `{db}`.{t} WHERE Execution_Id=%s", (eid,)
        )
        for t in ("TB_EXECUTION", "TB_SUITE", "TB_TEST")
    }


def audit_count(db_conn, db, eid):
    return count(
        db_conn,
        f"SELECT COUNT(*) FROM `{db}`.TB_DELETION_LOG WHERE execution_id=%s",
        (eid,),
    )


def project_row(db_conn, db):
    cur = db_conn.cursor()
    cur.execute(
        "SELECT Total_Executions, Recent_Pass_Perc, Last_Updated "
        "FROM robothistoric.TB_PROJECT WHERE Project_Name=%s",
        (db,),
    )
    return cur.fetchone()


def delete(client, db, eid):
    return client.get(f"/{db}/edelete/{eid}")


def test_lead_delete_removes_rows_and_audits(lead, throwaway_db, db_conn):
    eid2_before = eid_rows(db_conn, throwaway_db, 2)
    resp = delete(lead, throwaway_db, 1)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/{throwaway_db}/ehistoric")

    assert eid_rows(db_conn, throwaway_db, 1) == {
        "TB_EXECUTION": 0,
        "TB_SUITE": 0,
        "TB_TEST": 0,
    }
    assert eid_rows(db_conn, throwaway_db, 2) == eid2_before

    cur = db_conn.cursor()
    cur.execute(f"SELECT * FROM `{throwaway_db}`.TB_DELETION_LOG WHERE execution_id=1")
    logs = cur.fetchall()
    assert len(logs) == 1
    _, total, passed, failed = SEED_EXECUTIONS[0]
    assert logs[0]["deleted_by"] == "pytest@local"
    assert (
        logs[0]["snapshot_execution_total"],
        logs[0]["snapshot_execution_pass"],
        logs[0]["snapshot_execution_fail"],
    ) == (total, passed, failed)

    _, total2, passed2, _ = SEED_EXECUTIONS[1]
    row = project_row(db_conn, throwaway_db)
    assert row["Total_Executions"] == 1
    assert float(row["Recent_Pass_Perc"]) == float(
        "{0:.2f}".format(passed2 / total2 * 100)
    )


def test_repeat_delete_is_noop(lead, throwaway_db, db_conn):
    assert delete(lead, throwaway_db, 1).status_code == 302
    before = project_row(db_conn, throwaway_db)
    assert delete(lead, throwaway_db, 1).status_code == 302
    assert audit_count(db_conn, throwaway_db, 1) == 1
    assert project_row(db_conn, throwaway_db) == before


def test_delete_last_execution_zeroes_summary(lead, throwaway_db, db_conn):
    assert delete(lead, throwaway_db, 1).status_code == 302
    assert delete(lead, throwaway_db, 2).status_code == 302
    row = project_row(db_conn, throwaway_db)
    assert row["Total_Executions"] == 0
    assert float(row["Recent_Pass_Perc"]) == 0
    assert lead.get(f"/{throwaway_db}/ehistoric").status_code == 200


def test_delete_execution_without_children(lead, throwaway_db, db_conn):
    db_conn.cursor().execute(
        f"INSERT INTO `{throwaway_db}`.TB_EXECUTION (Execution_Id, Execution_Date, "
        "Execution_Total, Execution_Pass, Execution_Fail) VALUES (3, NOW(), 0, 0, 0)"
    )
    assert delete(lead, throwaway_db, 3).status_code == 302
    assert audit_count(db_conn, throwaway_db, 3) == 1
    assert eid_rows(db_conn, throwaway_db, 3)["TB_EXECUTION"] == 0


def test_db_error_returns_500_and_rolls_back(lead, throwaway_db, db_conn):
    rows_before = eid_rows(db_conn, throwaway_db, 1)
    audit_before = count(
        db_conn, f"SELECT COUNT(*) FROM `{throwaway_db}`.TB_DELETION_LOG"
    )
    project_before = project_row(db_conn, throwaway_db)
    cur = db_conn.cursor()
    # DELETE on TB_TEST runs after the audit INSERT and the execution/suite deletes
    cur.execute(f"RENAME TABLE `{throwaway_db}`.TB_TEST TO `{throwaway_db}`.TB_TEST_x")
    try:
        resp = delete(lead, throwaway_db, 1)
        assert resp.status_code == 500
        assert b"Delete failed; no changes were saved" in resp.data
        assert (
            count(db_conn, f"SELECT COUNT(*) FROM `{throwaway_db}`.TB_DELETION_LOG")
            == audit_before
        )
        for t in ("TB_EXECUTION", "TB_SUITE"):
            assert (
                count(
                    db_conn,
                    f"SELECT COUNT(*) FROM `{throwaway_db}`.{t} "
                    "WHERE Execution_Id=1",
                )
                == rows_before[t]
            )
        assert project_row(db_conn, throwaway_db) == project_before
    finally:
        cur.execute(
            f"RENAME TABLE `{throwaway_db}`.TB_TEST_x TO `{throwaway_db}`.TB_TEST"
        )


@pytest.mark.parametrize("who", ["client", "viewer"])
def test_viewer_and_unauth_cannot_delete(request, who, throwaway_db, db_conn):
    rows_before = eid_rows(db_conn, throwaway_db, 1)
    client = request.getfixturevalue(who)
    if who == "client":
        with client.session_transaction() as sess:
            sess.clear()
    assert delete(client, throwaway_db, 1).status_code == 403
    assert eid_rows(db_conn, throwaway_db, 1) == rows_before
    assert audit_count(db_conn, throwaway_db, 1) == 0
