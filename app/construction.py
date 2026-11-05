"""Powerbolaget's construction projects: turbines, batteries, lines, transformers and link capacity.

A build command is checked (land, spacing, connection), priced and queued. Progress payments go out
monthly, partly to the island's construction firm and partly off-island. On completion the new
equipment is commissioned into world.grid and the power-flow model is rebuilt. Under the free-
investment rule a project is never refused for lack of money: the shortfall is booked as external
financing. Previews show cost, duration and the electrical connection; they do not promise that the
power flow will be feasible, which the solver checks after commissioning.
"""
from math import hypot
from . import grid as G
from . import land
from .island import TURBINE_MODELS, inside, zone_at
from .params import COST, DAYS, LOCAL_CONSTRUCTION_SHARE
from .calendar import DAY

HOME_DISTANCE = .5          # km from the nearest town or village parcel
CONNECT_RADIUS = 12.0       # km: farther sites need their own farm substation


class BuildError(ValueError):
    pass


def winter_factor(minute):
    from .calendar import parts
    doy = parts(minute)['doy']
    return 1.25 if doy < 75 or doy > 320 else 1.0


def plan_turbine(world, model, x, y):
    if model not in TURBINE_MODELS:
        raise BuildError('Unknown turbine model.')
    m = TURBINE_MODELS[model]
    if not inside(x, y):
        raise BuildError('Turbines are built on land.')
    cls = land.land_class(x, y)
    if cls in land.NO_TURBINES:
        raise BuildError(f'No turbines {land.NO_TURBINES[cls]}.')
    if land.homes_within(x, y, HOME_DISTANCE):
        raise BuildError(f'Closer than {HOME_DISTANCE*1000:.0f} m to homes.')
    for t in world.grid['turbines'].values():
        spacing = 3.5*max(m['rotor'], t['rotor'])/1000
        if hypot(t['x']-x, t['y']-y) < spacing:
            raise BuildError(f"Closer than {spacing:.2f} km to turbine {t['id'].upper()}.")
    grid = world.grid
    best = None
    for fid, farm in grid['farms'].items():
        nodes = [(farm['hub'], grid['buses'][farm['hub']])]
        nodes += [(grid['turbines'][t]['bus_mv'], grid['buses'][grid['turbines'][t]['bus_mv']]) for t in farm['turbines']]
        for bid, b in nodes:
            d = hypot(b['x']-x, b['y']-y)
            if d <= CONNECT_RADIUS and (best is None or d < best[2]):
                best = (fid, bid, d)
    cost = m['capex']
    days = m['days']
    plan = dict(kind='turbine', model=model, x=round(x, 3), y=round(y, 3), mw=m['mw'])
    if best:
        fid, bus, d = best
        km = round(max(.3, d*1.1), 2)
        cost += km*COST['collector_km']
        plan.update(farm=fid, connect_bus=bus, cable_km=km,
                    connection=f"33 kV cable {km:.1f} km to {grid['buses'][bus]['name']} ({grid['farms'][fid]['name']})")
    else:
        sub = min(world.substations.values(), key=lambda s: hypot(s['x']-x, s['y']-y))
        km = round(hypot(sub['x']-x, sub['y']-y)*1.15, 2)
        cost += COST['farm_substation']+km*G.LINE_TYPES['OHL110'][7]
        days = max(days, DAYS['farm_substation'])
        plan.update(farm=None, substation=sub['id'], line_km=km,
                    connection=f"new 110/33 kV farm substation and {km:.1f} km 110 kV line to {sub['name']}")
    zone = zone_at(x, y, world.zones)
    plan.update(cost=round(cost*1e6), days=round(days*winter_factor(world.minute)), zone=zone['id'],
                title=f"{model} wind turbine in {zone['name']}")
    return plan


