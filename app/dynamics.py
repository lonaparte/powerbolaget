"""Sub-second event clock and aggregated RMS control of the native AC network.

All turbine branches remain in the algebraic network; farm frequency response is shared.
Source swing/governor/voltage equations live behind the solver boundary. No drawn response curve
is substituted for a network solve. Numerical failures are retained as failed event studies.
"""
from math import hypot, pi
from . import grid as G
from . import energy as N
from .solvers.rms import advance

STEP_S=.02
WINDOW_S=10.
FIELDS=[['seconds','s'],['frequency_hz','Hz'],['min_voltage_pu','pu'],['served_mw','MW'],
        ['wind_mw','MW'],['storage_mw','MW'],['oil_mw','MW'],['link_mw','MW'],['loss_mw','MW']]
OBJECT_FIELDS=[['seconds','s'],['p_mw','MW'],['q_mvar','Mvar'],['voltage_pu','pu'],['loading','pu'],['soc','pu']]


def active(world,t=None):
    return bool(world.rms.get('active')) and (t is None or t<=world.rms['end']+1e-9)


def sources(world):
    found={}
    if world.grid['source_bus']=='mainland' and N.hvdc_capacity(world)>0:
        found['source']=dict(bus=world.grid['link']['bus'],rating=N.hvdc_capacity(world),
            inertia=1.5,governor_s=.05,droop=.05,voltage_s=.10,voltage_ref=1.03,base_mvasc=G.SOURCE_MVASC,converter=True)
    for u in G.forming_units(world.grid):
        if not u.get('forming_active'):
            continue
        oil=u['id'] in world.grid.get('oil',{})
        found[u['id']+'_gf']=dict(bus=u['bus'],rating=u['p_mw'],inertia=3. if oil else 1.5,
            governor_s=.5 if oil else .05,droop=.05,voltage_s=.15 if oil else .10,
            voltage_ref=1.02,base_mvasc=max(20. if oil else 50.,(5 if oil else 20)*u['p_mw']),
            converter=not oil,pmin=.2 if oil else -1.)
    return found


def pq(world,name):
    f=world.flows or {}
    if name=='source':
        return f.get('link_dc',0.),f.get('link_q',0.)
    key=name[:-3]
    u=world.grid['storage'].get(key) or world.grid.get('oil',{}).get(key,{})
    p=f.get('storage',{}).get(key,f.get('oil',{}).get(key,0.))
    return p,u.get('q',0.)


def start(world,t,cause):
    if active(world,t):
        world.rms['end']=max(world.rms['end'],t+WINDOW_S/60)
        return
    key=f'rms{world.next_id("rms")}'
    world.rms=dict(active=True,id=key,start=t,end=t+WINDOW_S/60,last=t,states={},shed_stages=[])
    window=dict(id=key,t=t,cause=cause,model='aggregated positive-sequence RMS / AC algebraic network',
                step_seconds=STEP_S,fields=FIELDS,samples=[],actions=[],status='running',object_fields=OBJECT_FIELDS,object_samples={})
    world.archive.waveforms.append(window)
    prepare(world,t)
    world.events.push(t+STEP_S/60,'rms_step','protection')


def window(world):
    return next((w for w in reversed(world.archive.waveforms) if w['id']==world.rms.get('id')),None)


def prepare(world,t):
    if not active(world,t):
        world.network.reference_overrides={}
        return
    current=sources(world)
    states=world.rms['states']
    refs={}
    for name,c in current.items():
        p,q=pq(world,name)
        if name not in states:
            angle=(world.flows or {}).get('va',{}).get(c['bus'],0.)*pi/180
            states[name]=dict(y=[angle,world.frequency_hz-50 if world.frequency_hz>0 else 0.,p/c['rating'],c['voltage_ref']],
                              factor=1.,rating=c['rating'])
        s=states[name]
        if s['rating']!=c['rating']:
            s['y'][2]*=s['rating']/c['rating'];s['rating']=c['rating']
        refs[name]=(s['y'][3],s['y'][0]*180/pi,c['base_mvasc']/s['factor'])
    world.network.reference_overrides=refs


