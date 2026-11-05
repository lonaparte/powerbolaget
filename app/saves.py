"""Checks on a save file before it becomes a running world.

Saves live in the player's browser and come back through the API, so they are untrusted input.
Element ids end up inside power-flow engine commands, so they must match a strict pattern; catalog
references must exist; sizes are bounded so a crafted file cannot exhaust the server.
"""
import re
from math import isfinite
from . import grid as G
from .island import TURBINE_MODELS
from .params import POP_CAP

ID = re.compile(r'^[a-z0-9_]{1,48}$')
LIMITS = dict(buses=3000, branches=4000, turbines=800, storage=200, devices=3000, pops=POP_CAP, firms=600, heap=200000)


class SaveError(ValueError):
    pass


def validate(state):
    if not isinstance(state, dict) or state.get('format') != 'powerbolaget.world' or state.get('schema') != 1:
        raise SaveError('Not a Powerbolaget 0.1 world save.')
    grid = state.get('grid')
    if not isinstance(grid, dict):
        raise SaveError('The save has no grid.')
    for key in ('buses', 'branches', 'turbines', 'storage'):
        items = grid.get(key)
        if not isinstance(items, dict) or len(items) > LIMITS[key]:
            raise SaveError(f'Invalid or oversized {key}.')
        for k in items:
            if not ID.match(k):
                raise SaveError(f'Invalid {key} id.')
            if not isinstance(items[k],dict) or items[k].get('id')!=k:
                raise SaveError(f'Mismatched {key} element id.')
    for b in grid['buses'].values():
        if b.get('kv') not in G.BASES_KV or not _num(b.get('x'),-100,250) or not _num(b.get('y'),-100,250):
            raise SaveError('Invalid bus voltage or coordinates.')
    for k, br in grid['branches'].items():
        if br.get('a') not in grid['buses'] or br.get('b') not in grid['buses']:
            raise SaveError('A branch connects to an unknown bus.')
        if br.get('kind') == 'line' and br.get('type') not in G.LINE_TYPES:
            raise SaveError('Unknown line type.')
        if br.get('kind') == 'transformer' and br.get('type') not in G.TRANSFORMER_TYPES:
            raise SaveError('Unknown transformer type.')
        if br.get('kind') not in ('line', 'transformer'):
            raise SaveError('Unknown branch kind.')
        for f in ('km', 'mva'):
            if f in br and not _num(br[f], 0, 1e5):
                raise SaveError('Invalid branch size.')
        if not _num(br.get('circuits', 1), 1, 20):
            raise SaveError('Invalid circuit count.')
        if not _num(br.get('tap',1.),.9,1.1) or not _num(br.get('rating_factor',1.),.1,10):
            raise SaveError('Invalid branch settings.')
        fault=br.get('active_fault')
        if fault is not None and (not isinstance(fault,dict) or fault.get('bus') not in grid['buses'] or not _num(fault.get('r'),.001,1e6)):
            raise SaveError('Invalid active fault.')
    for t in grid['turbines'].values():
        if t.get('model') not in TURBINE_MODELS or t.get('bus_lv') not in grid['buses'] or t.get('bus_mv') not in grid['buses']:
            raise SaveError('Invalid turbine.')
    for s in grid['storage'].values():
        if s.get('bus') not in grid['buses'] or not _num(s.get('p_mw'), .001, 1000) or not _num(s.get('e_mwh'), .001, 10000):
            raise SaveError('Invalid battery.')
    if not isinstance(grid.get('oil',{}),dict) or len(grid.get('oil',{}))>200:
        raise SaveError('Invalid backup generators.')
    for key,g in grid.get('oil',{}).items():
        if not ID.match(key) or key!=g.get('id') or g.get('bus') not in grid['buses'] or not _num(g.get('p_mw'),.5,100):
            raise SaveError('Invalid backup generator.')
        if not _num(g.get('fuel_mwh'),0,1e9) or not _num(g.get('eff'),.1,.6):
            raise SaveError('Invalid generator fuel state.')
    if grid.get('source_bus') not in grid['buses']:
        raise SaveError('Invalid source bus.')
    devices = state.get('devices')
    if not isinstance(devices, dict) or len(devices) > LIMITS['devices']:
        raise SaveError('Invalid load devices.')
    for k, d in devices.items():
        if not ID.match(k) or d.get('id')!=k or d.get('bus') not in grid['buses'] or not _num(d.get('pf'), .5, 1):
            raise SaveError('Invalid load device.')
    for name,ref in grid.get('references',{}).items():
        if not ID.match(name) or not isinstance(ref,dict) or ref.get('bus') not in grid['buses']:
            raise SaveError('Invalid voltage reference.')
        v=ref.get('values',[])
        if len(v)!=3 or not _num(v[0],.05,1.2) or not _num(v[1],-1e9,1e9) or not _num(v[2],.001,1e8):
            raise SaveError('Invalid voltage reference settings.')
    for name,s in state.get('rms',{}).get('states',{}).items():
        y=s.get('y',[])
        if not ID.match(name) or len(y)!=4 or any(not _num(x,-1e9,1e9) for x in y) or not _num(s.get('factor'),1,50):
            raise SaveError('Invalid RMS controller state.')
    for key in ('pops', 'firms'):
        if not isinstance(state.get(key), dict) or len(state[key]) > LIMITS[key]:
            raise SaveError(f'Invalid or oversized {key}.')
    for p in state['pops'].values():
        if not _num(p.get('count'), 0, 5e6) or not _num(p.get('employed'), 0, 5e6):
            raise SaveError('Invalid POP.')
    if len(state.get('events', {}).get('heap', [])) > LIMITS['heap']:
        raise SaveError('Too many queued events.')
    archive=state.get('archive',{})
    if not isinstance(archive,dict) or len(archive.get('selected',[]))>8 or len(archive.get('waveforms',[]))>8:
        raise SaveError('Invalid history archive.')
    for group,maxrows in (('hours',168),('days',30),('minutes',1440)):
        data=archive.get(group,{})
        if not isinstance(data,dict) or len(data)>10000 or any(not isinstance(rows,list) or len(rows)>maxrows for rows in data.values()):
            raise SaveError('Invalid history retention.')
    if not _num(state.get('minute'), 0, 525600*500) or not _num(state.get('seed'), 0, 2**31):
        raise SaveError('Invalid clock or seed.')
    return state


def _num(x, lo, hi):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x) and lo <= x <= hi
