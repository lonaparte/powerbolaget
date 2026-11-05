"""Public pumping and potable-water storage, driven by people and tourism.

Teaching assumptions: resident use 0.12 m3/person/day, visitors 0.22, pumping 0.65 kWh/m3,
two design-days of storage, groundwater supply available at pump rating (drought deferred).
"""
from . import loads as L

KWH_M3=.65


def create(world):
    world.water={}
    for z in world.zones:
        design=.12*(z['start_residents']+2.8*z['holiday_homes'])+.22*z['beds']
        volume=max(20.,2*design)
        did='water_'+z['id']
        world.water[z['id']]=dict(device=did,capacity_m3=volume,volume_m3=.75*volume,
            initial_m3=.75*volume,pump_m3_h=max(2.,2*design/24),produced_m3=0.,delivered_m3=0.,
            spilled_m3=0.,unmet_m3=0.,day_demand=0.,day_delivered=0.,availability=1.)
        world.devices[did]=L.new_device(did,'water',('firm','p_'+z['id']),z['bus'],'critical',.92,p_target=0.)
        world.firms['p_'+z['id']]['devices'].append(did)
    targets(world)


def demand(world,zid):
    st=world.society_stats
    return (.12*sum(st[k].get(zid,0) for k in ('zone_residents','zone_holiday','zone_seasonal'))
            +.22*st['zone_tourists'].get(zid,0))/24


def targets(world):
    for zid,w in world.water.items():
        rate=max(0.,min(w['pump_m3_h'],demand(world,zid)+(.75*w['capacity_m3']-w['volume_m3'])/6.))
        world.devices[w['device']]['p_target']=rate*KWH_M3/1000


def integrate(world,hours):
    for zid,w in world.water.items():
        d=world.devices[w['device']]
        produced=d['p']*d['served']*hours*1000/KWH_M3
        requested=demand(world,zid)*hours
        delivered=min(requested,w['volume_m3']+produced)
        stock=w['volume_m3']+produced-delivered
        spilled=max(0.,stock-w['capacity_m3'])
        w['volume_m3']=min(w['capacity_m3'],max(0.,stock))
        w['produced_m3']+=produced;w['delivered_m3']+=delivered;w['spilled_m3']+=spilled
        w['unmet_m3']+=requested-delivered;w['day_demand']+=requested;w['day_delivered']+=delivered


def close_day(world):
    for w in world.water.values():
        w['availability']=w['day_delivered']/w['day_demand'] if w['day_demand'] else 1.
        w['day_demand']=w['day_delivered']=0.


def residual(w):
    return w['initial_m3']+w['produced_m3']-w['delivered_m3']-w['spilled_m3']-w['volume_m3']
