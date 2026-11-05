"""Economic Production Model: bounded-rational firms, markets, labour and investment (spec section 5).

Firms are not POPs; their staff are counted people of resident POPs (world.jobs). Each firm plans
the next hour from what it knows now (EMA demand forecast, inventory, inputs, staff, electricity
price), turns the plan into equipment starts and stops, and settles what the equipment actually did:
a machine that tripped produced nothing while it was down, and a kiln needs hours to warm up again.
Markets clear daily: island markets for traded goods are bounded by mainland import and export prices;
local services (the 'consumer' basket), lodging and ferry trips clear in their own zone or firm.
Every payment goes through the ledger.
"""
from math import exp, hypot, tanh
from . import loads as L
from .calendar import HOUR, is_rest_day, parts
from .params import GOODS, IMPORT_SHARE, INCOME_TAX, SHIFT_HOURS, WAGE

# Industrial firms: id, name, kind, zone, connection bus, staff.
INDUSTRY = [
    ('f_cement', 'Kalkudden Cement', 'cement', 'z11', 'ind_kal', 215),
    ('f_quarry_n', 'Kalkuddens kalkbrott', 'quarry', 'z11', 'z11', 70),
    ('f_quarry_s', 'Burgviks kalkbrott', 'quarry', 'z18', 'z18', 32),
    ('f_dairy', 'Romsta mejeri', 'dairy', 'z10', 'z10', 120),
    ('f_feed', 'Gutnö foder', 'feedmill', 'z10', 'z10', 26),
    ('f_slaughter', 'Hemby slakteri', 'slaughter', 'z17', 'z17', 85),
    ('f_brewery', 'Hamnens bryggeri', 'brewery', 'z02', 'z02', 32),
    ('f_port', 'Västerhamn färjeterminal', 'port', 'z02', 'z02', 55),
    ('f_hospital', 'Gutnö lasarett', 'hospital', 'z01', 'z01', 900),
    ('f_construction', 'Gutnö bygg', 'construction', 'z03', 'z03', 1150),
]
# Equipment per kind: key, name, MW, power factor, priority class, ramp min, restart min, warm-up min, warm-up share,
# production role and rate (output units per hour while running).
EQUIPMENT = {
    # Power factors include the plant's capacitor banks. The cement works is sized like Gotland's Slite
    # plant: about 2 Mt of clinker a year and about 340 GWh of electricity with its quarry about 20 GWh
    # more (Region Gotland: the cement producer uses about 350 GWh of the island's 850-1,000 GWh).
    'cement': [('kiln', 'Kiln line', 12.0, .94, 'industry', 25, 30, 480, .35, 'clinker', 240.),
               ('aux', 'Coal mill and kiln auxiliaries', 3.5, .93, 'industry', 5, 15, 0, 0., 'aux', 0.),
               ('rawmill1', 'Raw mill 1', 6.0, .94, 'flexible', 4, 20, 0, 0., 'rawmeal', 230.),
               ('rawmill2', 'Raw mill 2', 6.0, .94, 'flexible', 4, 20, 0, 0., 'rawmeal', 230.),
               ('cmill1', 'Cement mill 1', 7.5, .94, 'flexible', 4, 20, 0, 0., 'cement', 160.),
               ('cmill2', 'Cement mill 2', 7.5, .94, 'flexible', 4, 20, 0, 0., 'cement', 160.),
               ('site', 'Packing, conveyors and site services', 2.5, .9, 'commercial', 2, 10, 0, 0., 'aux', 0.)],
    'quarry': [('crusher1', 'Primary crusher', 1.4, .84, 'commercial', 2, 10, 0, 0., 'limestone', 380.),
               ('crusher2', 'Secondary crusher and conveyors', 1.0, .84, 'commercial', 2, 10, 0, 0., 'limestone', 0.)],
    'dairy': [('cooling', 'Cold storage', .7, .9, 'industry', 1, 5, 0, 0., 'cooling', 0.),
              ('line', 'Process line', 1.3, .9, 'industry', 3, 15, 0, 0., 'food', 16.)],
    'feedmill': [('mill', 'Hammer mill and pelleting', .9, .86, 'commercial', 2, 10, 0, 0., 'feed', 12.)],
    'slaughter': [('cold', 'Cold store', .5, .9, 'industry', 1, 5, 0, 0., 'cooling', 0.),
                  ('line', 'Processing line', .6, .9, 'commercial', 2, 10, 0, 0., 'food', 2.2)],
    'brewery': [('line', 'Brew house', .35, .92, 'commercial', 2, 10, 0, 0., 'food', .9)],
    'port': [('terminal', 'Terminal', .3, .95, 'critical', 1, 2, 0, 0., '', 0.),
             ('shore', 'Ferry shore power', 1.8, .92, 'commercial', 1, 2, 0, 0., '', 0.)],
    'hospital': [('hospital', 'Hospital', 1.35, .93, 'critical', 1, 1, 0, 0., '', 0.)],
}
CEMENT_RATE = {e[0]: e[10] for e in EQUIPMENT['cement']}
# The large quarry next to the cement works has two crushing lines (twice the equipment of the small one).
QUARRY_RATE = {'f_quarry_n': 800., 'f_quarry_s': 180.}
QUARRY_SCALE = {'f_quarry_n': 2.1, 'f_quarry_s': 1.}
# Inputs per unit of each production role.
RECIPE = {'rawmeal': {'limestone': 1.0}, 'clinker': {'rawmeal': 1.55, 'fuel': .82}, 'cement': {'clinker': .93},
          'limestone': {}, 'food_dairy': {'milk': 6.2}, 'feed': {'grain': 1.0}, 'food_slaughter': {'livestock': 1.65},
          'food_brewery': {'grain': .28}}
