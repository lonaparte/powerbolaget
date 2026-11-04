"""The opening state of Gutnö on 1 January, year 1 of the Fantasy Era."""
from math import ceil
from . import economy as E
from . import grid as G
from . import loads as L
from .construction import add_turbine
from .calendar import DAY, YEAR
from .island import FEEDERS, HVAC, LINES_110, LINK_POLE_MW, LINK_POLES, LINK_STATION, MAINLAND, SUBSTATIONS, WIND_FARMS, ZONES
from .params import HOUSEHOLD_SIZE, SECTORS, STARTING_CASH
from .rng import stable_unit
from .society import pop, refresh_stats

# Shares of employed residents by sector outside the zone's industrial firms (assumptions).
SECTOR_SHARES = {
    'urban': dict(public=.30, services=.40, hospitality=.06, agriculture=.0, construction=.045),
    'suburban': dict(public=.30, services=.33, hospitality=.04, agriculture=.03, construction=.05),
    'industrial': dict(public=.27, services=.18, hospitality=.03, agriculture=.05, construction=.05),
    'agri': dict(public=.26, services=.14, hospitality=.03, agriculture=.30, construction=.045),
    'tourism': dict(public=.26, services=.22, hospitality=.20, agriculture=.10, construction=.045),
    'rural': dict(public=.26, services=.15, hospitality=.06, agriculture=.22, construction=.05),
}
PARTICIPATION = .86
EMPLOYMENT = .94
RUNNING_AT_START = ('kiln', 'aux', 'cooling', 'cold', 'terminal', 'hospital')


def generate(world):
    world.zones = []
    for zid, name, x, y, kind, residents, holiday, beds, amenity, (direct, hp), town in ZONES:
        world.zones.append(dict(id=zid, name=name, x=x, y=y, kind=kind, holiday_homes=holiday, beds=beds, amenity=amenity, town=town,
                                direct=direct, heat_pump=hp, housing_units=ceil(residents/HOUSEHOLD_SIZE*1.035), bus=zid,
                                start_residents=residents, provenance='synthetic'))
    world.zone_by_id = {z['id']: z for z in world.zones}
    build_grid(world)
    E.create_firms(world)
    for z in world.zones:
        did = 'res_'+z['id']
        world.devices[did] = L.aggregated(did, 'residential', ('zone', z['id']), z['bus'], 'residential', .97, 0.,
                                          heated=0., direct=z['direct'], heat_pump=z['heat_pump'], t_in=20.6,
                                          heat_electric_kw=0., heat_thermal_kw=0.)
    create_pops(world)
    endow(world)
    for f in world.firms.values():
        for did in f['equipment']:
            d = world.devices[did]
            if did.rsplit('_', 1)[-1] in RUNNING_AT_START:
                d['state'], d['want_on'] = 'running', True
    refresh_stats(world)


