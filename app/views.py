"""What the client sees: one world state, three views (island map, grid analysis, socio-economics).

static() changes only when the grid or the firm list changes; snapshot() is sent with every tick;
entity() and table() answer the inspector and the statistics pages on demand. Values are rounded
for transport, never recomputed differently from the model.
"""
from math import isfinite
from . import grid as G
from . import energy as N
from . import weather as W
from .calendar import ERA, MONTHS, WEEKDAYS, is_rest_day, label, parts
from .island import ISLET, MAINLAND, NAME, OUTLINE, TURBINE_MODELS
from .params import COST, DAYS, GOODS, HOUSEHOLD_SIZE, SECTORS
from . import __version__


def r(x, n=3):
    return round(x, n) if isinstance(x, (int, float)) and isfinite(x) else None


def static(world):
    grid = world.grid
    return dict(
        version=__version__, seed=world.seed, grid_version=grid['version'], firm_count=len(world.firms),
        island=dict(name=NAME, outline=OUTLINE, islet=ISLET, mainland=list(MAINLAND), era=ERA),
        zones=[dict(id=z['id'], name=z['name'], x=z['x'], y=z['y'], kind=z['kind'], bus=z['bus'], beds=z['beds'],
                    holiday_homes=z['holiday_homes'], amenity=z['amenity'], town=z.get('town', 0)) for z in world.zones],
        buses={b['id']: [b['name'], b['kv'], b['x'], b['y'], b['kind']] for b in grid['buses'].values()},
        routes={b['id']: b['route'] for b in grid['branches'].values() if b.get('route')},
        branches={b['id']: [b['a'], b['b'], b['kind'], b['type'], b.get('km', 0.), b.get('circuits', 1), r(b['mva'], 1),
                            b.get('name', b['id'])] for b in grid['branches'].values()},
        turbines={t['id']: [t['model'], t['x'], t['y'], t['farm'], t['mw'], t['rotor'], t['hub']] for t in grid['turbines'].values()},
        farms={f['id']: [f['name'], f['hub'], f['substation']] for f in grid['farms'].values()},
        substations={s['id']: [s['name'], s['x'], s['y'], s['hv_bus'], s['mv_bus'], s['transformers']] for s in world.substations.values()},
        storage={s['id']: [s['name'], s['station'], s['x'], s['y'], s['p_mw'], s['e_mwh'], s['grid_forming']] for s in grid['storage'].values()},
        link=dict(bus=grid['link']['bus'], x=grid['link']['x'], y=grid['link']['y'], poles=[[p['id'], p.get('name', p['id']), p['mw']] for p in grid['link']['poles']]),
        hvac=dict(name=grid['hvac']['name'], station=grid['hvac']['station'], mainland=grid['hvac']['mainland'], cables=grid['hvac']['cables'],
                  stages=[dict(date=label(st['minute']).rsplit(' · ', 1)[0], cables=st['cables'], mw=st['mw']) for st in grid['hvac']['stages']]),
        firms={f['id']: [f['name'], f['kind'], f['sector'], f['zone'], f['bus']] for f in world.firms.values()},
        catalog=dict(turbines=TURBINE_MODELS, lines={k: [v[8], v[7], v[6]] for k, v in G.LINE_TYPES.items() if k in ('OHL110', 'CAB110', 'OHL20', 'CAB20', 'CAB33')},
                     costs=COST, days=DAYS, goods={g: [u, p] for g, (u, p, _, _) in GOODS.items()}),
    )


