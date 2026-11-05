"""Editable engineering plans. Distances in km; costs SEK; durations calendar days.

The mainland connection envelope and costs are published synthetic assumptions, not an
operator's offer. A preview is advisory; every plan is revalidated before construction.
"""
from math import hypot, isfinite, ceil
from . import grid as G
from .island import inside, zone_at
from .construction import BuildError, winter_factor

LINK_LIMITS = dict(HVDC=640., HVAC=440.)


def bus(world, ref, side='hv_bus'):
    bid = world.substations.get(ref, {}).get(side, ref)
    if bid not in world.grid['buses']:
        raise BuildError('Choose an existing electrical bus or substation.')
    return bid


def route(world, a, b, points=None):
    """Endpoints are authoritative. Player waypoints change both electrical length and price."""
    coords = lambda bid: [world.grid['buses'][bid][k] for k in ('x', 'y')]
    start = coords(a) if isinstance(a, str) else list(a)
    end = coords(b) if isinstance(b, str) else list(b)
    if not points:
        return [start, end], max(.3, hypot(end[0]-start[0], end[1]-start[1])*1.15)
    if len(points) > 128 or len(points) < 2:
        raise BuildError('A route needs 2–128 points including its endpoints.')
    for p in points:
        if len(p) != 2 or any(not isinstance(v, (int, float)) or not isfinite(v) or not -100 <= v <= 250 for v in p):
            raise BuildError('Invalid route coordinates.')
    if hypot(points[0][0]-start[0], points[0][1]-start[1]) > .1 or hypot(points[-1][0]-end[0], points[-1][1]-end[1]) > .1:
        raise BuildError('Route endpoints must match the chosen buses within 100 m.')
    points = [start]+[list(p) for p in points[1:-1]]+[end]
    return points, max(.3, sum(hypot(q[0]-p[0], q[1]-p[1]) for p, q in zip(points, points[1:])))


def plan_line(world, a, b, ltype='OHL110', points=None):
    a, b = bus(world, a), bus(world, b)
    if a == b or ltype not in ('OHL110', 'CAB110', 'OHL20', 'CAB20', 'CAB33'):
        raise BuildError('Choose distinct buses and an available AC line type.')
    ga, gb = world.grid['buses'][a], world.grid['buses'][b]
    kv = 110 if '110' in ltype else 33 if '33' in ltype else 20
    if ga['kv'] != kv or gb['kv'] != kv:
        raise BuildError('Line voltage must match both buses; use a transformer between voltage levels.')
    path, km = route(world, a, b, points)
    if ltype.startswith('OHL'):
        for p, q in zip(path, path[1:]):
            n = max(1, ceil(hypot(q[0]-p[0], q[1]-p[1])*2))
            if any(not inside(p[0]+(q[0]-p[0])*i/n, p[1]+(q[1]-p[1])*i/n) for i in range(n+1)):
                raise BuildError('Overhead routes must remain on land; choose cable or edit waypoints.')
    return dict(kind='line', a_bus=a, b_bus=b, type=ltype, route=path, km=round(km, 3),
                cost=round(km*G.LINE_TYPES[ltype][7]*1e6), days=round((180 if ltype.startswith('OHL') else 240)*winter_factor(world.minute)),
                zone=zone_at(ga['x'], ga['y'], world.zones)['id'],
                title=f"{G.LINE_TYPES[ltype][8]} {ga['name']}–{gb['name']}", connection=f'{km:.2f} km, editable route')


def plan_station(world, x, y, mv_kv=20., mva=40., name=None):
    if not inside(x, y) or mv_kv not in (20., 33.) or not 5 <= mva <= 200:
        raise BuildError('A station needs a land site, 20 or 33 kV collector and 5–200 MVA transformer.')
    return dict(kind='station', x=x, y=y, mv_kv=mv_kv, mva=mva,
                name=(name or 'New substation')[:60], cost=round((20.+mva*.65)*1e6), days=360,
                zone=zone_at(x, y, world.zones)['id'], title=f'{name or "New substation"} · 110/{mv_kv:g} kV',
                connection='Independent 110 kV and collector buses; build the incoming line separately')