def plan_storage(world, station, p_mw, hours, grid_forming):
    if station not in world.substations:
        raise BuildError('Unknown substation.')
    if not (1 <= p_mw <= 100) or not (.5 <= hours <= 8):
        raise BuildError('Battery size must be 1-100 MW and 0.5-8 hours.')
    e = p_mw*hours
    cost = (p_mw*COST['storage_mw']+e*COST['storage_mwh'])*(1+(COST['grid_forming_extra'] if grid_forming else 0))
    sub = world.substations[station]
    return dict(kind='storage', station=station, p_mw=p_mw, e_mwh=e, grid_forming=bool(grid_forming),
                cost=round(cost*1e6), days=DAYS['storage'], zone=zone_at(sub['x'], sub['y'], world.zones)['id'],
                title=f"{p_mw:g} MW / {e:g} MWh {'grid-forming ' if grid_forming else ''}battery at {sub['name']}",
                connection=f"20 kV bay at {sub['name']}")


def plan_line(world, a, b, ltype):
    subs = world.substations
    if a not in subs or b not in subs or a == b:
        raise BuildError('Choose two different substations.')
    if ltype not in ('OHL110', 'CAB110'):
        raise BuildError('New lines are 110 kV overhead lines or cables.')
    sa, sb = subs[a], subs[b]
    km = round(hypot(sa['x']-sb['x'], sa['y']-sb['y'])*1.15, 2)
    cost = km*G.LINE_TYPES[ltype][7]
    days = DAYS['line_ohl' if ltype == 'OHL110' else 'line_cable']
    return dict(kind='line', a=a, b=b, type=ltype, km=km, cost=round(cost*1e6), days=round(days*winter_factor(world.minute)),
                zone=zone_at(sa['x'], sa['y'], world.zones)['id'],
                title=f"{G.LINE_TYPES[ltype][8]} {sa['name']}–{sb['name']}", connection=f'{km:.1f} km')


def plan_transformer(world, station):
    if station not in world.substations:
        raise BuildError('Unknown substation.')
    sub = world.substations[station]
    return dict(kind='transformer', station=station, cost=round(COST['transformer_unit']*1e6), days=DAYS['transformer'],
                zone=zone_at(sub['x'], sub['y'], world.zones)['id'],
                title=f"40 MVA transformer unit at {sub['name']}", connection='110/20 kV, parallel unit')


PLANNERS = dict(turbine=plan_turbine, storage=plan_storage, line=plan_line, transformer=plan_transformer)


def start(world, plan):
    """Queue a checked plan as a project; turbines appear at once as construction sites."""
    pid = f"p{world.next_id('project')}"
    project = dict(id=pid, start=world.minute, finish=world.minute+plan['days']*DAY, paid=0., status='building', **plan)
    world.projects[pid] = project
    if plan['kind'] == 'turbine':
        add_turbine(world, plan, status='construction', project=pid)
    world.events.push(project['finish'], 'commission', 'commission', project=pid)
    world.log('construction', f"Construction started: {plan['title']} ({plan['days']} days, {plan['cost']/1e6:.0f} MSEK)",
              plan['zone'], project=pid)
    return project


def pay_progress(world, minute):
    """Monthly progress payments for every active project, and for firms' own expansions."""
    for p in world.projects.values():
        if p['status'] != 'building' or p.get('owner', 'pb') != 'pb':
            continue
        done = min(1., (minute-p['start'])/max(1, p['finish']-p['start']))
        due = p['cost']*done-p['paid']
        if due > 0:
            world.pay_construction('pb', due, minute, 'capex')
            p['paid'] += due


def commission(world, pid):
    p = world.projects[pid]
    p['status'] = 'done'
    due = p['cost']-p['paid']
    if due > 0:
        world.pay_construction('pb', due, world.minute, 'capex')
        p['paid'] = p['cost']
    grid = world.grid
    kind = p['kind']
    if kind == 'turbine':
        tid = p['turbine']
        t = grid['turbines'][tid]
        t['status'] = 'ok'
        t['built'] = world.minute
        t['maintained'] = world.minute
    elif kind == 'storage':
        add_storage(world, p)
    elif kind == 'line':
        sa, sb = world.substations[p['a']], world.substations[p['b']]
        bid = f"l_{p['a']}_{p['b']}_{pid}".lower()
        G.add_line(grid, bid, sa['hv_bus'], sb['hv_bus'], p['type'], km=p['km'], name=f"{sa['name']}–{sb['name']}")
    elif kind == 'transformer':
        sub = world.substations[p['station']]
        n = len(sub['transformers'])+1
        bid = f"t_{p['station']}_{n}".lower()
        G.add_transformer(grid, bid, sub['hv_bus'], sub['mv_bus'], '110/20', 40., name=f"{sub['name']} T{n}")
        sub['transformers'].append(bid)
    grid['version'] = grid.get('version', 0)+1
    if getattr(world, 'network', None):
        world.network.dirty = True
    world.log('construction', f"Commissioned: {p['title']}", p['zone'], project=pid)


