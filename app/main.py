"""Powerbolaget web service: one running world per browser session.

The simulation core runs in worker processes (spec 10.1: headless core, client over HTTP; see
app/runtime.py). Each player gets a world in memory while they play; their saves live in their own
browser, which can always bring a world back by loading a save. Idle worlds are evicted; nothing is
written to disk.
"""
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from . import __version__ as VERSION
from .runtime import Gone, Rejected, Worker
from .saves import SaveError, validate

MAX_SESSIONS = int(os.environ.get('POWERBOLAGET_MAX_SESSIONS', '8'))
IDLE_SECONDS = int(os.environ.get('POWERBOLAGET_IDLE_SECONDS', '1800'))
TICK_BUDGET_S = float(os.environ.get('POWERBOLAGET_TICK_BUDGET', '2.5'))
WORKERS = [Worker() for _ in range(max(1, int(os.environ.get('POWERBOLAGET_WORKERS', '1'))))]
MAX_BODY = 12_000_000
ID = r'^[a-z0-9_]{1,48}$'
SESSIONS: dict = {}          # session id -> [worker index, worker generation, last use]
REGISTRY = threading.Lock()


def open_session(op, args):
    """Start a world in the least busy worker; evict idle or oldest sessions beyond the limit."""
    stale = []
    with REGISTRY:
        now = time.monotonic()
        stale = [(sid, SESSIONS.pop(sid)) for sid in [s for s, x in SESSIONS.items() if now-x[2] > IDLE_SECONDS]]
        while len(SESSIONS) >= MAX_SESSIONS:
            oldest = min(SESSIONS, key=lambda s: SESSIONS[s][2])
            stale.append((oldest, SESSIONS.pop(oldest)))
        load = [sum(1 for x in SESSIONS.values() if x[0] == i) for i in range(len(WORKERS))]
        index = load.index(min(load))
    for sid, (i, _, _) in stale:
        try:
            WORKERS[i].call('drop', sid, None)
        except (Gone, Rejected, RuntimeError):
            pass
    sid = secrets.token_urlsafe(18)
    try:
        result = WORKERS[index].call(op, sid, args)
    except Rejected as exc:
        raise HTTPException(400, str(exc))
    with REGISTRY:
        SESSIONS[sid] = [index, WORKERS[index].generation, time.monotonic()]
    return dict(session=sid, **result)


def call(sid, op, args=None):
    with REGISTRY:
        entry = SESSIONS.get(sid)
        if entry is not None:
            entry[2] = time.monotonic()
    gone = HTTPException(410, 'This game is no longer running on the server; it continues from your browser save.')
    if entry is None or WORKERS[entry[0]].generation != entry[1]:
        raise gone
    try:
        return WORKERS[entry[0]].call(op, sid, args or {})
    except Gone:
        with REGISTRY:
            SESSIONS.pop(sid, None)
        raise gone
    except Rejected as exc:
        raise HTTPException(400, str(exc))


class New(BaseModel):
    seed: int = Field(default=1, ge=0, le=1_000_000)


class Load(BaseModel):
    save: dict


