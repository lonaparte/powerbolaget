"""HTTP API: sessions, ticks, commands, previews, saves and the request guard."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

H = {'X-PowerGame': '1'}


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c


def test_a_new_game_runs_and_takes_commands(client):
    j = client.post('/api/session', json={'seed': 3}, headers=H).json()
    sid = j['session']
    assert j['snapshot']['label'] == 'FE 1 · 01 Jan · 00:00' and j['static']['island']['name'] == 'Gutnö'
    s = client.post('/api/tick', json={'session': sid, 'minutes': 45}, headers=H).json()['snapshot']
    assert s['minute'] == 45 and s['totals']['load'] > 20
    p = client.post('/api/preview', json={'session': sid, 'build': {'type': 'storage', 'station': 'vhn', 'p_mw': 10, 'hours': 2}}, headers=H).json()
    assert p['ok'] and p['plan']['cost'] > 0
    r = client.post('/api/command', json={'session': sid, 'command': {'kind': 'build', 'build': {'type': 'storage', 'station': 'vhn', 'p_mw': 10, 'hours': 2}}}, headers=H)
    assert r.status_code == 200 and r.json()['snapshot']['projects']
    bad = client.post('/api/command', json={'session': sid, 'command': {'kind': 'build', 'build': {'type': 'storage', 'station': 'nowhere', 'p_mw': 10, 'hours': 2}}}, headers=H)
    assert bad.status_code == 400
    for eid in ('wt001', 'z01', 'f_cement', 'vhn', 'link', 'l_lnk_vhn'):
        assert client.post('/api/entity', json={'session': sid, 'id': eid}, headers=H).status_code == 200
    for name in ('zones', 'pops', 'firms', 'markets', 'finance', 'demography', 'history', 'outlook'):
        assert client.post('/api/table', json={'session': sid, 'name': name}, headers=H).status_code == 200
    save = client.post('/api/save', json={'session': sid}, headers=H).json()
    r = client.post('/api/command', json={'session': sid, 'command': {'kind':'retail_policy',
                    'category':'business','policy':{'network_fee':.35}}}, headers=H)
    assert r.status_code == 200
    finance = client.post('/api/table', json={'session': sid, 'name':'finance'}, headers=H).json()
    assert finance['retail_policy']['business']['network_fee'] == .35
    loaded = client.post('/api/session/load', json={'save': save}, headers=H).json()
    assert loaded['snapshot']['minute'] == 45


def test_requests_are_guarded(client):
    assert client.post('/api/session', json={}).status_code == 403
    assert client.post('/api/session', json={}, headers={**H, 'Origin': 'http://evil.example'}).status_code == 403
    assert client.post('/api/tick', json={'session': 'gone', 'minutes': 5}, headers=H).status_code == 410
    assert client.post('/api/session/load', json={'save': {'format': 'x'}}, headers=H).status_code == 400
    assert client.post('/api/tick', json={'session': 'x', 'minutes': 99999}, headers=H).status_code == 422