def snapshot(world, since_log=0):
    f = world.flows or {}
    grid = world.grid
    p = parts(world.minute)
    w = W.instant(world.seed, world.minute/1440)
    energized = world.network.energized
    load = sum(x*s for x, s in f.get('dev', {}).values())
    req = sum(x for x, _ in f.get('dev', {}).values())
    wind = sum(f.get('turb', {}).values())
    storage = f.get('storage', {})
    zones = {}
    zl = {z['id']: [0., 0.] for z in world.zones}
    for did, (pw, srv) in f.get('dev', {}).items():
        d = world.devices[did]
        zone = d['owner'][1] if d['owner'][0] == 'zone' else world.firms[d['owner'][1]]['zone']
        zl[zone][0] += pw
        zl[zone][1] += pw*(1-srv)
    st = world.society_stats
    for z in world.zones:
        res = world.devices['res_'+z['id']]
        zones[z['id']] = [st['zone_residents'].get(z['id'], 0), st['zone_tourists'].get(z['id'], 0),
                          st['zone_holiday'].get(z['id'], 0), st['zone_unemployed'].get(z['id'], 0),
                          st['zone_working'].get(z['id'], 0), r(zl[z['id']][0]), r(zl[z['id']][1]), r(res['t_in'], 2),
                          r(world.zone_outage_hours(z['id'], 30), 2), z['bus'] in energized]
    led = world.ledger
    hist = list(world.history_hour)
    return dict(
        minute=world.minute, label=label(world.minute), year=p['year'], month=MONTHS[p['month']-1], day=p['day'],
        hour=p['hour'], minute_of_hour=p['minute'], weekday=WEEKDAYS[p['weekday']], rest=is_rest_day(world.minute),
        weather=dict(wind=r(w['wind_10m_ms'], 2), ratio=r(w['wind_ratio'], 4), dir=r(w['direction_deg'], 0), temp=r(w['temperature_c'], 1),
                     cloud=r(w['cloud_fraction'], 2), sun=r(w['irradiance_w_m2'], 0), rh=r(w['humidity_pct'], 0),
                     sunrise=r(w['sunrise_hour'], 2), sunset=r(w['sunset_hour'], 2), elev=r(w['sun_elevation_deg'], 2), snow=r(W.snow_cover(world.seed, world.minute/1440), 2), thunder=r(w['thunder_risk'], 2),
                     icing=r(w['icing_risk'], 2)),
        totals=dict(load=r(load), requested=r(req), unserved=r(req-load), wind=r(wind), wind_avail=r(f.get('wind_avail', wind)),
                    link=r(f.get('link', 0.)), link_cap=r(N.link_capacity(world), 1), link_dc=r(f.get('link_dc', f.get('link', 0.))),
                    link_ac=r(f.get('link_ac', 0.)), cap_dc=r(N.hvdc_capacity(world), 1), cap_ac=r(N.hvac_capacity(world), 1),
                    reference='AC mainland' if grid['source_bus'] == 'mainland_ac' else 'HVDC converter', battery=r(sum(storage.values())),
                    losses=r(f.get('losses', 0.)), price=r(world.energy_price(world.minute), 3),
                    tariff=r(world.tariff('household', world.minute), 3), energized=len(energized), buses=len(grid['buses'])),
        buses={b: [r(f.get('vm', {}).get(b, 0.), 4), r(f.get('va', {}).get(b, 0.), 2), b in energized] for b in grid['buses']},
        branches={b: branch_state(world, b, br, f) for b, br in grid['branches'].items()},
        turbines={t: [r(tb['p']), tb['status'] if tb['status'] != 'ok' else ('waiting' if tb['grid_wait'] > world.minute else
                     'high wind' if tb.get('high_wind') else 'ok'), r(tb.get('v', 0.), 2)] for t, tb in grid['turbines'].items()},
        storage={s: [r(storage.get(s, 0.)), r(x['soc'], 3), x['status'], x['mode'], bool(x.get('forming_active'))]
                 for s, x in grid['storage'].items()},
        link=[[p_['id'], p_['mw'], p_['status']] for p_ in grid['link']['poles']],
        zones=zones,
        firms={fid: [x['status'], x['staff'], x['desired_staff'], r(firm_power(world, x), 3), r(x['ema_util'], 2),
                     r(led.balance('firm:'+fid)/1e6, 2)] for fid, x in world.firms.items()},
        kpi=dict(residents=sum(st['zone_residents'].values()), tourists=sum(st['zone_tourists'].values()),
                 holiday=sum(st['zone_holiday'].values()), unemployed=sum(st['zone_unemployed'].values()),
                 labour=sum(st['zone_working'].values()), pb_cash=r(led.balance('pb')/1e6, 2),
                 financing=r(-led.balance('financing')/1e6, 2), pops=len(world.pops), firms=len(world.firms)),
        projects=[project_view(world, x) for x in world.projects.values() if x['status'] == 'building'],
        logs=[e for e in world.logbook if e['id'] > since_log][-60:],
        series=list(world.minute_series)[-240:],
        perf=perf(world), grid_version=grid['version'], firm_count=len(world.firms),
        last_hour=hist[-1] if hist else None,
    )