SERVICE_PRODUCTIVITY = .55       # consumer baskets (1000 SEK) per worker-hour
CONSTRUCTION_PRODUCTIVITY = .70  # work units (1000 SEK) per worker-hour
FERRY_TRIPS_PER_SAILING = 1500
HERD_PER_FARM_WORKER = 9.0       # dairy-cow equivalents
CROP_HA_PER_FARM_WORKER = 38.0


def firm(fid, name, kind, sector, zone, bus, output, scope, **extra):
    base = dict(id=fid, name=name, kind=kind, sector=sector, zone=zone, bus=bus, output=output, scope=scope,
                status='operating', inventory={}, equipment=[], devices=[], desired_staff=0, staff=0,
                price=GOODS[output][1] if output in GOODS else 0., ema_sales=0., ema_util=.8, ema_margin=.05,
                months_high=0, months_low=0, capacity_factor=1.0, today=_blank_day(), month=_blank_day(),
                last_day=_blank_day(), last_month=_blank_day(), plans=[], provenance='synthetic')
    base.update(extra)
    return base


def _blank_day():
    return dict(produced=0., sold=0., revenue=0., input_cost=0., wages=0., power_cost=0., unmet=0., outage_min=0.,
                capacity=0., exported=0.)


# ---------------------------------------------------------------- creation
def create_firms(world):
    zones = {z['id']: z for z in world.zones}
    firms, devices = {}, world.devices
    for fid, name, kind, zid, bus, staff in INDUSTRY:
        sector = 'public' if kind == 'hospital' else 'construction' if kind == 'construction' else 'industry'
        output = dict(cement='cement', quarry='limestone', dairy='food', feedmill='feed', slaughter='food',
                      brewery='food', port='ferry', hospital='', construction='construction')[kind]
        scope = 'none' if kind == 'hospital' else 'firm' if kind in ('port', 'construction') else 'island'
        f = firm(fid, name, kind, sector, zid, bus, output, scope, desired_staff=staff)
        for key, ename, mw, pf, prio, ramp, restart, warm, share, role, rate in EQUIPMENT.get(kind, []):
            did = f'{fid}_{key}'
            mw *= QUARRY_SCALE.get(fid, 1.)
            devices[did] = L.equipment(did, ('firm', fid), bus, ename, mw, pf, prio, ramp, restart, warm, share, role, rate)
            f['equipment'].append(did)
        if kind == 'construction':
            did = f'{fid}_site'
            devices[did] = L.aggregated(did, 'services', ('firm', fid), bus, 'commercial', .92, staff*.6)
            f['devices'].append(did)
        firms[fid] = f
    c = firms['f_cement']
    c['inventory'] = dict(limestone=36000., rawmeal=14000., clinker=72000., cement=56000., fuel=10400.)
    c['limits'] = dict(rawmeal=24000., clinker=120000., cement=104000.)
    firms['f_quarry_n']['inventory'] = dict(limestone=84000.)
    firms['f_quarry_n']['limits'] = dict(limestone=140000.)
    firms['f_quarry_s']['inventory'] = dict(limestone=9000.)
    firms['f_quarry_s']['limits'] = dict(limestone=20000.)
    firms['f_dairy']['inventory'] = dict(milk=180., food=60.)
    firms['f_feed']['inventory'] = dict(grain=900., feed=400.)
    firms['f_slaughter']['inventory'] = dict(livestock=60., food=40.)
    firms['f_brewery']['inventory'] = dict(grain=80., food=50.)
    for z in world.zones:
        zid = z['id']
        services = firm(f's_{zid}', f"Handel & service {z['name']}", 'services', 'services', zid, z['bus'], 'consumer', 'zone')
        did = f'{services["id"]}_load'
        devices[did] = L.aggregated(did, 'services', ('firm', services['id']), z['bus'], 'commercial', .93, 0.)
        services['devices'].append(did)
        firms[services['id']] = services
        public = firm(f'p_{zid}', f"Kommunal service {z['name']}", 'public', 'public', zid, z['bus'], '', 'none')
        did = f'{public["id"]}_load'
        devices[did] = L.aggregated(did, 'public', ('firm', public['id']), z['bus'], 'critical', .94, 0.)
        public['devices'].append(did)
        firms[public['id']] = public
        if z['beds'] >= 250:
            h = firm(f'h_{zid}', f"Turism {z['name']}", 'hospitality', 'hospitality', zid, z['bus'], 'lodging', 'zone',
                     beds=z['beds'])
            did = f'{h["id"]}_load'
            devices[did] = L.aggregated(did, 'lodging', ('firm', h['id']), z['bus'], 'commercial', .95, 0., beds=z['beds'])
            h['devices'].append(did)
            firms[h['id']] = h
        if z['kind'] in ('agri', 'rural') or zid in ('z09', 'z13', 'z16', 'z17', 'z18'):
            a = firm(f'a_{zid}', f"Lantbruk {z['name']}", 'agriculture', 'agriculture', zid, z['bus'], 'milk', 'island',
                     herd=0., crop_ha=0., inventory=dict(milk=0., livestock=0., grain=0., feed=40.))
            did = f'{a["id"]}_load'
            devices[did] = L.aggregated(did, 'farm', ('firm', a['id']), z['bus'], 'residential', .9, 0., base_kw=25.)
            a['devices'].append(did)
            dryer = f'{a["id"]}_dryer'
            devices[dryer] = L.equipment(dryer, ('firm', a['id']), z['bus'], 'Grain dryer', .9, .85, 'commercial', 5, 15,
                                         role='drying')
            a['equipment'].append(dryer)
            firms[a['id']] = a
    world.firms = firms
    world.markets = {g: dict(price=ref, ref=ref, freight=fr, tradable=tr, unit=unit, demand=0., supplied=0., imported=0.,
                             exported=0., unmet=0.) for g, (unit, ref, fr, tr) in GOODS.items()}
    world.markets['rawmeal'] = dict(price=0., ref=0., freight=0., tradable=False, unit='t', demand=0., supplied=0.,
                                    imported=0., exported=0., unmet=0., internal=True)
    world.markets['clinker'] = dict(world.markets['rawmeal'])


