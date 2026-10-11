from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException,Request,Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field
from .compute import Compute
from .errors import RuleError
from .parameters import VERSION

DATA=Path(os.environ.get('COASTAL_DATA',str(Path(__file__).resolve().parent.parent/'data')))
COMPUTE=Compute(); LOCK=threading.RLock()

class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['new','advance','build','settings','weather','fault','repair','maintenance','plan_save','plan_build']
    target:str=Field(default='',max_length=40,pattern=r'^[a-zA-Z0-9_]*$')
    steps:int=Field(default=1,ge=1,le=672)
    seed:int=Field(default=42,ge=0,le=1_000_000)
    settings:dict=Field(default_factory=dict,max_length=7)
    breaker_failure:bool=False
    plan:dict|None=None

class Command(Action): revision:int=Field(ge=0)
class Revision(BaseModel): revision:int=Field(ge=0)
class PlanCheck(Revision): plan:dict
class Replay(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['powergame.coastal.v2']
    seed:int=Field(default=42,ge=0,le=1_000_000)
    commands:list[Action]=Field(default_factory=list,max_length=2048)
class ImportRequest(BaseModel):
    revision:int=Field(ge=0)
    save:Replay

def db():
    conn=sqlite3.connect(DATA/'coastal.sqlite3',timeout=20)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True,exist_ok=True)
    with db() as conn: conn.execute('CREATE TABLE IF NOT EXISTS games(sid TEXT PRIMARY KEY,state TEXT NOT NULL,replay TEXT NOT NULL,checkpoint TEXT)')
    COMPUTE.call('create')
    try: yield
    finally: COMPUTE.close()

app=FastAPI(title='Powerbolaget',version=VERSION,lifespan=lifespan)

@app.middleware('http')
async def guard(request,call_next):
    if request.method=='POST':
        if request.headers.get('x-powergame')!='1': return JSONResponse({'detail':'Missing X-PowerGame header'},status_code=403)
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'): return JSONResponse({'detail':'Cross-origin write rejected'},status_code=403)
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>1_000_000: return JSONResponse({'detail':'Save file exceeds 1 MB'},status_code=413)
        request._body=bytes(data)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.exception_handler(RuleError)
async def rule_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)
@app.exception_handler(RuntimeError)
async def runtime_error(request,exc):
    logging.exception('Simulation failed',exc_info=exc)
    return JSONResponse({'detail':str(exc)},status_code=503)

def fetch(request):
    sid=request.cookies.get('powergame_coastal','')
    if len(sid)!=48 or any(c not in '0123456789abcdef' for c in sid): raise HTTPException(401,'Please reload to create a scenario.')
    with db() as conn: row=conn.execute('SELECT state,replay,checkpoint FROM games WHERE sid=?',(sid,)).fetchone()
    if not row: raise HTTPException(401,'Scenario not found. Please reload.')
    return sid,json.loads(row[0]),json.loads(row[1]),row[2]

def check(game,rev):
    if game['revision']!=rev: raise HTTPException(409,'Another page updated the scenario. Please reload.')

def expose(game,checkpoint):
    result=COMPUTE.call('public',game);result['has_checkpoint']=checkpoint is not None
    return result

def commit(sid,g,replay,clear=False):
    with db() as conn:
        conn.execute('UPDATE games SET state=?,replay=?,checkpoint=CASE WHEN ? THEN NULL ELSE checkpoint END WHERE sid=?',
                     (json.dumps(g,allow_nan=False),json.dumps(replay),clear,sid))

@app.get('/api/health')
def health(): return dict(status='ok',version=VERSION,solver='OpenDSSDirect.py 0.9.4',step_minutes=15)

@app.post('/api/plan/validate')
def validate_plan(payload:PlanCheck,request:Request):
    with LOCK:
        _,g,_,_=fetch(request);check(g,payload.revision)
        return COMPUTE.call('check_plan',g,payload.plan)

@app.get('/api/state')
def state(request:Request,response:Response):
    with LOCK:
        try: sid,g,r,c=fetch(request)
        except HTTPException:
            sid=secrets.token_hex(24);g=COMPUTE.call('create');r=dict(format='powergame.coastal.v2',seed=42,commands=[]);c=None
            with db() as conn:conn.execute('INSERT INTO games VALUES(?,?,?,NULL)',(sid,json.dumps(g),json.dumps(r)))
            response.set_cookie('powergame_coastal',sid,max_age=31536000,httponly=True,samesite='strict')
        return expose(g,c)

@app.post('/api/command')
def command(payload:Command,request:Request):
    with LOCK:
        sid,g,r,c=fetch(request);check(g,payload.revision)
        action=payload.model_dump(exclude={'revision'})
        if len(r['commands'])>=2048 and action['kind']!='new': raise RuleError('Command history is full. Export and create a new scenario.')
        updated=COMPUTE.call('apply',g,action)
        if action['kind']=='new':r=dict(format='powergame.coastal.v2',seed=action['seed'],commands=[]);c=None
        else:r['commands'].append(action)
        out=expose(updated,c);commit(sid,updated,r,action['kind']=='new')
        return out

@app.post('/api/checkpoint')
def checkpoint(payload:Revision,request:Request):
    with LOCK:
        sid,g,r,c=fetch(request);check(g,payload.revision)
        with db() as conn:conn.execute('UPDATE games SET checkpoint=? WHERE sid=?',(json.dumps(dict(state=g,replay=r)),sid))
        return dict(saved=True)

@app.post('/api/restore')
def restore(payload:Revision,request:Request):
    with LOCK:
        sid,g,r,c=fetch(request);check(g,payload.revision)
        if not c:raise RuleError('Save a checkpoint first.')
        saved=json.loads(c);saved['state']['revision']=g['revision']+1
        out=expose(saved['state'],c);commit(sid,saved['state'],saved['replay'])
        return out

@app.get('/api/export')
def export(request:Request):
    with LOCK:
        _,g,r,_=fetch(request)
        return JSONResponse(r,headers={'Content-Disposition':f'attachment; filename="coastal-step-{g["step"]}.json"'})

@app.post('/api/import')
def import_save(payload:ImportRequest,request:Request):
    with LOCK:
        sid,g,r,c=fetch(request);check(g,payload.revision)
        replay=payload.save.model_dump()
        if any(a['kind']=='new' for a in replay['commands']) or sum(a['steps'] for a in replay['commands'] if a['kind']=='advance')>35040:
            raise RuleError('Replay contains a new-scenario command or exceeds one year.')
        restored=COMPUTE.call('create',replay['seed'])
        for a in replay['commands']:restored=COMPUTE.call('apply',restored,a)
        restored['revision']=g['revision']+1
        out=expose(restored,c);commit(sid,restored,replay)
        return out

app.mount('/',StaticFiles(directory=Path(__file__).resolve().parent.parent/'web',html=True),name='web')
