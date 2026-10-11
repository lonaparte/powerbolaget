import os
from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path):
    main.DATA=tmp_path
    with TestClient(main.app) as c:
        c.headers['X-PowerGame']='1'
        yield c


def test_session_csrf_revision_checkpoint_replay(client):
    c=client
    first=c.get('/api/state').json()
    assert first['installed_mw']==20
    assert c.post('/api/checkpoint',json={'revision':0}).status_code==200
    r=c.post('/api/command',json={'kind':'advance','steps':4,'revision':0})
    assert r.status_code==200,r.text
    after=r.json()
    assert after['step']==4
    assert c.post('/api/command',json={'kind':'advance','revision':0}).status_code==409
    save=c.get('/api/export').json()
    restored=c.post('/api/restore',json={'revision':1}).json()
    assert restored['step']==0 and restored['revision']==2
    imported=c.post('/api/import',json={'revision':2,'save':save})
    assert imported.status_code==200,imported.text
    assert imported.json()['metrics']==after['metrics']
    assert c.post('/api/command',headers={'Origin':'https://example.org'},json={'kind':'advance','revision':3}).status_code==403
    c.cookies.clear()
    isolated=c.get('/api/state').json()
    assert isolated['step']==0
    c.headers.pop('X-PowerGame')
    assert c.post('/api/checkpoint',json={'revision':0}).status_code==403


def test_rejected_commands_do_not_modify_state(client):
    c=client;initial=c.get('/api/state').json()
    for data,code in [({'kind':'advance','steps':673,'revision':0},422),
                      ({'kind':'settings','settings':{'import_limit_mw':21},'revision':0},400),
                      ({'kind':'repair','target':'grid','revision':0},400)]:
        response=c.post('/api/command',json=data)
        assert response.status_code==code,response.text
        assert c.get('/api/state').json()==initial
    bad={'format':'powergame.coastal.v2','commands':[{'kind':'new'}]}
    assert c.post('/api/import',json={'revision':0,'save':bad}).status_code==400
    assert c.get('/api/state').json()==initial


def test_planner_api_roundtrip_and_rejected_revision(client):
    c=client;initial=c.get('/api/state').json();p=initial['draft']
    report=c.post('/api/plan/validate',json={'revision':0,'plan':p})
    assert report.status_code==200,report.text
    assert not report.json()['errors']
    assert c.get('/api/state').json()==initial
    built=c.post('/api/command',json={'kind':'plan_build','plan':p,'revision':0})
    assert built.status_code==200,built.text
    assert built.json()['projects'][0]['days']==report.json()['schedule']['days']
    assert c.post('/api/plan/validate',json={'revision':0,'plan':p}).status_code==409
    save=c.get('/api/export').json()
    imported=c.post('/api/import',json={'revision':1,'save':save})
    assert imported.status_code==200,imported.text
    assert imported.json()['projects']==built.json()['projects']
    assert imported.json()['metrics']==built.json()['metrics']
    assert b'Powerbolaget' in c.get('/').content
    assert 'lang="en"' in c.get('/').text
    assert 'langToggle' not in c.get('/').text
    assert c.get('/api/health').json()['version']=='0.0.1'
    assert initial['snapshot']['weather']['location']=='A Baltic coastal city'