def import_price(world, good):
    m = world.markets[good]
    return m['ref']+m['freight']


def export_price(world, good):
    m = world.markets[good]
    return max(0., m['ref']-m['freight'])


# ---------------------------------------------------------------- hourly plans
def plan_hour(world, now):
    """Every firm decides the coming hour from what it knows at `now`."""
    p = parts(now)
    hour, rest = p['hour'], is_rest_day(now)
    price = world.energy_price(now)
    avg = world.price_avg
    for f in world.firms.values():
        if f['status'] != 'operating':
            continue
        kind = f['kind']
        want = {}
        if kind == 'cement':
            inv, lim = f['inventory'], f['limits']
            # The kiln runs continuously; the mills fill and empty the silos around it and avoid
            # expensive hours while the silos give them room to (load shifting).
            expensive = price > 1.2*avg
            kiln_ok = inv['rawmeal'] > 400 and inv['fuel'] > 200 and inv['clinker'] < .97*lim['clinker']
            want['kiln'] = want['aux'] = kiln_ok and not f.get('kiln_stop')
            want['site'] = True
            raw = inv['rawmeal']/lim['rawmeal']
            raw_need = inv['limestone'] > 300 and (raw < .35 or (raw < .92 and not expensive))
            want['rawmill1'] = raw_need
            want['rawmill2'] = raw_need and (raw < .6 or not expensive)
            clinker, cement = inv['clinker']/lim['clinker'], inv['cement']/lim['cement']
            mill_need = inv['clinker'] > 600 and cement < .95 and (clinker > .7 or cement < .25 or not expensive)
            want['cmill1'] = mill_need
            want['cmill2'] = mill_need and (clinker > .45 or cement < .2)
        elif kind == 'quarry':
            shift = (6 <= hour < 22 if f['id'] == 'f_quarry_n' else 7 <= hour < 16) and not rest
            stock_ok = f['inventory']['limestone'] < .92*f['limits']['limestone']
            want['crusher1'] = want['crusher2'] = shift and stock_ok
        elif kind == 'dairy':
            want['cooling'] = True
            want['line'] = 6 <= hour < 22 and f['inventory']['milk'] > 20
        elif kind == 'feedmill':
            want['mill'] = 6 <= hour < 15 and not rest and f['inventory']['grain'] > 15 and f['inventory']['feed'] < 900
        elif kind == 'slaughter':
            want['cold'] = True
            want['line'] = 6 <= hour < 15 and not rest and f['inventory']['livestock'] > 3
        elif kind == 'brewery':
            want['line'] = 7 <= hour < 16 and not rest and f['inventory']['grain'] > 1
        elif kind == 'port':
            want['terminal'] = True
            sailings = ferry_sailings(now)
            want['shore'] = any(h <= hour < h+2 for h in sailings)
        elif kind == 'hospital':
            want['hospital'] = True
        elif kind == 'datacenter':
            want['servers'] = True
        elif kind == 'agriculture':
            want['dryer'] = harvest_day(now) and 9 <= hour < 21 and world.weather_now['humidity_pct'] < 92
        for i, did in enumerate(f['equipment']):
            key = did[len(f['id'])+1:]
            if key in want:
                d = world.devices[did]
                if d['want_on'] != want[key]:
                    world.events.push(now+(i*7) % 23, 'equipment', 'equipment', device=did, on=want[key])