def step(world,t):
    if not active(world):
        return
    if t>world.rms['end']+1e-9:
        finish(world)
        return
    dt=max(0.,(t-world.rms['last'])*60)
    world.rms['last']=t
    weighted=weight=0.
    for name,c in sources(world).items():
        if name not in world.rms['states']:
            prepare(world,t)
        s=world.rms['states'][name]
        p,q=pq(world,name)
        voltage=(world.flows or {}).get('vm',{}).get(c['bus'],1.)
        s['y']=advance(s['y'],p/c['rating'],q/c['rating'],voltage,p/c['rating'],c,dt)
        if c['converter']:
            current=hypot(p,q)/(c['rating']*max(.05,voltage))
            if current>1.2:
                s['factor']=min(50.,s['factor']*min(2.,current/1.2))
            else:
                s['factor']=max(1.,s['factor']*.90)
        weighted+=(50+s['y'][1])*c['rating'];weight+=c['rating']
    if G.hvac_active(world.grid):
        world.frequency_hz=50.
    else:
        world.frequency_hz=weighted/weight if weight else 0.
    if weight:
        for threshold,share in ((48.8,.10),(48.2,.25),(47.5,.45)):
            if world.frequency_hz<threshold and threshold not in world.rms['shed_stages']:
                world.rms['shed_stages'].append(threshold)
                world.settings['frequency_shed']=max(world.settings.get('frequency_shed',0.),share)
                world.log('protection',f'Underfrequency stage {threshold:g} Hz: {share:.0%} load shed by priority',None)
    prepare(world,t)
    world.events.push(t+STEP_S/60,'rms_step','protection')


def record(world,t):
    if not active(world,t):
        return
    w=window(world)
    if w is None:
        return
    f=world.flows or {}
    voltages=[v for b,v in f.get('vm',{}).items() if b in world.network.energized and world.grid['buses'][b]['kind']!='mainland']
    sample=[(t-world.rms['start'])*60,world.frequency_hz,min(voltages,default=0.),
            sum(p*s for p,s in f.get('dev',{}).values()),sum(f.get('turb',{}).values()),
            sum(f.get('storage',{}).values()),sum(f.get('oil',{}).values()),f.get('link',0.),f.get('losses',0.)]
    if not w['samples'] or sample[0]>w['samples'][-1][0]+1e-9:
        w['samples'].append([round(v,7) for v in sample])
        keys=list(world.archive.selected)+[n[:-3] if n.endswith('_gf') else world.grid['link']['bus'] for n in sources(world)]
        if w['cause'].startswith('branch fault '):
            keys.append(w['cause'][13:])
        for key in list(dict.fromkeys(keys))[:12]:
            p=q=loading=soc=0.;bus=key;g=world.grid
            if key in world.devices:
                d=world.devices[key];p=d['p']*d['served'];q=d['q']*d['served'];bus=d['bus']
            elif key in g['branches']:
                b=g['branches'][key];x=f.get('branches',{}).get(key,(0.,0.,0.,0.,0.));p,q=x[:2]
                loading=f.get('loading',{}).get(key,0.);bus=b['b']
            elif key in g['turbines']:
                a=g['turbines'][key];p=a['p'];q=a.get('q',0.);bus=a['bus_lv']
            elif key in g['storage'] or key in g.get('oil',{}):
                a=g['storage'].get(key) or g['oil'][key]
                p=f.get('storage',{}).get(key,f.get('oil',{}).get(key,0.));q=a.get('q',0.);soc=a.get('soc',0.);bus=a['bus']
            elif key==g['link']['bus']:
                p=f.get('link_dc',0.);q=f.get('link_q',0.)
            w['object_samples'].setdefault(key,[]).append([round(v,7) for v in (sample[0],p,q,f.get('vm',{}).get(bus,0.),loading,soc)])


def finish(world,status='complete'):
    w=window(world)
    if w:
        w['status']=status
        w['final_frequency_hz']=world.frequency_hz
        w['remaining_faults']=[k for k,b in world.grid['branches'].items() if b.get('active_fault')]
    world.rms['active']=False
    world.network.reference_overrides={}
    if status=='numerical_failure':
        world.network.dirty=True
    if world.settings.get('frequency_shed'):
        world.events.push(world.t_now+1,'load_recovery','restore')