def branch_state(world, bid, br, f):
    flow = f.get('branches', {}).get(bid)
    loading = f.get('loading', {}).get(bid, 0.)
    if br.get('planned'):
        return [0., 0., 0., 'planned']
    status = 'ok' if G.in_service(br) else ('open' if not br['closed'] else 'repair' if br['repair_until'] is not None else 'tripped')
    if status == 'ok' and br['a'] not in world.network.energized:
        status = 'dead'
    return [r(flow[0]) if flow else 0., r(flow[1]) if flow else 0., r(loading, 3), status]


def firm_power(world, f):
    total = 0.
    for did in f['equipment']+f['devices']:
        d = world.devices[did]
        total += d['p']*d['served']
    return total


def project_view(world, p):
    span = max(1, p['finish']-p['start'])
    return dict(id=p['id'], kind=p['kind'], status=p['status'], title=p['title'], zone=p.get('zone'), progress=r(min(1., (world.minute-p['start'])/span), 3),
                finish=label(p['finish']), cost=r(p['cost']/1e6, 1), paid=r(p['paid']/1e6, 1), owner=p.get('owner', 'pb'))


def perf(world):
    steps = sorted(world.perf['step_ms'])
    solves = sorted(world.perf['solve_ms'])
    pick = lambda xs, q: r(xs[min(len(xs)-1, int(q*len(xs)))], 2) if xs else None
    return dict(step_p50=pick(steps, .5), step_p95=pick(steps, .95), solve_p50=pick(solves, .5), solve_p95=pick(solves, .95),
                ms_per_sim_hour=r(sum(steps)/len(steps)*60, 1) if steps else None, failures=world.perf['failures'],
                minutes=world.perf['minutes'])