def ferry_sailings(now):
    """Departure hours of the ferry: more sailings in summer."""
    doy = parts(now)['doy']
    if 150 <= doy < 245:
        return (6, 10, 14, 18, 21)
    if 120 <= doy < 280:
        return (7, 13, 19)
    return (8, 18)


def harvest_day(now):
    return 210 <= parts(now)['doy'] < 258


# ---------------------------------------------------------------- hourly settlement
def settle_hour(world, start, end):
    """Production of the hour that just ended, from what equipment and staff actually did."""
    p = parts(start)
    hour = p['hour']
    for f in world.firms.values():
        if f['status'] != 'operating':
            continue
        kind = f['kind']
        run = {}
        for did in f['equipment']:
            d = world.devices[did]
            run[did[len(f['id'])+1:]] = d['run_min']/60
            if d['run_min'] < 59.9 and d['want_on']:
                f['today']['outage_min'] += 60-d['run_min'] if d['state'] in ('tripped', 'warmup') else 0
            d['run_min'] = 0.
        inv = f['inventory']
        if kind == 'cement':
            R = CEMENT_RATE
            produce(f, 'rawmeal', run['rawmill1']*R['rawmill1']+run['rawmill2']*R['rawmill2'], RECIPE['rawmeal'])
            if run['aux'] > .5:
                produce(f, 'clinker', run['kiln']*R['kiln'], RECIPE['clinker'])
            produce(f, 'cement', run['cmill1']*R['cmill1']+run['cmill2']*R['cmill2'], RECIPE['cement'], output=True)
            for k, lim in f['limits'].items():
                inv[k] = min(inv[k], lim)
        elif kind == 'quarry':
            produce(f, 'limestone', min(run['crusher1'], run['crusher2'])*QUARRY_RATE[f['id']], {}, output=True)
        elif kind == 'dairy':
            produce(f, 'food', run['line']*16./6.2, RECIPE['food_dairy'], output=True)
        elif kind == 'feedmill':
            produce(f, 'feed', run['mill']*12., RECIPE['feed'], output=True)
        elif kind == 'slaughter':
            produce(f, 'food', run['line']*2.2/1.65, RECIPE['food_slaughter'], output=True)
        elif kind == 'brewery':
            produce(f, 'food', run['line']*.9, RECIPE['food_brewery'], output=True)
        elif kind in ('services', 'construction'):
            served = world.devices[f['devices'][0]]['served']
            present = staff_presence(f, start)
            productivity = SERVICE_PRODUCTIVITY if kind == 'services' else CONSTRUCTION_PRODUCTIVITY
            f['today']['capacity'] += f['staff']*present*productivity*served
            if served < .999:
                f['today']['outage_min'] += 60*(1-served)
        elif kind == 'agriculture' and hour == 23:
            daily_farm(world, f, start)
        elif kind == 'datacenter':
            mwh = run['servers']*world.devices[f['equipment'][0]]['p_rated']
            value = mwh*1900.
            world.ledger.transfer('external', 'firm:'+f['id'], value, 'export:compute', start)
            f['today']['produced'] += mwh
            f['today']['sold'] += mwh
            f['today']['revenue'] += value
        if kind in ('hospitality', 'public'):
            served = world.devices[f['devices'][0]]['served']
            if served < .999:
                f['today']['outage_min'] += 60*(1-served)


