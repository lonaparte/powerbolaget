"""Validated user-owned wind-farm graphs; the same graph builds the AC network."""
from copy import deepcopy
from math import isfinite
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from .parameters import TURBINES, TURBINE, INITIAL_TURBINES
from .errors import RuleError


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class Node(StrictModel):
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,11}$')
    kind:Literal['substation','turbine','junction']
    x_m:float=Field(ge=-20000,le=20000)
    y_m:float=Field(ge=-20000,le=20000)
    rated_mw:float=Field(default=5,ge=.5,le=15)
    rotor_m:float=Field(default=126,ge=40,le=260)
    hub_m:float=Field(default=90,ge=40,le=200)
    cut_in:float=Field(default=3,ge=1,le=6)
    rated_speed:float=Field(default=11.4,ge=7,le=18)
    cut_out:float=Field(default=25,ge=20,le=35)
    transformer_mva:float=Field(default=5.5,ge=.5,le=25)
    transformer_x_pct:float=Field(default=6,ge=2,le=15)

    @model_validator(mode='after')
    def curve(self):
        if self.kind=='turbine':
            if not self.cut_in<self.rated_speed<self.cut_out:raise ValueError('Wind speeds must satisfy cut-in < rated < cut-out')
            if self.transformer_mva<self.rated_mw:raise ValueError('Unit transformer MVA must be at least rated MW')
        return self


class Edge(StrictModel):
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,11}$')
    source:str=Field(max_length=12)
    target:str=Field(max_length=12)
    length_km:float=Field(ge=.05,le=50)
    r_ohm_km:float=Field(default=.12,ge=.005,le=1.)
    x_ohm_km:float=Field(default=.10,ge=.01,le=.8)
    c_nf_km:float=Field(default=200,ge=0,le=500)
    amps:float=Field(default=300,ge=50,le=1500)
    closed:bool=True


class Resources(StrictModel):
    foundation_vessels:int=Field(default=1,ge=1,le=4)
    installation_vessels:int=Field(default=1,ge=1,le=4)
    cable_vessels:int=Field(default=1,ge=1,le=4)
    engineering_teams:int=Field(default=1,ge=1,le=4)
    electrical_teams:int=Field(default=1,ge=1,le=4)
    supply_lines:int=Field(default=1,ge=1,le=4)
    port_distance_km:float=Field(default=30,ge=1,le=200)
    water_depth_m:float=Field(default=25,ge=5,le=60)


class Plan(StrictModel):
    name:str=Field(min_length=1,max_length=32)
    resources:Resources=Field(default_factory=Resources)
    collector_kv:Literal[35,66]=35
    transformer_mva:float=Field(default=31.5,ge=2,le=200)
    transformer_x_pct:float=Field(default=8,ge=2,le=20)
    storage_power_mw:float=Field(default=0,ge=0,le=30)
    storage_capacity_mwh:float=Field(default=0,ge=0,le=240)
    nodes:list[Node]=Field(min_length=1,max_length=41)
    edges:list[Edge]=Field(default_factory=list,max_length=80)

    @model_validator(mode='after')
    def safe_ids(self):
        ids=[n.id.lower() for n in self.nodes]
        if len(ids)!=len(set(ids)):raise ValueError('Node IDs must be unique (case-insensitive)')
        if sum(n.kind=='substation' for n in self.nodes)!=1:raise ValueError('A plant requires exactly one substation')
        if sum(n.kind=='turbine' for n in self.nodes)>24:raise ValueError('At most 24 turbines per plant')
        edge_ids=[e.id.lower() for e in self.edges]
        if len(edge_ids)!=len(set(edge_ids)):raise ValueError('Cable IDs must be unique')
        exact={n.id for n in self.nodes}
        if any(e.source not in exact or e.target not in exact for e in self.edges):raise ValueError('Cable endpoint references a missing node')
        if any(e.source==e.target for e in self.edges):raise ValueError('A cable cannot connect a node to itself')
        if (self.storage_power_mw==0)!=(self.storage_capacity_mwh==0):raise ValueError('Storage power and energy must both be zero or both positive')
        return self


def normalize(plan):
    try:return Plan.model_validate(plan).model_dump()
    except ValidationError as exc:
        errors=['.'.join(map(str,e['loc']))+': '+e['msg'].removeprefix('Value error, ') for e in exc.errors()[:5]]
        raise RuleError('Invalid planning parameters: '+'; '.join(errors)) from exc


