"""Backup oil engines and converter capability, using explicit first-release assumptions.

Oil inventory is thermal MWh. Electricity = consumed fuel * efficiency; waste heat is counted.
Engine starts take ten minutes, minimum up/down times 30/15 minutes, ramp 20% rating/minute.
"""
from math import sqrt
from . import grid as G
from .construction import BuildError
from .island import zone_at

FUEL_PRICE = 950.  # SEK per thermal MWh, synthetic delivered oil price


def plan(world, station, p_mw, fuel_hours=48., connect_bus=None):
    from .engineering import bus
    bid = bus(world, connect_bus or station, 'mv_bus')
    node = world.grid['buses'][bid]
    if node['kv'] not in (20.,33.) or not .5 <= p_mw <= 100 or not 1 <= fuel_hours <= 720:
        raise BuildError('Oil backup requires a 20/33 kV bus, 0.5–100 MW and 1–720 fuel hours.')
    return dict(kind='oil',station=station,connect_bus=bid,p_mw=p_mw,fuel_hours=fuel_hours,
                cost=round((p_mw*12.+2.+p_mw*fuel_hours*.003)*1e6),days=360,
                zone=zone_at(node['x'],node['y'],world.zones)['id'],title=f'{p_mw:g} MW oil backup at {node["name"]}',
                connection='Synchronous black-start engine, 10 min start, 20% minimum output; fuel purchased separately')


def add(world, plan):
    bid = plan['connect_bus']
    node = world.grid['buses'][bid]
    gid = f"oil{world.next_id('oil')}"
    cap = plan['p_mw']*plan['fuel_hours']/.38
    world.grid.setdefault('oil',{})[gid] = dict(id=gid,name=f'Oil backup {gid}',bus=bid,p_mw=plan['p_mw'],
        fuel_capacity=cap,fuel_mwh=cap,eff=.38,fuel_used=0.,energy_mwh=0.,waste_heat_mwh=0.,
        state='off',status='ok',mode='auto',setpoint=plan['p_mw'],p=0.,q=0.,since=world.minute,
        last_step=world.minute,grid_forming=True,forming_active=False,black_start=True,auto_refuel=True,
        starts=0,x=node['x']+.5,y=node['y']+.5)
    world.ledger.transfer('pb','external',cap*FUEL_PRICE,'backup fuel inventory',world.minute,'oil',cap)
    plan['asset']=gid
    return gid


def step(world, now, requests, wind):
    from .energy import link_capacity
    need = sum(p for p,q in requests.values())*1.03-sum(wind.values())
    cap = link_capacity(world)*(1-world.settings['link_margin'])
    for g in world.grid.get('oil',{}).values():
        dt = max(0.,now-g['last_step'])
        g['last_step']=max(now,g['last_step'])
        if g['status']!='ok' or g['fuel_mwh']<=1e-6:
            g['p']=0.
            g['state']='off'
            continue
        want = g['mode']=='on' or (g['mode']=='auto' and (cap==0 or need>cap))
        elapsed = now-g['since']
        if want and g['state']=='off' and (g['starts']==0 or elapsed>=15):
            g.update(state='starting',since=now)
            g['starts']+=1
            world.ledger.transfer('pb','external',g['p_mw']*8000.,'backup start',now)
            world.log('operation',g['name']+' starting (10 minutes)',None,generator=g['id'])
        elif g['state']=='starting' and elapsed>=10:
            g.update(state='running',since=now)
        elif not want and g['state']=='running' and elapsed>=30:
            g.update(state='off',since=now,p=0.)
        if g['state']=='running':
            target = g['setpoint'] if g['mode']=='on' else max(0.,need-cap)
            target = min(g['p_mw'],max(.2*g['p_mw'],target),g['fuel_mwh']*g['eff']*60)
            ramp = .2*g['p_mw']*dt
            g['p']=max(0.,min(target,g['p']+ramp)) if target>=g['p'] else max(target,g['p']-ramp)
            need-=g['p']
        else:
            g['p']=0.


def integrate(world, hours, outputs):
    for gid,p in outputs.items():
        g=world.grid['oil'][gid]
        energy=max(0.,p)*hours
        fuel=energy/g['eff']
        g['fuel_mwh']=max(0.,g['fuel_mwh']-fuel)
        g['fuel_used']+=fuel
        g['energy_mwh']+=energy
        g['waste_heat_mwh']+=fuel-energy


def refuel(world, now):
    for g in world.grid.get('oil',{}).values():
        if g['status']!='ok' or not g['auto_refuel'] or g['fuel_mwh']>=.25*g['fuel_capacity']:
            continue
        qty=g['fuel_capacity']-g['fuel_mwh']
        world.ledger.transfer('pb','external',qty*FUEL_PRICE,'backup fuel purchase',now,'oil',qty)
        g['fuel_mwh']+=qty


def injection(asset, p, vm=1.):
    """P/Q circle and current capability. Positive Q raises voltage; no unlimited var source."""
    rating=asset.get('p_mw',asset.get('mw',0.))
    smax=1.1*rating*min(1.,max(0.,vm))
    p=max(-smax,min(smax,p))
    qmax=sqrt(max(0.,smax*smax-p*p))
    mode=asset.get('q_mode','voltage')
    q=(asset.get('q_setpoint',0.) if mode=='fixed' else (asset.get('v_setpoint',1.02)-vm)*rating*.5)
    return p,max(-qmax,min(qmax,q))


def age_storage(s, hours):
    nominal=s.setdefault('nominal_e_mwh',s['e_mwh'])
    s['age_hours']=s.get('age_hours',0.)+hours
    soh=max(0.,1.-.015*s['age_hours']/8760.-.2*s['cycles_mwh']/(2*nominal*6000.))
    stored=s['soc']*s['e_mwh']
    s['soh'],s['e_mwh']=soh,nominal*soh
    if s['e_mwh']>0:
        excess=max(0.,stored-s['e_mwh'])
        s['degradation_loss_mwh']=s.get('degradation_loss_mwh',0.)+excess
        s['soc']=min(1.,stored/s['e_mwh'])
    if soh<=.8:
        s['status']='retired'