def produce(f, good, amount, recipe, output=False):
    """Make up to `amount` of good, limited by input stocks."""
    inv = f['inventory']
    if amount <= 0:
        return 0.
    for g, per in recipe.items():
        if per > 0:
            amount = min(amount, inv.get(g, 0.)/per)
    for g, per in recipe.items():
        inv[g] = inv.get(g, 0.)-amount*per
    inv[good] = inv.get(good, 0.)+amount
    if output:
        f['today']['produced'] += amount
    return amount


def staff_presence(f, minute):
    """Share of a firm's staff at work in the hour starting at `minute`."""
    h = (minute % 1440)/60+.5
    if f['kind'] == 'services':
        return L.open_hours(h, minute)*.62
    if f['kind'] == 'construction':
        return 0. if is_rest_day(minute) else L.window(h, 7, 16)
    return .33


def daily_farm(world, f, minute):
    """Milk and livestock every day; grain in the harvest window when the weather allows."""
    inv = f['inventory']
    herd = f['herd']*f['capacity_factor']
    feed_need = herd*.012
    fed = min(1., inv.get('feed', 0.)/feed_need) if feed_need > 0 else 1.
    inv['feed'] = max(0., inv.get('feed', 0.)-feed_need*fed)
    milk = herd*.026*(.75+.25*fed)
    inv['milk'] += milk
    inv['livestock'] += herd*.0011
    if harvest_day(minute):
        wet = world.weather_now['humidity_pct'] > 93
        grain = 0. if wet else f['crop_ha']*f['capacity_factor']*5.4/40
        inv['grain'] += grain
        f['today']['produced'] += grain
    f['today']['produced'] += milk


# ---------------------------------------------------------------- markets
def sell_island(world, good, orders, minute):
    """Clear an island market. orders: list of (buyer account, qty).
    Local sellers first (cheapest first), then imports at import parity. Returns filled quantities."""
    m = world.markets[good]
    sellers = [f for f in world.firms.values() if f['status'] == 'operating' and f['scope'] == 'island'
               and f['inventory'].get(good, 0.) > 1e-9 and good in sells(f)]
    supply = {f['id']: max(0., f['inventory'][good]-reserve(f, good)) for f in sellers}
    total_local = sum(supply.values())
    demand = sum(q for _, q in orders)
    m['demand'] += demand
    filled = []
    price = m['price']
    share = min(1., total_local/demand) if demand > 0 else 0.
    for buyer, qty in orders:
        local = qty*share
        rest = qty-local
        if local > 0:
            for f in sellers:
                if total_local <= 0:
                    break
                part = local*supply[f['id']]/total_local
                f['inventory'][good] -= part
                f['today']['sold'] += part if good == f['output'] else 0
                world.ledger.transfer(buyer, 'firm:'+f['id'], part*price, 'goods:'+good, minute, good, part)
                f['today']['revenue'] += part*price
        imported = 0.
        if rest > 0 and m['tradable']:
            imported = rest
            world.ledger.transfer(buyer, 'external', rest*import_price(world, good), 'import:'+good, minute, good, rest)
            m['imported'] += rest
        elif rest > 0:
            m['unmet'] += rest
        m['supplied'] += local
        filled.append(local+imported)
    # Price discovery: scarcity pulls toward import parity, surplus toward export parity.
    if demand > 0 or total_local > 0:
        pressure = tanh((demand-total_local)/(max(demand, total_local)+1e-9))
        m['price'] = min(import_price(world, good), max(export_price(world, good), price*(1+.04*pressure)))
    return filled


def sells(f):
    if f['kind'] == 'agriculture':
        return ('milk', 'livestock', 'grain')
    if f['kind'] == 'cement':
        return ('cement',)
    return (f['output'],)


def reserve(f, good):
    """Stock a seller keeps for itself (inputs it needs)."""
    if f['kind'] == 'agriculture' and good == 'grain':
        return 0.
    return 0.