def reachable(plan):
    root=next(n['id'] for n in plan['nodes'] if n['kind']=='substation')
    visited={root}; changed=True
    while changed:
        changed=False
        for e in plan['edges']:
            if not e['closed']:continue
            if e['source'] in visited or e['target'] in visited:
                old=len(visited); visited.update([e['source'],e['target']]);changed|=len(visited)>old
    return visited


def audit(plan):
    p=normalize(plan);linked=reachable(p);units=[n for n in p['nodes'] if n['kind']=='turbine']
    errors=[];warnings=[]
    if not units:errors.append('Add at least one turbine.')
    missing=[n['id'] for n in p['nodes'] if n['id'] not in linked]
    if missing:errors.append('No closed path to the substation: '+', '.join(missing))
    mw=sum(n['rated_mw'] for n in units)
    if mw>120:errors.append('Maximum capacity per farm: 120 MW.')
    if p['transformer_mva']<mw*1.05:warnings.append('Site transformer is below 1.05 times installed MW; curtailment may be required.')
    for i,a in enumerate(units):
        for b in units[i+1:]:
            distance=((a['x_m']-b['x_m'])**2+(a['y_m']-b['y_m'])**2)**.5
            if distance<max(a['rotor_m'],b['rotor_m'])*3:
                warnings.append(f"{a['id']} and {b['id']} spacing is below 3D; check wakes and layout.")
    if sum(e['closed'] for e in p['edges'])>=len(p['nodes']):warnings.append('Ring or parallel paths detected. Power flow uses this topology; directional protection coordination requires a separate design.')
    cost=round(mw*7_000_000+sum(e['length_km'] for e in p['edges'])*900_000+p['transformer_mva']*180_000+
               p['storage_power_mw']*800_000+p['storage_capacity_mwh']*1_100_000+2_000_000)
    return dict(plan=p,errors=errors,warnings=list(dict.fromkeys(warnings))[:20],turbine_count=len(units),capacity_mw=mw,
                cable_km=sum(e['length_km'] for e in p['edges']),cost=cost,
                topology='Ring / multiple paths' if sum(e['closed'] for e in p['edges'])>=len(p['nodes']) else 'Radial / tree')


def default_plan():
    nodes=[dict(id='S',kind='substation',x_m=0,y_m=0)]
    edges=[]
    for i in range(4):
        nid=f'T{i+1:02}'
        nodes.append(dict(id=nid,kind='turbine',x_m=(i%2)*900+800,y_m=(i//2)*800-400))
        edges.append(dict(id=f'L{i+1:02}',source='S' if i%2==0 else f'T{i:02}',target=nid,length_km=1.5 if i%2==0 else .9))
    return normalize(dict(name='East Bay Offshore Wind Farm',nodes=nodes,edges=edges))


def fleet(game):
    units=[dict(**TURBINE,**t,farm_id='base',breaker='collector_'+t['string'],transformer_mva=5.5,transformer_x_pct=6) for t in TURBINES]
    for plant in game.get('plants',[]):
        for n in plant['plan']['nodes']:
            if n['kind']=='turbine':
                t=deepcopy(n);t['local_id']=t['id'];t['id']=plant['id']+'_'+t['id']
                t.update(farm_id=plant['id'],farm_name=plant['name'],breaker='plant_'+plant['id'],rho_ref=1.225,
                         restart_speed=min(20.,t['cut_out']-3),restart_steps=2)
                units.append(t)
    return units


def installed(game,index):return index>=len(TURBINES) or index in INITIAL_TURBINES or 'wind_phase2' in game['upgrades']


def enabled(game,unit):
    return game['breakers']['pcc'] and game['breakers'].get(unit['breaker'],False) and (unit['farm_id']!='base' or game['breakers']['farm'])


def commission(game,project):
    game.setdefault('plants',[]).append(deepcopy(project))
    game['breakers']['plant_'+project['id']]=True
    for n in project['plan']['nodes']:
        if n['kind']=='turbine':game['turbines'].append(dict(maintenance=False,storm_lock=False,restart_count=0))
    added=project['plan']['storage_capacity_mwh']*.15
    game['battery']['energy_mwh']+=added
    game['totals']['import_mwh']+=added/.96
    game['totals']['battery_loss_mwh']+=added/.96-added
    game['cash']-=added/.96*650