def build_grid(world):
    grid = world.grid = dict(buses={}, branches={}, turbines={}, farms={}, storage={}, link={}, version=0, source_bus='mainland')
    G.add_bus(grid, 'mainland', 'Mainland converter', 110., MAINLAND[0], MAINLAND[1], 'mainland')
    lid, lname, lx, ly = LINK_STATION
    G.add_bus(grid, 'lnk', lname, 110., lx, ly, 'link')
    G.add_line(grid, 'hvdc', 'mainland', 'lnk', 'HVDC', circuits=LINK_POLES, km=1.0, name='HVDC link')
    grid['link'] = dict(bus='lnk', poles=[dict(id=f'pole{i+1}', name=f'HVDC {i+1}', mw=LINK_POLE_MW, status='ok', until=None)
                                          for i in range(LINK_POLES)], x=lx, y=ly, mainland=list(MAINLAND))
    world.substations = {}
    stations = {'LNK': 'lnk'}
    for sid, name, x, y, units in SUBSTATIONS:
        key = sid.lower()
        hv = G.add_bus(grid, f'{key}_110', name, 110., x, y, 'substation', station=key)
        mv = G.add_bus(grid, f'{key}_20', f'{name} 20 kV', 20., x, y, 'substation_mv', station=key)
        units_ids = [G.add_transformer(grid, f't_{key}_{i+1}', hv, mv, '110/20', 40., name=f'{name} T{i+1}') for i in range(units)]
        world.substations[key] = dict(id=key, name=name, x=x, y=y, hv_bus=hv, mv_bus=mv, transformers=units_ids)
        stations[sid] = hv
    for a, b, ltype in LINES_110:
        G.add_line(grid, f'l_{a}_{b}'.lower(), stations[a], stations[b], ltype,
                   name=f"{grid['buses'][stations[a]]['name']}–{grid['buses'][stations[b]]['name']}")
    build_hvac(world, grid)
    for z in world.zones:
        G.add_bus(grid, z['id'], z['name'], 20., z['x'], z['y'], 'zone', zone=z['id'])
    for zid, (src, ltype, n) in FEEDERS.items():
        start = src if src.startswith('z') else f'{src.lower()}_20'
        # Land feeders can be re-fed by switching after a fault; the sea cable to the islet cannot.
        G.add_line(grid, f'f_{zid}', start, zid, ltype, circuits=n, restorable=not src.startswith('z'),
                   name=f"Feeder {grid['buses'][start]['name']} → {world.zone_by_id[zid]['name']}")
    G.add_bus(grid, 'ind_kal', 'Kalkudden industry 20 kV', 20., 46.4, 88.7, 'industry', zone='z04')
    G.add_line(grid, 'f_ind_kal', 'kal_20', 'ind_kal', 'CAB20', circuits=3, restorable=True, name='Feeder Kalkudden → cement works')
    for fid, name, host, (fx, fy), model, rows, age in WIND_FARMS:
        key = fid.lower()
        mw = len([p for r in rows for p in r])*{'PB-2.3': 2.3, 'PB-3.6': 3.6}[model]
        hv = G.add_bus(grid, f'{key}_110', f'{name} 110 kV', 110., fx, fy, 'farm')
        hub = G.add_bus(grid, f'{key}_33', f'{name} 33 kV', 33., fx, fy, 'collector')
        G.add_transformer(grid, f'{key}_tr', hv, hub, '110/33', float(ceil(mw*1.2/10)*10), name=f'{name} 110/33 kV')
        sub = world.substations[host.lower()]
        G.add_line(grid, f'{key}_line', sub['hv_bus'], hv, 'OHL110', name=f"{sub['name']}–{name}")
        grid['farms'][key] = dict(id=key, name=name, hub=hub, substation=sub['id'], turbines=[])
        for row in rows:
            connect = hub
            for x, y in row:
                plan = dict(model=model, x=x, y=y, farm=key, connect_bus=connect,
                            cable_km=round(G.length(grid, connect, hub, 1.1) if connect != hub else
                                           max(.3, ((x-fx)**2+(y-fy)**2)**.5*1.1), 3))
                if connect != hub:
                    prev = grid['buses'][connect]
                    plan['cable_km'] = round(max(.3, ((x-prev['x'])**2+(y-prev['y'])**2)**.5*1.1), 3)
                tid = add_turbine(world, plan, status='ok', age=age)
                grid['turbines'][tid]['maintained'] = -int(stable_unit('maintained', tid)*330*1440)
                connect = grid['turbines'][tid]['bus_mv']
    grid['version'] = 1


def build_hvac(world, grid):
    """The planned AC interconnector: present from the start as planned equipment, commissioned in stages
    by the national grid operator (not Powerbolaget), as dated events."""
    sid, name, sx, sy = HVAC['station']
    G.add_bus(grid, 'mainland_ac', 'Mainland 220 kV grid', 220., HVAC['mainland'][0], HVAC['mainland'][1], 'mainland')
    G.add_bus(grid, 'stk_220', f'{name} 220 kV', 220., sx, sy, 'interconnector')
    G.add_bus(grid, 'stk_110', f'{name} 110 kV', 110., sx, sy, 'interconnector')
    cables = [G.add_line(grid, f'hvac_{i+1}', 'mainland_ac', 'stk_220', 'CAB220', km=HVAC['km'], name=f'HVAC cable {i+1}', planned=True)
              for i in range(HVAC['cables'])]
    G.add_transformer(grid, 'stk_t1', 'stk_220', 'stk_110', '220/110', 500., name=f'{name} 220/110 kV', planned=True)
    G.add_line(grid, 'l_stk_lnk', 'stk_110', 'lnk', 'CAB110', name=f'{name}–Länkstation', planned=True)
    G.add_line(grid, 'l_stk_rom', 'stk_110', 'rom_110', 'OHL110', name=f'{name}–Romsta', planned=True)
    stages = [dict(minute=y*YEAR+d*DAY, cables=c, mw=mw) for y, d, c, mw in HVAC['stages']]
    grid['hvac'] = dict(station=[sx, sy], name=name, mainland=list(HVAC['mainland']), cables=cables, transformer='stk_t1',
                        links=['l_stk_lnk', 'l_stk_rom'], capacity=0., cable_mw=220., stages=stages)
    for i, st in enumerate(stages):
        world.events.push(st['minute'], 'interconnector', 'commission', stage=i)
    world.projects['tso_hvac'] = dict(id='tso_hvac', kind='interconnector', owner='tso', title='HVAC 220 kV mainland link (grid operator)',
                                      start=0, finish=stages[0]['minute'], cost=7.5e9, paid=0., status='building', zone='z05')