def export_surplus(world, minute):
    """Sellers ship stock above their target to the mainland at export parity (limited ship capacity)."""
    plans = [('f_cement', 'cement', .25, 7200.), ('f_quarry_n', 'limestone', .55, 4200.), ('f_quarry_s', 'limestone', .5, 1500.)]
    for fid, good, keep, cap in plans:
        f = world.firms.get(fid)
        if not f or f['status'] != 'operating':
            continue
        lim = f['limits'][good]
        qty = min(cap, max(0., f['inventory'][good]-keep*lim))
        if qty > 0:
            f['inventory'][good] -= qty
            value = qty*export_price(world, good)
            world.ledger.transfer('external', 'firm:'+fid, value, 'export:'+good, minute, good, qty)
            f['today']['sold'] += qty
            f['today']['exported'] += qty
            f['today']['revenue'] += value
            world.markets[good]['exported'] += qty
    # Farms and food processors sell surplus food and grain off-island.
    for f in world.firms.values():
        if f['status'] != 'operating':
            continue
        if f['kind'] in ('dairy', 'slaughter', 'brewery'):
            surplus = f['inventory'].get('food', 0.)-25.
            if surplus > 0:
                ship(world, f, 'food', surplus*.6, minute)
        if f['kind'] == 'agriculture':
            for good, keep in (('grain', 400.), ('milk', 25.), ('livestock', 8.)):
                surplus = f['inventory'].get(good, 0.)-keep
                if surplus > 0:
                    ship(world, f, good, surplus*.5, minute)


def ship(world, f, good, qty, minute):
    f['inventory'][good] -= qty
    value = qty*export_price(world, good)
    world.ledger.transfer('external', 'firm:'+f['id'], value, 'export:'+good, minute, good, qty)
    f['today']['sold'] += qty
    f['today']['exported'] += qty
    f['today']['revenue'] += value
    world.markets[good]['exported'] += qty


def restock_inputs(world, minute):
    """Firms buy inputs toward a few days of planned use."""
    wanted = {
        'f_cement': [('limestone', 52000.), ('fuel', 12000.)],
        'f_dairy': [('milk', 260.)], 'f_feed': [('grain', 1100.)], 'f_slaughter': [('livestock', 70.)],
        'f_brewery': [('grain', 90.)],
    }
    for fid, items in wanted.items():
        f = world.firms.get(fid)
        if not f or f['status'] != 'operating':
            continue
        for good, target in items:
            need = target-f['inventory'].get(good, 0.)
            if need > 0:
                got = sell_island(world, good, [('firm:'+fid, need)], minute)[0]
                f['inventory'][good] = f['inventory'].get(good, 0.)+got
                f['today']['input_cost'] += got*world.markets[good]['price']
    for f in world.firms.values():
        if f['kind'] == 'agriculture' and f['status'] == 'operating':
            need = f['herd']*.012*4-f['inventory'].get('feed', 0.)
            if need > 0:
                got = sell_island(world, 'feed', [('firm:'+f['id'], need)], minute)[0]
                f['inventory']['feed'] = f['inventory'].get('feed', 0.)+got


def sell_local(world, f, orders, minute):
    """A zone service, lodging or ferry: sell up to today's capacity at the firm's price.
    orders: list of (buyer, qty). Returns filled share."""
    demand = sum(q for _, q in orders)
    if f['kind'] in ('services', 'construction'):
        capacity = f['today']['capacity']
    elif f['kind'] == 'port':
        capacity = len(ferry_sailings(minute))*2*FERRY_TRIPS_PER_SAILING
    else:
        capacity = float('inf')
    share = min(1., capacity/demand) if demand > 0 else 1.
    for buyer, qty in orders:
        sold = qty*share
        if sold > 0:
            world.ledger.transfer(buyer, 'firm:'+f['id'], sold*f['price'], 'goods:'+f['output'], minute, f['output'], sold)
            f['today']['sold'] += sold
            f['today']['revenue'] += sold*f['price']
    f['today']['unmet'] += demand*(1-share)
    f['today']['demand'] = f['today'].get('demand', 0.)+demand
    if f['kind'] == 'services':
        # Inputs: off-island goods sold through the shop.
        imports = f['today']['sold']*IMPORT_SHARE['consumer']*1000
        world.ledger.transfer('firm:'+f['id'], 'external', imports, 'import:consumer', minute)
        f['today']['input_cost'] += imports
    return share


def pay_wages(world, minute):
    """Daily wages: employer -> employee POPs, income tax -> region."""
    rest = is_rest_day(minute-1)
    for fid, staff in world.jobs.items():
        f = world.firms[fid]
        if f['status'] != 'operating' and f['status'] != 'construction':
            continue
        sector = f['sector']
        continuous = f['kind'] in ('hospital', 'hospitality', 'cement', 'port', 'dairy', 'public', 'agriculture')
        if rest and not continuous:
            continue
        daily = WAGE[sector]*SHIFT_HOURS*(5/7 if continuous else 1)
        payer = 'region' if f['kind'] in ('public', 'hospital') else 'firm:'+fid
        for pid, n in staff.items():
            if n <= 0:
                continue
            gross = n*daily
            world.ledger.transfer(payer, 'pop:'+pid, gross, 'wages', minute)
            world.ledger.transfer('pop:'+pid, 'region', gross*INCOME_TAX, 'income tax', minute)
            f['today']['wages'] += gross