def add_turbine(world, plan, status='ok', project=None, tid=None, age=0.):
    grid = world.grid
    m = TURBINE_MODELS[plan['model']]
    n = world.next_id('turbine')
    tid = tid or f'wt{n:03d}'
    x, y = plan['x'], plan['y']
    farm_id = plan.get('farm')
    if farm_id is None:
        farm_id = f'wf{world.next_id("farm")}'
        sub = world.substations[plan['substation']]
        hub = G.add_bus(grid, f'{farm_id}_33', f'{farm_id.upper()} collector', 33., x+.25, y+.25, 'collector')
        hv = G.add_bus(grid, f'{farm_id}_110', f'{farm_id.upper()} farm substation', 110., x+.25, y+.25, 'farm')
        G.add_transformer(grid, f'{farm_id}_tr', hv, hub, '110/33', 40., name=f'{farm_id.upper()} 110/33 kV')
        G.add_line(grid, f'{farm_id}_line', sub['hv_bus'], hv, 'OHL110', km=plan['line_km'], name=f"{sub['name']}–{farm_id.upper()}")
        grid['farms'][farm_id] = dict(id=farm_id, name=f'Vindpark {farm_id.upper()}', hub=hub, substation=sub['id'], turbines=[])
        plan['connect_bus'] = hub
        plan['cable_km'] = .3
        plan['farm'] = farm_id
    mv = G.add_bus(grid, f'{tid}_mv', f'{tid.upper()} 33 kV', 33., x, y, 'turbine')
    lv = G.add_bus(grid, f'{tid}_lv', f'{tid.upper()} 0.69 kV', .69, x, y, 'turbine')
    G.add_line(grid, f'{tid}_cable', plan['connect_bus'], mv, 'CAB33', km=plan['cable_km'], name=f'{tid.upper()} collector')
    G.add_transformer(grid, f'{tid}_tr', mv, lv, '33/0.69', round(m['mw']*1.12, 2), name=f'{tid.upper()} unit transformer')
    grid['turbines'][tid] = dict(id=tid, model=plan['model'], mw=m['mw'], rotor=m['rotor'], hub=m['hub'], x=x, y=y,
                                 farm=farm_id, bus_mv=mv, bus_lv=lv, status=status, age=age, maintained=world.minute,
                                 built=world.minute if status == 'ok' else None,
                                 grid_wait=0., v=0., p=0., energy_mwh=0., project=project)
    grid['farms'][farm_id]['turbines'].append(tid)
    grid['version'] = grid.get('version', 0)+1
    if project:
        world.projects[project]['turbine'] = tid
    if getattr(world, 'network', None):
        world.network.dirty = True
    return tid


def add_storage(world, p):
    grid = world.grid
    sub = world.substations[p['station']]
    sid = f"bess{world.next_id('storage')}"
    grid['storage'][sid] = dict(id=sid, name=f"Battery {sub['name']}", bus=sub['mv_bus'], station=p['station'],
                                p_mw=float(p['p_mw']), e_mwh=float(p['e_mwh']), soc=.5, eff=.92, mode='auto', setpoint=0.,
                                grid_forming=p['grid_forming'], forming_active=False, status='ok', p=0., x=sub['x']+.6,
                                y=sub['y']-.5, cycles_mwh=0.)
    grid['version'] = grid.get('version', 0)+1
    if getattr(world, 'network', None):
        world.network.dirty = True
    return sid
