import uuid

import pytest

from conftest import count

GUARDED = [
    ("GET", "/register"),
    ("GET", "/newdb"),
    ("GET", "/rf_full_data/deldbconf"),
    ("GET", "/rf_full_data/delete"),
    ("GET", "/rf_full_data/deleconf/1"),
    ("GET", "/rf_full_data/edelete/1"),
    ("POST", "/register"),
    ("POST", "/newdb"),
]


def seed_state(db_conn):
    return (
        count(
            db_conn,
            "SELECT COUNT(*) FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME='rf_full_data'",
        ),
        count(db_conn, "SELECT COUNT(*) FROM rf_full_data.TB_EXECUTION"),
    )


@pytest.fixture
def seed_unchanged(db_conn):
    before = seed_state(db_conn)
    assert before[0] == 1
    yield
    assert seed_state(db_conn) == before


@pytest.mark.parametrize("method,path", GUARDED)
def test_unauthenticated_forbidden(client, seed_unchanged, method, path):
    assert client.open(path, method=method).status_code == 403


@pytest.mark.parametrize("method,path", GUARDED)
def test_viewer_forbidden(viewer, seed_unchanged, method, path):
    assert viewer.open(path, method=method).status_code == 403


@pytest.mark.parametrize(
    "path",
    ["/register", "/newdb", "/rf_full_data/deldbconf", "/rf_full_data/deleconf/1"],
)
def test_lead_allowed_get(lead, seed_unchanged, path):
    assert lead.get(path).status_code == 200


def test_lead_delete_project(lead, throwaway_db, db_conn):
    resp = lead.get(f"/{throwaway_db}/delete")
    assert resp.status_code == 302
    assert (
        count(
            db_conn,
            "SELECT COUNT(*) FROM information_schema.SCHEMATA " "WHERE SCHEMA_NAME=%s",
            (throwaway_db,),
        )
        == 0
    )
    assert (
        count(
            db_conn,
            "SELECT COUNT(*) FROM robothistoric.TB_PROJECT " "WHERE Project_Name=%s",
            (throwaway_db,),
        )
        == 0
    )


def test_lead_register_user(lead, db_conn):
    email = f"pytest_{uuid.uuid4().hex[:8]}@local"
    try:
        resp = lead.post(
            "/register",
            data={"name": "pytest", "email": email, "password": "pw", "role": "viewer"},
        )
        assert resp.status_code == 302
        assert (
            count(
                db_conn,
                "SELECT COUNT(*) FROM accounts.TB_USERS WHERE email=%s",
                (email,),
            )
            == 1
        )
    finally:
        db_conn.cursor().execute(
            "DELETE FROM accounts.TB_USERS WHERE email=%s", (email,)
        )


def test_public_routes_no_session(client):
    for path in ["/", "/login", "/rf_full_data/dashboard"]:
        assert client.get(path).status_code == 200, path


def test_login_seeded_lead(client):
    resp = client.post("/login", data={"email": "admin@local", "password": "admin"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert sess.get("role") == "lead"
    assert client.get("/newdb").status_code == 200


def test_login_wrong_password(client):
    resp = client.post("/login", data={"email": "admin@local", "password": "wrong"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "role" not in sess


def test_logout_clears_session(lead):
    assert lead.get("/logout").status_code == 302
    assert lead.get("/newdb").status_code == 403
