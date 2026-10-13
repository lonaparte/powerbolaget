import json
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.delenv('POWERBOLAGET_SECRET',raising=False)
    with TestClient(main.app) as c:
        c.headers['X-PowerGame']='1'
        yield c


def core(bundle):
    return json.loads(bundle['state'])


def signed(bundle,**extra):
    return dict(state=bundle['state'],sig=bundle['sig'],**extra)


def test_stateless_signed_saves_replay_and_csrf(client):
    c=client
    first=c.post('/api/new',json={'seed':42}).json()
    state=json.loads(first['state'])
    assert first['view']['installed_mw']==20 and first['rows']==[]
    assert 'history' not in state and 'metrics' in state
    r=c.post('/api/command',json=signed(first,action={'kind':'advance','steps':4}))
    assert r.status_code==200,r.text
    after=r.json()
    assert json.loads(after['state'])['step']==4 and len(after['rows'])==4
    # The server keeps nothing: the same signed state gives the same result again.
    again=c.post('/api/command',json=signed(first,action={'kind':'advance','steps':4})).json()
    assert core(again)['metrics']==core(after)['metrics'] and again['state']==after['state']
    resumed=c.post('/api/resume',json=signed(after)).json()
    assert core(resumed)['metrics']==core(after)['metrics'] and resumed['rows']==[] and resumed['state']==after['state']
    tampered=json.loads(after['state']);tampered['cash']=1e12
    assert c.post('/api/command',json=dict(state=json.dumps(tampered),sig=after['sig'],action={'kind':'advance'})).status_code==409
    replay={'format':'powergame.coastal.v2','seed':42,'commands':[{'kind':'advance','steps':4}]}
    imported=c.post('/api/import',json={'save':replay}).json()
    assert imported['state']==after['state'] and imported['rows']==after['rows']
    assert c.post('/api/command',headers={'Origin':'https://example.org'},json=signed(after,action={'kind':'advance'})).status_code==403
    c.headers.pop('X-PowerGame')
    assert c.post('/api/resume',json=signed(after)).status_code==403


def test_signing_key_persists_and_foreign_saves_are_rejected(client,tmp_path,monkeypatch):
    first=client.post('/api/new',json={'seed':7}).json()
    key=(tmp_path/'state.key').read_text(encoding='utf-8').strip()
    monkeypatch.setattr(main,'KEY',b'another server')
    assert client.post('/api/resume',json=signed(first)).status_code==409
    monkeypatch.setattr(main,'KEY',key.encode())
    assert client.post('/api/resume',json=signed(first)).status_code==200


def test_rejected_commands_return_errors(client):
    c=client;first=c.post('/api/new',json={}).json()
    for action,code in [({'kind':'advance','steps':673},422),({'kind':'settings','settings':{'import_limit_mw':21}},400),
                        ({'kind':'repair','target':'grid'},400),({'kind':'new'},400)]:
        response=c.post('/api/command',json=signed(first,action=action))
        assert response.status_code==code,response.text
    bad={'format':'powergame.coastal.v2','commands':[{'kind':'new'}]}
    assert c.post('/api/import',json={'save':bad}).status_code==400
    assert c.post('/api/command',json=dict(state='{}',sig='0'*64,action={'kind':'advance'})).status_code==409


def test_planner_api_roundtrip_and_replay(client):
    c=client;first=c.post('/api/new',json={'seed':42}).json();p=json.loads(first['state'])['draft']
    report=c.post('/api/plan/validate',json=signed(first,plan=p))
    assert report.status_code==200,report.text
    assert not report.json()['errors']
    built=c.post('/api/command',json=signed(first,action={'kind':'plan_build','plan':p}))
    assert built.status_code==200,built.text
    projects=json.loads(built.json()['state'])['projects']
    assert projects[0]['days']==report.json()['schedule']['days']
    imported=c.post('/api/import',json={'save':{'format':'powergame.coastal.v2','seed':42,'commands':[{'kind':'plan_build','plan':p}]}}).json()
    assert json.loads(imported['state'])['projects']==projects
    assert core(imported)['metrics']==core(built.json())['metrics']
    assert b'Powerbolaget' in c.get('/').content
    assert 'lang="en"' in c.get('/').text
    assert 'langToggle' not in c.get('/').text
    assert c.get('/api/health').json()['version']=='0.0.1'
    assert core(first)['snapshot']['weather']['location']=='A Baltic coastal city'