# ---------------------------------------------------------------- inspector
def entity(world, eid):
    grid, f = world.grid, world.flows or {}
    hist = world.entity_hist
    if eid in grid['turbines']:
        t = grid['turbines'][eid]
        model = TURBINE_MODELS[t['model']]
        return dict(type='turbine', id=eid, title=f"{eid.upper()} · {t['model']}", model=t['model'], mw=t['mw'], rotor=t['rotor'],
                    hub=t['hub'], farm=grid['farms'][t['farm']]['name'], status=t['status'], p=r(t['p']), hub_wind=r(t.get('v', 0.), 2),
                    age=r(t['age'] + (world.minute/525600), 1), maintained=label(t['maintained']) if t['maintained'] >= 0 else 'before FE 1',
                    bus_v=r(f.get('vm', {}).get(t['bus_lv'], 0.), 4), cut_in=model['cut_in'], rated_speed=model['rated_speed'],
                    cut_out=model['cut_out'], x=t['x'], y=t['y'], history=list(hist.get(eid, [])), unit='MWh per hour',
                    actions=['maintenance'])
    if eid in grid['branches']:
        br = grid['branches'][eid]
        flow = f.get('branches', {}).get(eid)
        return dict(type='branch', id=eid, title=br.get('name', eid), kind=br['kind'], line_type=br['type'],
                    label=G.LINE_TYPES[br['type']][8] if br['kind'] == 'line' else f"{br['type']} kV transformer",
                    a=grid['buses'][br['a']]['name'], b=grid['buses'][br['b']]['name'], km=br.get('km'), circuits=br.get('circuits', 1),
                    rating_mva=br['mva'], amps=br.get('amps'), tap=br.get('tap', 1.0) if br['kind'] == 'transformer' else None,
                    flow=[r(x) for x in flow] if flow else None, loading=r(f.get('loading', {}).get(eid, 0.), 3),
                    status=branch_state(world, eid, br, f)[3], fault=br.get('fault'),
                    repair_until=label(br['repair_until']) if br['repair_until'] is not None else None,
                    section_out=br.get('section_out'),
                    history=list(hist.get(eid, [])), unit='loading (1 = rating)', actions=['switch'] if eid != 'hvdc' else [])
    if eid in grid['buses']:
        b = grid['buses'][eid]
        devices = [d for d in world.devices.values() if d['bus'] == eid]
        return dict(type='bus', id=eid, title=b['name'], kv=b['kv'], v=r(f.get('vm', {}).get(eid, 0.), 4),
                    angle=r(f.get('va', {}).get(eid, 0.), 2), energized=eid in world.network.energized,
                    loads=[dict(id=d['id'], kind=d['kind'], p=r(d['p']), served=r(d['served'], 3), priority=d['priority'],
                                name=d.get('name') or d['kind']) for d in devices],
                    branches=[b2 for b2, br in grid['branches'].items() if eid in (br['a'], br['b'])])
    if eid in world.zone_by_id:
        return zone_view(world, eid)
    if eid in world.firms:
        return firm_view(world, eid)
    if eid in world.pops:
        p = world.pops[eid]
        return dict(type='pop', id=eid, title=pop_title(world, p), kind=p['kind'], group=p['group'], zone=p['zone'],
                    count=p['count'], employed=p['employed'], inactive=p.get('inactive', 0),
                    wealth=r(world.ledger.balance('pop:'+eid)), income_day=r(p['income_ema']), elasticity=p['elasticity'],
                    jobs={fid: n for fid, staff in world.jobs.items() for pid, n in staff.items() if pid == eid},
                    provenance=p['provenance'])
    if eid in grid['storage']:
        s = grid['storage'][eid]
        return dict(type='storage', id=eid, title=s['name'], p_mw=s['p_mw'], e_mwh=s['e_mwh'], soc=r(s['soc'], 3), mode=s['mode'],
                    setpoint=s['setpoint'], grid_forming=s['grid_forming'], forming=bool(s.get('forming_active')), status=s['status'],
                    p=r(f.get('storage', {}).get(eid, 0.)), throughput_mwh=r(s['cycles_mwh'], 1), actions=['storage_mode'])
    if eid in world.substations:
        s = world.substations[eid]
        return dict(type='substation', id=eid, title=s['name'], hv_bus=s['hv_bus'], mv_bus=s['mv_bus'],
                    v_hv=r(f.get('vm', {}).get(s['hv_bus'], 0.), 4), v_mv=r(f.get('vm', {}).get(s['mv_bus'], 0.), 4),
                    transformers=[dict(id=t, loading=r(f.get('loading', {}).get(t, 0.), 3), tap=grid['branches'][t].get('tap', 1.),
                                       status=branch_state(world, t, grid['branches'][t], f)[3]) for t in s['transformers']],
                    actions=['build_storage', 'build_transformer'])
    if eid == 'link':
        ac = grid['hvac']
        cables = [dict(id=c, status=branch_state(world, c, grid['branches'][c], f)[3], loading=r(f.get('loading', {}).get(c, 0.), 3)) for c in ac['cables']]
        return dict(type='link', id='link', title='Mainland links', capacity=N.link_capacity(world), p=r(f.get('link', 0.)),
                    q=r(f.get('link_q', 0.)), margin=world.settings['link_margin'],
                    reference='AC mainland grid' if grid['source_bus'] == 'mainland_ac' else 'HVDC converter',
                    hvdc=dict(poles=grid['link']['poles'], capacity=N.hvdc_capacity(world), p=r(f.get('link_dc', f.get('link', 0.)))),
                    hvac=dict(name=ac['name'], cables=cables, capacity=N.hvac_capacity(world), stage_mw=ac['capacity'], p=r(f.get('link_ac', 0.)),
                              stages=[], player_controlled=True, mainland_limit=440.))
    if eid in world.projects:
        return dict(type='project', **project_view(world, world.projects[eid]))
    return None