def plan_transformer(world, station, mva=40.):
    if station not in world.substations or not 5 <= mva <= 200:
        raise BuildError('Choose a substation and 5–200 MVA capacity.')
    sub = world.substations[station]
    kv = world.grid['buses'][sub['mv_bus']]['kv']
    return dict(kind='transformer', station=station, mva=mva, transformer_type=f'110/{kv:g}',
                cost=round((8.+mva*.45)*1e6), days=240, zone=zone_at(sub['x'], sub['y'], world.zones)['id'],
                title=f'{mva:g} MVA transformer at {sub["name"]}', connection=f'110/{kv:g} kV parallel unit')


def plan_link(world, technology, p_mw, station, points=None):
    technology = technology.upper()
    if technology not in LINK_LIMITS or not 50 <= p_mw <= LINK_LIMITS[technology]:
        raise BuildError('Mainland envelope: HVDC 50–640 MW; HVAC 50–440 MW total contracted capacity.')
    landing = bus(world, station)
    node = world.grid['buses'][landing]
    if node['kv'] != 110 or not inside(node['x'], node['y']):
        raise BuildError('Choose an island-side 110 kV landing bus.')
    existing = sum(p['mw'] for p in world.grid['link']['poles']) if technology == 'HVDC' else world.grid['hvac']['capacity']
    if p_mw <= existing:
        raise BuildError(f'New total capacity must exceed the existing {existing:g} MW.')
    if any(p['status'] == 'building' and p['kind'] == 'interconnector' for p in world.projects.values()):
        raise BuildError('Complete or cancel the active mainland connection project first.')
    mainland = world.grid['hvac']['mainland']
    path, km = route(world, mainland, landing, points)
    increment = p_mw-existing
    cost = (4.5e9 if technology == 'HVAC' and existing == 0 else 350e6)+increment*6e6+km*3e6
    return dict(kind='interconnector', technology=technology, p_mw=p_mw, landing=landing, route=path, sea_km=km,
                cost=round(cost), days=1460 if technology == 'HVAC' else 1095, zone=zone_at(node['x'], node['y'], world.zones)['id'],
                title=f'{technology} mainland connection · {p_mw:g} MW total',
                connection=f'Island bus {node["name"]}; mainland capacity agreement {LINK_LIMITS[technology]:g} MW maximum',
                assumptions='Synthetic mainland availability, price and construction schedule; no forced calendar commissioning')


def plan_asset(world, target, action):
    g = world.grid
    asset = g['turbines'].get(target) or g['storage'].get(target) or g['branches'].get(target)
    if not asset or target == 'hvdc' or asset.get('planned') or asset.get('retired') or asset.get('status') in ('retired','construction'):
        raise BuildError('Choose a commissioned island asset.')
    if action not in ('decommission', 'retrofit', 'maintenance'):
        raise BuildError('Unknown asset work.')
    if any(p['status']=='building' and p.get('target')==target for p in world.projects.values()):
        raise BuildError('This asset already has a work order.')
    if target in g['turbines']:
        node = g['buses'][asset['bus_lv']]
        rating = asset['mw']
    elif target in g['storage']:
        node = g['buses'][asset['bus']]
        rating = asset['p_mw']
    else:
        node = g['buses'][asset['b']]
        rating = asset['mva']
    # Public first-release planning coefficients; never described as real operator quotations.
    days, unit_cost = {'decommission':(30,.25), 'retrofit':(90,.8), 'maintenance':(2,.02)}[action]
    return dict(kind='asset_work', target=target, action=action, cost=round(rating*unit_cost*1e6), days=days,
                zone=zone_at(node['x'], node['y'], world.zones)['id'], title=f'{action.title()} {target}',
                connection='Asset unavailable during work; retrofit restores condition and increases rating 10%')


def isolate(world, target):
    g = world.grid
    if target in g['branches']:
        br = g['branches'][target]
        br['closed'] = False
    else:
        asset = g['turbines'].get(target) or g['storage'].get(target)
        asset['status'], asset['p'], asset['forming_active'] = 'maintenance', 0., False
    world.network.dirty = True


