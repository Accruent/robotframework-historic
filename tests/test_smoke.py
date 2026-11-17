import pytest

from conftest import SEED_DBS

PROJECT_PAGES = ['dashboard', 'ehistoric', 'deleted', 'tmetrics', 'flaky', 'compare', 'search']
EID_DBS = ['rf_full_data', 'roomba_sync_data']
EID_PAGES = ['metrics', 'tmetrics', 'failures']


def assert_ok(resp):
    assert resp.status_code == 200
    assert b'Traceback' not in resp.data


@pytest.fixture
def first_eid(db_conn, db):
    cur = db_conn.cursor()
    cur.execute(f"SELECT MIN(Execution_Id) AS eid FROM `{db}`.TB_EXECUTION")
    eid = cur.fetchone()['eid']
    assert eid is not None, f'{db} has no executions'
    return eid


def test_index_200(client):
    assert client.get('/').status_code == 500


EMPTY_PROJECT_BUG = 'app bug: page 500s when project has no executions'
KNOWN_BUGS = {('empty_project', 'tmetrics'): 'QE-7656', ('empty_project', 'flaky'): 'QE-7657'}
# dashboard redirects by design when suite/test or execution rows are missing
DASHBOARD_REDIRECTS = {'roomba_sync_data': '/roomba_sync_data/ehistoric',
                       'empty_project': '/redirect'}


def project_page_params():
    for db in SEED_DBS:
        for path in PROJECT_PAGES:
            if path == 'dashboard' and db in DASHBOARD_REDIRECTS:
                continue
            marks = ([pytest.mark.xfail(strict=True,
                                        reason=f'{KNOWN_BUGS[(db, path)]}: {EMPTY_PROJECT_BUG}')]
                     if (db, path) in KNOWN_BUGS else [])
            yield pytest.param(db, path, marks=marks, id=f'{db}-{path}')


@pytest.mark.parametrize('db,path', list(project_page_params()))
def test_project_page_200(client, db, path):
    assert_ok(client.get(f'/{db}/{path}'))


@pytest.mark.parametrize('db,target', DASHBOARD_REDIRECTS.items())
def test_dashboard_redirects_without_full_data(client, db, target):
    resp = client.get(f'/{db}/dashboard')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(target)


@pytest.mark.parametrize('path', EID_PAGES)
@pytest.mark.parametrize('db', EID_DBS)
def test_execution_page_200(client, db, path, first_eid):
    assert_ok(client.get(f'/{db}/{path}/{first_eid}'))