def parcel(world, x, y):
    """Everything known about the 0.5 km parcel at (x, y) (spec 9.2: land use, wind, cost of building)."""
    from . import land
    from .construction import BuildError, plan_turbine
    from .island import coast_distance
    from . import windfield as WF
    from math import hypot
    c = land.cell_of(x, y)
    if c is None:
        return None
    cx, cy = land.center(*c)
    classes, zone_of = land.grid()
    k = c[1]*land.NX+c[0]
    cls = classes[k]
    out = dict(type='parcel', id=f'parcel_{c[0]}_{c[1]}', x=r(cx, 2), y=r(cy, 2), size_km=land.CELL, land=land.CLASSES[cls][0],
               title=f"Parcel {c[0]}·{c[1]} · {land.CLASSES[cls][0]}")
    if cls == '~':
        out.update(zone=None, note='Open sea. Offshore wind is not part of this version.')
        return out
    z = world.zones[zone_of[k]]
    residents = world.society_stats['zone_residents']
    people = land.parcel_people(cx, cy, residents)
    towns = sorted(world.zones, key=lambda q: hypot(q['x']-cx, q['y']-cy))
    sub = min(world.substations.values(), key=lambda s: hypot(s['x']-cx, s['y']-cy))
    now = WF.hub_speed(world.weather_now, 100, cx, cy, world.minute/1440, world.seed)
    yields = []
    for model, m in TURBINE_MODELS.items():
        mean = WF.at_height(cx, cy, m['hub'])
        cf = N.capacity_factor(model, mean)
        yields.append(dict(model=model, hub=m['hub'], mean=r(mean, 2), cf=r(cf, 3), gwh=r(cf*m['mw']*8.76, 1)))
    objects = [t for t, tb in world.grid['turbines'].items() if land.cell_of(tb['x'], tb['y']) == c]
    objects += [s for s, x in world.substations.items() if land.cell_of(x['x'], x['y']) == c]
    try:
        plan = plan_turbine(world, 'PB-3.6', cx, cy)
        build = dict(ok=True, cost=r(plan['cost']/1e6, 1), days=plan['days'], connection=plan['connection'])
    except BuildError as exc:
        build = dict(ok=False, reason=str(exc))
    out.update(zone=z['id'], zone_name=z['name'], zone_kind=z['kind'], people=round(people), coast_km=r(coast_distance(cx, cy), 2),
               nearest_town=towns[0]['name'], town_km=r(hypot(towns[0]['x']-cx, towns[0]['y']-cy), 1),
               substation=sub['name'], substation_km=r(hypot(sub['x']-cx, sub['y']-cy), 1),
               wind_mean_100m=r(WF.mean100(cx, cy), 2), wind_now_100m=r(now, 2), yields=yields,
               objects=objects, turbine_site=build, buildable_area_km2=r(land.CELL**2 if build['ok'] else 0., 2))
    return out


def pop_title(world, p):
    zone = world.zone_by_id[p['zone']]['name']
    if p['kind'] == 'resident':
        return f"{zone} · {p['group']}"
    return f"{zone} · {p['kind']}"