def close_day(world, minute):
    """Daily bookkeeping, price updates and forecasts."""
    for f in world.firms.values():
        t = f['today']
        f['ema_sales'] = .9*f['ema_sales']+.1*t['sold']
        if f['kind'] in ('services', 'construction') and t['capacity'] > 0:
            util = min(1.5, t.get('demand', 0.)/t['capacity'])
            f['ema_util'] = .93*f['ema_util']+.07*util
            f['price'] = max(.7*GOODS[f['output']][1], min(1.6*GOODS[f['output']][1], f['price']*(1+.01*tanh(4*(util-.85)))))
        elif f['kind'] == 'hospitality':
            util = t.get('demand', 0.)/max(1., f['beds'])
            f['ema_util'] = .93*f['ema_util']+.07*util
            season = .75+.5*util
            f['price'] = max(600., min(1900., .97*f['price']+.03*GOODS['lodging'][1]*season))
        elif f['equipment'] and f['kind'] not in ('hospital', 'port', 'agriculture'):
            hours = sum(1 for did in f['equipment'] if world.devices[did]['p_rated'] > 1)
            f['ema_util'] = .97*f['ema_util']+.03*min(1., t['produced']/max(1e-9, capacity_per_day(f)))
        cost = t['input_cost']+t['wages']+t['power_cost']
        if f['kind'] in ('construction', 'services'):
            cost += t['sold']*IMPORT_SHARE.get(f['output'], 0)*1000 if f['kind'] == 'construction' else 0
        margin = (t['revenue']-cost)/t['revenue'] if t['revenue'] > 0 else (-1. if cost > 0 else 0.)
        if f['kind'] in ('public', 'hospital'):
            margin = 0.
        f['ema_margin'] = .97*f['ema_margin']+.03*max(-1., margin)
        for k in t:
            f['month'][k] = f['month'].get(k, 0.)+t[k]
        f['last_day'] = t
        f['today'] = _blank_day()
    for m in world.markets.values():
        m['last'] = dict(demand=m['demand'], supplied=m['supplied'], imported=m['imported'], exported=m['exported'], unmet=m['unmet'])
        m['demand'] = m['supplied'] = m['imported'] = m['exported'] = m['unmet'] = 0.


def capacity_per_day(f):
    rates = {'cement': (CEMENT_RATE['cmill1']+CEMENT_RATE['cmill2'])*24, 'quarry': QUARRY_RATE.get(f['id'], 180.)*14, 'dairy': 16/6.2*16,
             'feedmill': 12*9, 'slaughter': 2.2/1.65*9, 'brewery': .9*9}
    return rates.get(f['kind'], 1.)


# ---------------------------------------------------------------- labour market
def labour_month(world, minute):
    """Monthly hiring and layoffs. Vacancies are filled from unemployed people of the same sector within
    commuting distance; if none, from other unemployed nearby who retrain."""
    zones = {z['id']: z for z in world.zones}
    for f in world.firms.values():
        if f['status'] != 'operating':
            continue
        f['desired_staff'] = desired_staff(world, f)
    for f in sorted(world.firms.values(), key=lambda f: f['id']):
        if f['status'] != 'operating':
            continue
        staff = world.jobs.setdefault(f['id'], {})
        have = sum(staff.values())
        gap = f['desired_staff']-have
        if gap > 0:
            hire(world, f, int(gap), zones)
        elif gap < -max(2, .04*have):
            fire(world, f, int(min(-gap, .08*have+2)))
        f['staff'] = sum(world.jobs[f['id']].values())


def desired_staff(world, f):
    kind = f['kind']
    if kind == 'services':
        expected = f['ema_sales']*1.15+5
        return max(3, round(expected/(SERVICE_PRODUCTIVITY*8*.62*.85)))
    if kind == 'hospitality':
        guests = world.pops.get(f['zone']+'_tourist', {}).get('count', 0)
        return max(4, round(f['beds']*.035+guests*.11))
    if kind == 'public':
        return max(5, round(world.society_stats['zone_working'].get(f['zone'], 0)*.235))
    if kind == 'agriculture':
        return max(3, round(f['desired_staff'] or 10))
    if kind == 'construction':
        orders = f['ema_sales']+world.construction_backlog/30/1000
        return max(300, round(orders*1.1/(CONSTRUCTION_PRODUCTIVITY*8.4*5/7)))
    return f['desired_staff']


