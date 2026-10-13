from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field
from .compute import Compute
from .errors import RuleError
from .parameters import VERSION

# Saves live in the player's browser. The server keeps nothing between requests: each request carries the
# core state this server signed last time, and each reply carries the next signed state.
DATA=Path(os.environ.get('COASTAL_DATA',str(Path(__file__).resolve().parent.parent/'data')))
COMPUTE=Compute(); LOCK=threading.RLock(); KEY=b''
# The browser keeps the chart history. The last step's metrics and snapshot stay signed: recomputing them
# after the step has been committed would show a different dispatch for the same interval.
DISPLAY=('history',)
HISTORY=672

class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['new','advance','build','settings','weather','fault','repair','maintenance','plan_save','plan_build']
    target:str=Field(default='',max_length=40,pattern=r'^[a-zA-Z0-9_]*$')
    steps:int=Field(default=1,ge=1,le=672)
    seed:int=Field(default=42,ge=0,le=1_000_000)
    settings:dict=Field(default_factory=dict,max_length=7)
    breaker_failure:bool=False
    plan:dict|None=None

class Replay(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['powergame.coastal.v2']
    seed:int=Field(default=42,ge=0,le=1_000_000)
    commands:list[Action]=Field(default_factory=list,max_length=2048)
class ImportRequest(BaseModel): save:Replay
class NewScenario(BaseModel): seed:int=Field(default=42,ge=0,le=1_000_000)
class Signed(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state:str=Field(max_length=500_000)
    sig:str=Field(pattern=r'^[0-9a-f]{64}$')
class CommandRequest(Signed): action:Action
class PlanCheck(Signed): plan:dict

def signing_key():
    """POWERBOLAGET_SECRET, or a key kept in the data folder. A new key only makes browsers rebuild saves from their replays."""
    if os.environ.get('POWERBOLAGET_SECRET'): return os.environ['POWERBOLAGET_SECRET'].encode()
    path=DATA/'state.key'
    if not path.exists(): path.write_text(secrets.token_hex(32),encoding='utf-8')
    return path.read_text(encoding='utf-8').strip().encode()

def sign(text): return hmac.new(KEY,text.encode(),hashlib.sha256).hexdigest()

def unpack(payload):
    if not hmac.compare_digest(sign(payload.state),payload.sig): raise HTTPException(409,'Save signature not recognised; rebuild it from its command history.')
    g=json.loads(payload.state);g['history']=[]
    return g

def bundle(g):
    """Signed core state, display data and the history rows produced by this call."""
    rows=g.get('history',[]);g=dict(g,history=[])
    core={k:v for k,v in g.items() if k not in DISPLAY}
    view=COMPUTE.call('public',g);text=json.dumps(core,separators=(',',':'),allow_nan=False)
    return dict(state=text,sig=sign(text),rows=rows,view={k:v for k,v in view.items() if k not in core and k!='history'})

@asynccontextmanager
async def lifespan(app):
    global KEY
    DATA.mkdir(parents=True,exist_ok=True);KEY=signing_key()
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

@app.get('/api/health')
def health(): return dict(status='ok',version=VERSION,solver='OpenDSSDirect.py 0.9.4',step_minutes=15)

@app.post('/api/new')
def new(payload:NewScenario):
    with LOCK: return bundle(COMPUTE.call('create',payload.seed))

@app.post('/api/resume')
def resume(payload:Signed):
    with LOCK: return bundle(unpack(payload))

@app.post('/api/command')
def command(payload:CommandRequest):
    action=payload.action.model_dump()
    if action['kind']=='new': raise RuleError('Start a new scenario from the saves menu.')
    with LOCK: return bundle(COMPUTE.call('apply',unpack(payload),action))

@app.post('/api/plan/validate')
def validate_plan(payload:PlanCheck):
    with LOCK: return COMPUTE.call('check_plan',unpack(payload),payload.plan)

@app.post('/api/import')
def import_save(payload:ImportRequest):
    replay=payload.save.model_dump()
    if any(a['kind']=='new' for a in replay['commands']) or sum(a['steps'] for a in replay['commands'] if a['kind']=='advance')>35040:
        raise RuleError('Replay contains a new-scenario command or exceeds one year.')
    with LOCK:
        g=COMPUTE.call('create',replay['seed']);history=[]
        for a in replay['commands']:
            g=COMPUTE.call('apply',dict(g,history=[]),a);history=(history+g['history'])[-HISTORY:]
        return bundle(dict(g,history=history))

app.mount('/',StaticFiles(directory=Path(__file__).resolve().parent.parent/'web',html=True),name='web')