def zone_view(world, zid):
    z = world.zone_by_id[zid]
    st = world.society_stats
    f = world.flows or {}
    comp = {}
    for did, (pw, srv) in f.get('dev', {}).items():
        d = world.devices[did]
        zone = d['owner'][1] if d['owner'][0] == 'zone' else world.firms[d['owner'][1]]['zone']
        if zone == zid:
            key = d['kind'] if d['kind'] != 'equipment' else 'industry'
            comp[key] = comp.get(key, 0.)+pw*srv
    pops = [dict(id=p['id'], title=pop_title(world, p), count=p['count'], employed=p['employed']) for p in world.pops.values()
            if p['zone'] == zid and p['count'] > 0]
    res = world.devices['res_'+zid]
    return dict(type='zone', id=zid, title=z['name'], kind=z['kind'], residents=st['zone_residents'].get(zid, 0),
                households=round(st['zone_residents'].get(zid, 0)/HOUSEHOLD_SIZE), housing_units=z['housing_units'],
                tourists=st['zone_tourists'].get(zid, 0), holiday=st['zone_holiday'].get(zid, 0),
                seasonal=st['zone_seasonal'].get(zid, 0), working=st['zone_working'].get(zid, 0),
                unemployed=st['zone_unemployed'].get(zid, 0), beds=z['beds'], holiday_homes=z['holiday_homes'],
                heating=dict(direct=z['direct'], heat_pump=z['heat_pump']), indoor_c=r(res['t_in'], 2),
                outage_h_30d=r(world.zone_outage_hours(zid, 30), 2), load=comp, bus=z['bus'],
                bus_v=r(f.get('vm', {}).get(z['bus'], 0.), 4), pops=pops,
                firms=[dict(id=x['id'], name=x['name'], kind=x['kind'], staff=x['staff']) for x in world.firms.values() if x['zone'] == zid],
                history=list(world.entity_hist.get('res_'+zid, [])), unit='household MWh per hour (served, unserved)')


def firm_view(world, fid):
    from . import retail as R
    x = world.firms[fid]
    led = world.ledger
    eq = []
    for did in x['equipment']:
        d = world.devices[did]
        eq.append(dict(id=did, name=d['name'], state=d['state'], p=r(d['p']*d['served']), rated=r(d['p_rated'], 2),
                       priority=d['priority'], trips=d.get('trips', 0)))
    return dict(type='firm', id=fid, title=x['name'], kind=x['kind'], sector=x['sector'], zone=x['zone'], bus=x['bus'],
                status=x['status'], staff=x['staff'], desired_staff=x['desired_staff'], cash=r(led.balance('firm:'+fid)),
                contract=world.contracts.get('firm:'+fid), credit=x.get('credit'), liquidation=x.get('liquidation'),
                electricity_price=world.tariff(R.category(x), world.minute, 'firm:'+fid),
                price=r(x['price'], 1), output=x['output'], inventory={k: r(v, 1) for k, v in x['inventory'].items()},
                today={k: r(v, 1) for k, v in x['today'].items()}, yesterday={k: r(v, 1) for k, v in x['last_day'].items()},
                util=r(x['ema_util'], 3), margin=r(x['ema_margin'], 3), capacity_factor=r(x['capacity_factor'], 3),
                equipment=eq, power=r(firm_power(world, x), 3), beds=x.get('beds'), herd=r(x.get('herd'), 0),
                history=list(world.entity_hist.get((x['equipment'] or x['devices'] or [''])[0], [])),
                unit='MWh per hour of its first device (served, unserved)', provenance=x['provenance'])