def finish_work(world, p):
    g, target = world.grid, p['target']
    asset = g['turbines'].get(target) or g['storage'].get(target) or g['branches'].get(target)
    retired = p['action'] == 'decommission'
    asset['retired'] = retired
    if target in g['branches']:
        asset['closed'] = not retired
        if p['action'] == 'retrofit':
            asset['mva'] *= 1.1
            if 'amps' in asset:
                asset['amps'] *= 1.1
                asset['rating_factor'] = asset.get('rating_factor',1.)*1.1
    else:
        asset['status'] = 'retired' if retired else 'ok'
        asset['maintained'] = world.minute
        if p['action'] == 'retrofit':
            if target in g['storage']:
                asset['e_mwh'] = asset.get('nominal_e_mwh', asset['e_mwh'])*1.1
                asset['nominal_e_mwh'], asset['soh'], asset['cycles_mwh'] = asset['e_mwh'], 1., 0.
            else:
                # Turbine model rating is unchanged: refurbishment restores availability/age.
                asset['age'] = 0.


def cancel_project(world, pid):
    p = world.projects.get(pid)
    if not p or p['status'] != 'building' or p.get('owner','pb') != 'pb':
        raise BuildError('Choose an active Powerbolaget project.')
    p['status'] = 'cancelled'
    world.events.cancel(lambda e: e.get('project') == pid)
    if p['kind'] == 'turbine':
        world.grid['turbines'][p['turbine']]['status'] = 'retired'
    if p['kind'] == 'asset_work':
        saved = p['before_work']
        asset = world.grid['branches'].get(p['target']) or world.grid['turbines'].get(p['target']) or world.grid['storage'].get(p['target'])
        asset.update(saved)
    world.network.dirty = True
    return p


def commission(world, p):
    g = world.grid
    if p['kind'] == 'asset_work':
        finish_work(world, p)
    elif p['kind'] == 'station':
        sid = f"sub{world.next_id('station')}"
        hv = G.add_bus(g, sid+'_110', p['name']+' 110 kV', 110., p['x'], p['y'], 'substation')
        mv = G.add_bus(g, sid+'_mv', p['name']+f" {p['mv_kv']:g} kV", p['mv_kv'], p['x'], p['y'], 'substation')
        tr = G.add_transformer(g, sid+'_t1', hv, mv, f"110/{p['mv_kv']:g}", p['mva'])
        world.substations[sid] = dict(id=sid, name=p['name'], x=p['x'], y=p['y'], hv_bus=hv, mv_bus=mv, transformers=[tr])
        p['asset'] = sid
    elif p['kind'] == 'interconnector':
        if p['technology'] == 'HVDC':
            link = g['link']
            total = sum(x['mw'] for x in link['poles'])
            link['poles'].append(dict(id=f"pole{len(link['poles'])+1}", mw=p['p_mw']-total, status='ok', repair_until=None))
            link['bus'] = p['landing']
            g['branches']['hvdc']['b'] = p['landing']
        else:
            ac = g['hvac']
            ac['capacity'] = p['p_mw']
            count = ceil(p['p_mw']/ac['cable_mw'])
            for i, bid in enumerate(ac['cables']):
                g['branches'][bid]['planned'] = i >= count
                g['branches'][bid]['km'] = p['sea_km']
                g['branches'][bid]['route'] = p['route']
            g['branches'][ac['transformer']]['planned'] = False
            primary = ac['links'][0]
            g['branches'][primary]['b'] = p['landing']
            g['branches'][primary]['km'] = G.length(g, g['branches'][primary]['a'], p['landing'])
            g['branches'][primary]['planned'] = False
            for bid in ac['links'][1:]:
                g['branches'][bid]['planned'] = True
            ac['player_project'] = p['id']
        g[p['technology'].lower()+'_contract'] = dict(capacity=p['p_mw'], landing=p['landing'], route=p['route'])
    else:
        raise BuildError('Unknown engineering project.')