def create_pops(world):
    world.pops = {}
    industry_jobs = {}
    for f in world.firms.values():
        if f['sector'] == 'industry':
            industry_jobs[f['zone']] = industry_jobs.get(f['zone'], 0)+f['desired_staff']
    employed_by = {}
    for z in world.zones:
        r = z['start_residents']
        youth, retired = round(.20*r), round(.245*r)
        working = r-youth-retired
        employed_total = working*PARTICIPATION*EMPLOYMENT
        ind = min(industry_jobs.get(z['id'], 0), employed_total*.5)
        shares = SECTOR_SHARES[z['kind']]
        rest = employed_total-ind
        norm = sum(shares.values())
        employed = {g: rest*shares[g]/norm for g in shares}
        employed['industry'] = ind
        counts = {g: employed[g]/EMPLOYMENT/PARTICIPATION for g in SECTORS}
        # Integer people: round, then fix the total to the zone's working-age population.
        ints = {g: int(counts[g]) for g in SECTORS}
        short = working-sum(ints.values())
        for g in sorted(SECTORS, key=lambda g: counts[g]-int(counts[g]), reverse=True)[:short]:
            ints[g] += 1
        for g in SECTORS:
            p = pop(f"{z['id']}_{g}", 'resident', z['id'], g, ints[g])
            p['inactive'] = round(ints[g]*(1-PARTICIPATION))
            world.pops[p['id']] = p
            employed_by[p['id']] = min(round(employed[g]), ints[g]-p['inactive'])
        world.pops[z['id']+'_retired'] = pop(z['id']+'_retired', 'resident', z['id'], 'retired', retired)
        world.pops[z['id']+'_youth'] = pop(z['id']+'_youth', 'resident', z['id'], 'youth', youth)
        world.pops[z['id']+'_holiday'] = pop(z['id']+'_holiday', 'holiday', z['id'], None, 0)
        if any(f['kind'] == 'hospitality' and f['zone'] == z['id'] for f in world.firms.values()):
            world.pops[z['id']+'_tourist'] = pop(z['id']+'_tourist', 'tourist', z['id'], None, 0, stay_days=3.6,
                                                 lodging='hotel and rental', origin='mainland')
            world.pops[z['id']+'_seasonal'] = pop(z['id']+'_seasonal', 'seasonal', z['id'], 'hospitality', 0)
    assign_jobs(world, employed_by)


def assign_jobs(world, employed_by):
    """Initial employment: each zone's employed people work for firms of their sector, nearest first."""
    from math import hypot
    world.jobs = {fid: {} for fid in world.firms}
    zones = world.zone_by_id
    by_sector = {}
    for f in world.firms.values():
        by_sector.setdefault(f['sector'], []).append(f)
    for pid in sorted(employed_by):
        n = employed_by[pid]
        p = world.pops[pid]
        z = zones[p['zone']]
        firms = sorted(by_sector.get(p['group'], []), key=lambda f: (hypot(zones[f['zone']]['x']-z['x'], zones[f['zone']]['y']-z['y']), f['id']))
        if p['group'] == 'industry':
            firms = [f for f in firms if f['zone'] == p['zone']] or firms
        for f in firms:
            if n <= 0:
                break
            if f['kind'] in ('services', 'public', 'hospitality', 'agriculture', 'construction'):
                take = n if f['zone'] == p['zone'] or f['kind'] == 'construction' else 0
                if f['kind'] == 'hospitality' and take == 0:
                    take = n
                if f['kind'] == 'agriculture' and take == 0:
                    take = n
            else:
                take = min(n, f['desired_staff']-sum(world.jobs[f['id']].values()))
            if take > 0:
                world.jobs[f['id']][pid] = world.jobs[f['id']].get(pid, 0)+take
                p['employed'] += take
                n -= take
    for f in world.firms.values():
        f['staff'] = sum(world.jobs[f['id']].values())
        if f['kind'] in ('services', 'public', 'hospitality', 'agriculture', 'construction') or f['desired_staff'] == 0:
            f['desired_staff'] = f['staff']
        if f['kind'] == 'agriculture':
            f['herd'] = f['staff']*E.HERD_PER_FARM_WORKER
            f['crop_ha'] = f['staff']*E.CROP_HA_PER_FARM_WORKER
            f['inventory']['grain'] = round(f['crop_ha']*5.4*.4)   # what is left of last year's harvest
        if f['kind'] == 'services':
            f['ema_sales'] = f['staff']*E.SERVICE_PRODUCTIVITY*8*.62*.8
        if f['kind'] == 'construction':
            f['ema_sales'] = f['staff']*E.CONSTRUCTION_PRODUCTIVITY*8.4*5/7*.8


def endow(world):
    led = world.ledger
    for p in world.pops.values():
        per = {'retired': 120000., 'youth': 6000.}.get(p['group'], 48000.)
        if p['kind'] == 'resident':
            led.endow('pop:'+p['id'], p['count']*per)
    for f in world.firms.values():
        base = {'cement': 180e6, 'quarry': 25e6, 'dairy': 30e6, 'construction': 60e6, 'hospital': 0.}.get(f['kind'], 4e6)
        led.endow('firm:'+f['id'], base+f['staff']*45000)
    led.endow('region', 250e6)
    led.endow('pb', STARTING_CASH)