# ---------------------------------------------------------------- statistics pages
def table(world, name):
    st = world.society_stats
    led = world.ledger
    if name == 'zones':
        rows = []
        for z in world.zones:
            zid = z['id']
            work = st['zone_working'].get(zid, 0)
            unemp = st['zone_unemployed'].get(zid, 0)
            pops = [p for p in world.pops.values() if p['zone'] == zid and p['kind'] == 'resident']
            income = sum(p['income_ema'] for p in pops)/max(1, sum(p['count'] for p in pops))
            rows.append([zid, z['name'], z['kind'], st['zone_residents'].get(zid, 0), work, r(unemp/max(1, work), 3),
                         st['zone_tourists'].get(zid, 0), st['zone_holiday'].get(zid, 0), r(income, 0),
                         r(world.zone_outage_hours(zid, 30), 2), round(z['housing_units']-st['zone_residents'].get(zid, 0)/HOUSEHOLD_SIZE)])
        return dict(columns=['id', 'zone', 'kind', 'residents', 'labour', 'unemployment', 'tourists', 'holiday', 'income/person/day',
                             'outage h 30d', 'free homes'], rows=rows)
    if name == 'pops':
        rows = [[p['id'], pop_title(world, p), p['kind'], p['zone'], p['group'] or '', p['count'], p['employed'], p.get('inactive', 0),
                 r(led.balance('pop:'+p['id'])/max(1, p['count']), 0), r(p['income_ema']/max(1, p['count']), 0)]
                for p in world.pops.values() if p['count'] > 0]
        return dict(columns=['id', 'POP', 'kind', 'zone', 'group', 'people', 'employed', 'inactive', 'wealth/person', 'income/person/day'],
                    rows=rows, total=len(world.pops))
    if name == 'firms':
        rows = []
        for x in world.firms.values():
            d = x['last_day']
            rows.append([x['id'], x['name'], x['kind'], x['zone'], x['status'], x['staff'], x['desired_staff'], r(x['ema_util'], 2),
                         r(x['ema_margin'], 2), r(led.balance('firm:'+x['id'])/1e6, 2), r(d['produced'], 1), r(d['revenue']/1e3, 1),
                         r(d['power_cost']/1e3, 1), r(d['outage_min'], 0)])
        return dict(columns=['id', 'firm', 'kind', 'zone', 'status', 'staff', 'wanted', 'utilisation', 'margin', 'cash MSEK',
                             'output yesterday', 'revenue kSEK', 'power kSEK', 'outage min'], rows=rows)
    if name == 'markets':
        from .economy import export_price, import_price
        rows = []
        for g, m in world.markets.items():
            if m.get('internal'):
                continue
            last = m.get('last', {})
            rows.append([g, m['unit'], r(m['price'], 0), r(m['ref'], 0), r(import_price(world, g), 0) if m['tradable'] else None,
                         r(export_price(world, g), 0) if m['tradable'] else None, r(last.get('demand', 0), 1),
                         r(last.get('supplied', 0), 1), r(last.get('imported', 0), 1), r(last.get('exported', 0), 1), r(last.get('unmet', 0), 1)])
        services = [[x['id'], x['name'], r(x['price'], 0), r(x['last_day'].get('demand', 0), 1), r(x['last_day']['sold'], 1),
                     r(x['last_day']['unmet'], 1)] for x in world.firms.values() if x['scope'] in ('zone', 'firm') and x['status'] == 'operating']
        return dict(columns=['good', 'unit', 'island price', 'mainland reference', 'import parity', 'export parity', 'demand',
                             'local supply', 'imported', 'exported', 'unmet'], rows=rows,
                    services_columns=['firm', 'name', 'price', 'demand', 'sold', 'unmet'], services=services)
    if name == 'finance':
        cats = sorted(led.totals.items(), key=lambda kv: -kv[1])
        return dict(pb_cash=r(led.balance('pb')), financing=r(-led.balance('financing')), region=r(led.balance('region')),
                    retail_policy=world.retail_policy, retail_version=world.retail_version,
                    loans=[dict(id=f['id'], name=f['name'], status=f['status'], **f['credit'])
                           for f in world.firms.values() if 'credit' in f],
                    totals=[[k, r(v, 0)] for k, v in cats], days=world.history_day[-60:],
                    journal=list(world.ledger.journal)[-60:])
    if name == 'demography':
        return dict(months=world.demography['months'], current=world.demography['month'])
    if name == 'history':
        return dict(hours=list(world.history_hour)[-24*14:], days=world.history_day)
    if name == 'outlook':
        day = world.minute//1440
        return dict(days=[W.outlook_day(world.seed, day, d) for d in range(day, day+7)])
    return None
