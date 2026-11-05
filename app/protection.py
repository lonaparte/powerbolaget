"""Three-phase fault study and graded IEC 60255 standard-inverse overcurrent relays.

Pickup defaults 1.25 times continuous current, TMS=.08, breaker time=.06 s and
upstream grading=.30 s per protection zone. These are teaching assumptions.
"""
from collections import deque
from math import sqrt
from . import grid as G


# Independent severe-fault backup. This represents the distance/differential/undervoltage protection
# omitted from the first-release relay detail; it never substitutes prospective current for measured
# overcurrent progress. It operates only while the actual fault bus remains deeply depressed.
PERSISTENT_FAULT_BACKUP_S = 5.0
PERSISTENT_FAULT_V_PU = .5


def inverse_time(current,pickup,tms=.08):
    multiple=current/pickup if pickup>0 else 0.
    return .06+.14*tms/(multiple**.02-1.) if multiple>1 else None


def pickup(grid,br):
    if br['kind']=='line':
        rated=br['amps']
    else:
        rated=br['mva']*1000/(sqrt(3)*grid['buses'][br['b']]['kv'])
    return br.get('relay',{}).get('pickup_a',1.25*rated)


def study(world,br,resistance=.5):
    # Compile the same switched topology including the enabled forming source. Study context is
    # private: disabling loads for a short-circuit calculation must never alter the live circuit.
    network=G.Network(world.grid,world.devices,world.backend)
    network.compile()
    current,voltage=network.solver.short_circuit(br['b'],resistance)
    currents=network.solver.fault_branch_currents
    adjacency={}
    for bid,b in world.grid['branches'].items():
        if bid!=br['id'] and G.in_service(b):
            adjacency.setdefault(b['a'],[]).append((b['b'],bid))
            adjacency.setdefault(b['b'],[]).append((b['a'],bid))
    roots={world.grid['source_bus']}|{u['bus'] for u in G.forming_units(world.grid) if u.get('forming_active')}
    queue=deque([(br['a'],[])])
    seen={br['a']}
    path=[]
    while queue:
        node,path=queue.popleft()
        if node in roots:
            break
        for nxt,bid in sorted(adjacency.get(node,[])):
            if nxt not in seen:
                seen.add(nxt);queue.append((nxt,path+[bid]))
    candidates=[]
    for depth,bid in enumerate([br['id']]+path):
        b=world.grid['branches'][bid]
        relay=b.get('relay',{})
        if not relay.get('enabled',True):
            continue
        amps=currents.get(bid,0.)
        delay=inverse_time(amps,pickup(world.grid,b),relay.get('tms',.08))
        if delay is not None:
            candidates.append(dict(branch=bid,current_a=amps,pickup_a=pickup(world.grid,b),
                                   seconds=delay+depth*.30,role='primary' if depth==0 else 'backup',depth=depth))
    candidates.sort(key=lambda x:x['seconds'])
    return dict(fault_bus=br['b'],fault_branch=br['id'],current_a=current,voltage_pu=voltage,
                resistance_ohm=resistance,relays=candidates,selected=candidates[0] if candidates else None)


def add_ties(world):
    """Normally-open alternative 20 kV feeders in the synthetic opening distribution grid."""
    g=world.grid
    for br in list(g['branches'].values()):
        if not br.get('restorable') or br.get('transfer_tie'):
            continue
        node=g['buses'][br['b']]
        choices=[s for s in world.substations.values() if s['mv_bus']!=br['a']]
        if not choices:
            continue
        sub=min(choices,key=lambda s:(s['x']-node['x'])**2+(s['y']-node['y'])**2)
        tid='tie_'+br['id']
        G.add_line(g,tid,sub['mv_bus'],br['b'],'CAB20',name='Normally-open transfer '+br['id'],closed=False,
                   transfer_for=br['id'])
        br['transfer_tie']=tid


def transfer(world,br,t):
    tie=world.grid['branches'].get(br.get('transfer_tie'))
    if not tie or not G.in_service(dict(tie,closed=True)):
        return False,'alternative feeder is unavailable'
    old=set(world.network.energized)
    tie['closed']=True
    world.network.switch(tie['id'])
    try:
        network=G.Network(world.grid,world.devices,world.backend)
        network.compile()
        req=world.requests(t,world.weather_now)
        loads={k:pq if world.devices[k]['bus'] in network.energized else (0.,0.) for k,pq in req.items()}
        gens={k:(s['p'],s.get('q',0.)) if s['bus_lv'] in network.energized else (0.,0.) for k,s in world.grid['turbines'].items() if s['status']!='construction'}
        gens.update({u['id']:(0.,0.) if u.get('forming_active') else (u['p'],u.get('q',0.)) for u in G.forming_units(world.grid)})
        if world.grid['source_bus']=='mainland_ac':
            gens['hvdc_conv']=(world.hvdc_setpoint,0.)
        res=network.solve(loads,gens)
        low=min((res.bus_vm.get(k,0.) for k in network.energized-old),default=1.)
        amps=res.branches.get(tie['id'],(0.,0.,0.,0.,0.))[4]
        ok=res.converged and br['b'] in network.energized and low>=.9 and amps<=tie['amps']
        reason=f'minimum transferred voltage {low:.3f} pu, tie loading {amps/tie["amps"]:.1%}'
    except Exception as exc:
        ok,reason=False,'transfer study failed: '+str(exc)
    if not ok:
        tie['closed']=False
        world.network.switch(tie['id'])
    return ok,reason