def hire(world, f, n, zones):
    z0 = zones[f['zone']]
    candidates = []
    for pop in world.pops.values():
        if pop['kind'] != 'resident' or pop['group'] not in ('industry', 'agriculture', 'hospitality', 'services', 'public', 'construction'):
            continue
        idle = pop['count']-pop['employed']-pop.get('inactive', 0)
        if idle <= 0:
            continue
        z = zones[pop['zone']]
        dist = hypot(z['x']-z0['x'], z['y']-z0['y'])
        if dist > 40:
            continue
        same = pop['group'] == f['sector']
        candidates.append((0 if same else 1, dist, pop))
    candidates.sort(key=lambda c: (c[0], c[1], c[2]['id']))
    for retrain, _, pop in candidates:
        if n <= 0:
            break
        take = min(n, pop['count']-pop['employed']-pop.get('inactive', 0))
        if retrain:
            take = min(take, max(1, int(.25*take)))
            target = world.pops[f"{pop['zone']}_{f['sector']}"]
            move_people(world, pop, target, take)
            pop = target
        pop['employed'] += take
        world.jobs[f['id']][pop['id']] = world.jobs[f['id']].get(pop['id'], 0)+take
        n -= take
    if n > 0 and f['kind'] == 'hospitality':
        seasonal = world.pops.get(f['zone']+'_seasonal')
        if seasonal is not None and 140 <= parts(world.minute)['doy'] < 240:
            seasonal['count'] += n
            seasonal['employed'] += n
            world.demography['month']['seasonal_in'] += n
            world.jobs[f['id']][seasonal['id']] = world.jobs[f['id']].get(seasonal['id'], 0)+n


def move_people(world, src, dst, k):
    """Move k people (not employed ones) between POPs, with their share of the POP's money."""
    if k <= 0 or src['count'] <= 0:
        return
    share = world.ledger.balance('pop:'+src['id'])*k/src['count']
    src['count'] -= k
    dst['count'] += k
    if share:
        world.ledger.transfer('pop:'+src['id'], 'pop:'+dst['id'], share, 'household moves', world.minute)
    if 'inactive' in src:
        src['inactive'] = max(0, min(src['inactive'], src['count']-src['employed']))


def fire(world, f, n):
    staff = world.jobs[f['id']]
    for pid in sorted(staff, key=lambda p: (world.pops[p]['kind'] != 'seasonal', -staff[p])):
        if n <= 0:
            break
        take = min(n, staff[pid])
        staff[pid] -= take
        world.pops[pid]['employed'] -= take
        if world.pops[pid]['kind'] == 'seasonal':
            world.pops[pid]['count'] -= take
            world.demography['month']['seasonal_out'] += take
        n -= take
        if staff[pid] == 0:
            del staff[pid]


# ---------------------------------------------------------------- investment
def invest_month(world, minute):
    """Firms expand after sustained high utilisation and margins; shrink after sustained losses.
    Hysteresis: several months in a row, and a cooldown after each decision."""
    for f in world.firms.values():
        if f['status'] != 'operating' or f['kind'] in ('public', 'hospital', 'port', 'agriculture'):
            continue
        util, margin = f['ema_util'], f['ema_margin']
        reliability = 1-min(1., world.zone_outage_hours(f['zone'])/48)
        f['months_high'] = f['months_high']+1 if util > .9 and margin > .06 and reliability > .5 else 0
        f['months_low'] = f['months_low']+1 if util < .35 and margin < -.05 else 0
        if f.get('cooldown', 0) > 0:
            f['cooldown'] -= 1
            continue
        if f['months_high'] >= 4:
            capex = expansion_cost(f)
            if world.ledger.balance('firm:'+f['id']) > .3*capex:
                world.start_firm_expansion(f, capex)
                f['cooldown'], f['months_high'] = 12, 0
        elif f['months_low'] >= 8:
            f['capacity_factor'] = max(.5, f['capacity_factor']*.85)
            for did in f['equipment']:
                world.devices[did]['p_rated'] *= .85
            f['cooldown'], f['months_low'] = 12, 0
            world.log('economy', f"{f['name']} cuts capacity after months of losses", f['zone'], firm=f['id'])


def expansion_cost(f):
    return {'services': 6e6, 'hospitality': 25e6, 'construction': 10e6}.get(f['kind'], 60e6)