class Ref(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session: str = Field(max_length=64)


class Tick(Ref):
    minutes: int = Field(ge=1, le=1440)
    since_log: int = Field(default=0, ge=0)
    grid_version: int = -1
    firm_count: int = -1


class Build(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['turbine', 'storage', 'line', 'transformer', 'station', 'interconnector']
    model: Optional[str] = Field(default=None, max_length=12)
    x: Optional[float] = Field(default=None, ge=-60, le=160)
    y: Optional[float] = Field(default=None, ge=-60, le=160)
    station: Optional[str] = Field(default=None, pattern=ID)
    p_mw: Optional[float] = Field(default=None, ge=1, le=640)
    connect_bus: Optional[str] = Field(default=None, pattern=ID)
    route: Optional[list[list[float]]] = Field(default=None, min_length=2, max_length=128)
    name: Optional[str] = Field(default=None, max_length=60)
    mv_kv: Literal[20, 33] = 20
    mva: float = Field(default=40., ge=5, le=200)
    technology: Literal['HVDC', 'HVAC'] = 'HVAC'
    hours: Optional[float] = Field(default=None, ge=.5, le=8)
    grid_forming: bool = False
    a: Optional[str] = Field(default=None, pattern=ID)
    b: Optional[str] = Field(default=None, pattern=ID)
    line_type: Literal['OHL110', 'CAB110', 'OHL20', 'CAB20', 'CAB33'] = 'OHL110'


class RetailPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    network_fee: Optional[float] = Field(default=None, ge=0, le=5)
    fixed_markup: Optional[float] = Field(default=None, ge=-.5, le=5)
    floating_markup: Optional[float] = Field(default=None, ge=-.5, le=5)
    fixed_days: Optional[int] = Field(default=None, ge=1, le=1095)
    floating_days: Optional[int] = Field(default=None, ge=1, le=1095)
    floating_index: Optional[Literal['spot', 'monthly']] = None


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    kind: Literal['build', 'maintenance', 'switch', 'storage_mode', 'settings', 'retail_policy', 'asset_work', 'cancel_project']
    action: Optional[Literal['decommission','retrofit','maintenance']] = None
    category: Optional[Literal['household', 'industry', 'business']] = None
    policy: Optional[RetailPolicy] = None
    build: Optional[Build] = None
    target: Optional[str] = Field(default=None, pattern=ID)
    closed: Optional[bool] = None
    mode: Optional[Literal['auto', 'hold', 'charge', 'discharge']] = None
    setpoint: Optional[float] = Field(default=None, ge=0, le=1000)
    link_margin: Optional[float] = Field(default=None, ge=0, le=.3)


class CommandRequest(Ref):
    command: Command
    since_log: int = Field(default=0, ge=0)


class PreviewRequest(Ref):
    build: Build


class EntityRequest(Ref):
    id: str = Field(max_length=48)


class ParcelRequest(Ref):
    x: float = Field(ge=-10, le=100)
    y: float = Field(ge=-10, le=130)


class TableRequest(Ref):
    name: Literal['zones', 'pops', 'firms', 'markets', 'finance', 'demography', 'history', 'outlook']


@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        for w in WORKERS:
            w.stop()


app = FastAPI(title='Powerbolaget', version=VERSION, lifespan=lifespan)


@app.middleware('http')
async def guard(request, call_next):
    if request.method == 'POST':
        if request.headers.get('x-powergame') != '1':
            return JSONResponse({'detail': 'Missing X-PowerGame header'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Cross-origin write rejected'}, status_code=403)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BODY:
                return JSONResponse({'detail': 'Request exceeds 12 MB'}, status_code=413)
        request._body = bytes(data)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/api/health')
def health():
    return dict(status='ok', version=VERSION, solver='OpenDSS (OpenDSSDirect.py)', sessions=len(SESSIONS),
                workers=len(WORKERS), resolution='1 minute')


@app.post('/api/session')
def new_session(payload: New):
    return open_session('new', dict(seed=payload.seed))


@app.post('/api/session/load')
def load_session(payload: Load):
    try:
        state = validate(payload.save)
    except SaveError as exc:
        raise HTTPException(400, str(exc))
    try:
        return open_session('load', dict(state=state))
    except RuntimeError as exc:
        logging.error('Save could not be loaded: %s', exc)
        raise HTTPException(400, 'This save could not be loaded.')


@app.post('/api/tick')
def tick(payload: Tick):
    return call(payload.session, 'tick', dict(minutes=payload.minutes, since_log=payload.since_log, budget=TICK_BUDGET_S,
                                              grid_version=payload.grid_version, firm_count=payload.firm_count))


@app.post('/api/command')
def run_command(payload: CommandRequest):
    cmd = payload.command.model_dump(exclude_none=True)
    if 'build' in cmd:
        cmd['build'] = {k: v for k, v in cmd['build'].items() if v is not None}
    return call(payload.session, 'command', dict(command=cmd, since_log=payload.since_log))


@app.post('/api/preview')
def preview(payload: PreviewRequest):
    return call(payload.session, 'preview', dict(build={k: v for k, v in payload.build.model_dump().items() if v is not None}))


@app.post('/api/save')
def save(payload: Ref):
    return call(payload.session, 'save')


@app.post('/api/entity')
def entity(payload: EntityRequest):
    out = call(payload.session, 'entity', dict(id=payload.id))
    if out is None:
        raise HTTPException(404, 'Unknown object.')
    return out


@app.get('/api/land')
def land_grid():
    """The island's parcels (land use and zone of every 0.5 km cell) and its long-term mean wind field."""
    from .land import encoded
    from .windfield import FIELD
    return dict(encoded(), wind={k: FIELD[k] for k in ('x0', 'y0', 'cell_km', 'nx', 'ny', 'values', 'height_m', 'source')})


@app.post('/api/parcel')
def parcel(payload: ParcelRequest):
    out = call(payload.session, 'parcel', dict(x=payload.x, y=payload.y))
    if out is None:
        raise HTTPException(404, 'Outside the map.')
    return out


@app.post('/api/table')
def table(payload: TableRequest):
    return call(payload.session, 'table', dict(name=payload.name))


@app.exception_handler(RuntimeError)
async def failed(request, exc):
    logging.error('Simulation failed: %s', exc)
    return JSONResponse({'detail': 'The simulation failed; the error is in the server log.'}, status_code=503)


app.mount('/', StaticFiles(directory=Path(__file__).resolve().parent.parent/'web', html=True), name='web')
