"""Society Model: spatial POPs with probabilistic transitions (spec section 4).

A POP is a group of people with a count, not a person. Residents are grouped by home zone and
occupation (six labour sectors, plus 'retired' and 'youth'). Tourists, holiday-home users and seasonal
workers are POPs too and count toward the 10,000-object cap. Money is held in ledger accounts
'pop:<id>'. Daily: income, transfers and consumption intents (necessities first, then discretionary
spending by preference and price). Tourism follows arrivals, stays and departures. Monthly:
births, deaths, ageing and logit migration with housing limits; every change of people is counted.
"""
from math import exp, hypot
from . import economy as E
from .calendar import parts, is_rest_day
from .loads import bump
from .params import (CHILD_DAY, EMIGRATION_RATE, EMIGRATION_RATE_RETIRED, FAMILY_SUPPORT_DAY, HOLIDAY_PERSONS, HOUSEHOLD_SIZE, HOUSING_DAY,
                     IMMIGRATION_PER_YEAR, MOVE_RATE, OTHER_EXTERNAL_DAY, PENSION_DAY, POP_CAP, SECTORS, STAY_DAYS,
                     STUDY_LEAVE_SHARE, UNEMPLOYED_EXIT,
                     TOURIST_BUDGET_DAY, UNEMPLOYMENT_DAY, VISITORS_PER_YEAR, BIRTH_RATE, DEATH_RATE, WAGE, SHIFT_HOURS,
                     INCOME_TAX, HOUSING_LOCAL_SHARE, PUBLIC_WORKS_DAY, MOVING_WEALTH)

GROUPS = SECTORS+('retired', 'youth')
PREFERENCES = dict(consumer=.30, food=.0021)      # baskets and tonnes per person and day at reference prices


def pop(pid, kind, zone, group, count, **extra):
    return dict(id=pid, kind=kind, zone=zone, group=group, count=int(count), employed=0, income_ema=0.,
                prefs=dict(consumer=1.0, food=1.0), elasticity=.6, inertia=.9, provenance='synthetic', **extra)


def residents(world, zone=None):
    return sum(p['count'] for p in world.pops.values() if p['kind'] == 'resident' and (zone is None or p['zone'] == zone))


def stochastic_round(rng, x):
    n = int(x)
    return n+(1 if rng.random() < x-n else 0)


def check_cap(world):
    if len(world.pops) > POP_CAP:
        raise RuntimeError(f'POP cap exceeded: {len(world.pops)} > {POP_CAP}')


# ---------------------------------------------------------------- statistics used by other models
def refresh_stats(world):
    zw, zr, zt, zh, zs, zu = {}, {}, {}, {}, {}, {}
    for p in world.pops.values():
        z = p['zone']
        if p['kind'] == 'resident':
            zr[z] = zr.get(z, 0)+p['count']
            if p['group'] in SECTORS:
                zw[z] = zw.get(z, 0)+p['count']
                zu[z] = zu.get(z, 0)+p['count']-p['employed']-p.get('inactive', 0)
        elif p['kind'] == 'tourist':
            zt[z] = zt.get(z, 0)+p['count']
        elif p['kind'] == 'holiday':
            zh[z] = zh.get(z, 0)+p['count']
        elif p['kind'] == 'seasonal':
            zs[z] = zs.get(z, 0)+p['count']
    world.society_stats = dict(zone_residents=zr, zone_working=zw, zone_unemployed=zu, zone_tourists=zt,
                               zone_holiday=zh, zone_seasonal=zs)


def household_scale(world, zone):
    """Occupied-household equivalents in a zone, the size driver of its residential load."""
    st = world.society_stats
    return (st['zone_residents'].get(zone['id'], 0)/HOUSEHOLD_SIZE+st['zone_holiday'].get(zone['id'], 0)/HOLIDAY_PERSONS
            + st['zone_seasonal'].get(zone['id'], 0)/2.)


def heated_households(world, zone):
    st = world.society_stats
    holiday_present = st['zone_holiday'].get(zone['id'], 0)/HOLIDAY_PERSONS
    return st['zone_residents'].get(zone['id'], 0)/HOUSEHOLD_SIZE+.25*zone['holiday_homes']+.75*holiday_present


# ---------------------------------------------------------------- tourism
def season(doy):
    return .22+3.1*bump(doy/365*24, 196/365*24, 27/365*24)+.55*bump(doy/365*24, 171/365*24, 4/365*24) \
        + .25*bump(doy/365*24, 358/365*24, 5/365*24)+.2*bump(doy/365*24, 100/365*24, 6/365*24)


_SEASON_NORM = sum(season(d) for d in range(365))


def holiday_occupancy(minute):
    p = parts(minute)
    doy, wd = p['doy'], p['weekday']
    summer = bump(doy/365*24, 200/365*24, 24/365*24)
    weekend = (.10+.15*bump(doy/365*24, 190/365*24, 60/365*24)) if wd >= 4 else 0.
    return min(.95, .04+.72*summer+weekend+.2*bump(doy/365*24, 358/365*24, 5/365*24))


def tourism_day(world, minute):
    """Departures, then arrivals for the day starting at `minute`, limited by beds and ferry seats."""
    rng = world.streams['tourism']
    p = parts(minute)
    doy, wd = p['doy'], p['weekday']
    w = world.forecast(minute, minute+14*60)
    weather = 1+.22*max(-1., min(1., (w['temperature_c']-17)/6))-.25*max(0., w['cloud_fraction']-.6)
    weekday = (.85, .85, .9, 1.0, 1.45, 1.2, .75)[wd]
    hosp = [f for f in world.firms.values() if f['kind'] == 'hospitality' and f['status'] == 'operating']
    avg_price = sum(f['price'] for f in hosp)/max(1, len(hosp))
    price = (avg_price/980.)**-.8
    island_arrivals = VISITORS_PER_YEAR*season(doy)/_SEASON_NORM*weekday*weather*price
    ferry = world.firms.get('f_port')
    seats = len(E.ferry_sailings(minute))*E.FERRY_TRIPS_PER_SAILING*.8 if ferry and ferry['status'] == 'operating' else 0
    island_arrivals = min(island_arrivals, seats)
    total_beds = sum(f['beds'] for f in hosp) or 1
    demo = world.demography['month']
    for f in hosp:
        tp = world.pops[f['zone']+'_tourist']
        leaving = stochastic_round(rng, tp['count']/STAY_DAYS)
        tp['count'] -= leaving
        demo['tourist_departures'] += leaving
        tp['departing'] = leaving
        wish = island_arrivals*f['beds']/total_beds*(.7+.6*world.zone_by_id[f['zone']]['amenity'])
        free = max(0, f['beds']-tp['count'])
        arriving = min(stochastic_round(rng, wish), free)
        tp['count'] += arriving
        tp['arrived'] = arriving
        tp['turned_away'] = max(0, stochastic_round(rng, wish)-arriving)
        demo['tourist_arrivals'] += arriving
        demo['tourists_turned_away'] += tp['turned_away']
    occ = holiday_occupancy(minute)
    for z in world.zones:
        hp = world.pops[z['id']+'_holiday']
        target = int(z['holiday_homes']*occ*HOLIDAY_PERSONS)
        change = target-hp['count']
        demo['holiday_in' if change > 0 else 'holiday_out'] += abs(change)
        hp['count'] = target


# ---------------------------------------------------------------- daily money
def daily(world, minute):
    """Income transfers and the day's purchases (settled at the end of the day just finished)."""
    led = world.ledger
    rng = world.streams['society']
    zones_services = {f['zone']: f for f in world.firms.values() if f['kind'] == 'services' and f['status'] == 'operating'}
    hosp = {f['zone']: f for f in world.firms.values() if f['kind'] == 'hospitality' and f['status'] == 'operating'}
    consumer_orders = {}     # zone -> list of (buyer, baskets)
    food_orders = []
    lodging_orders = {}
    construction_orders = []
    youth_by_zone = {}
    for p in world.pops.values():
        if p['kind'] == 'resident' and p['group'] == 'youth':
            youth_by_zone[p['zone']] = p
    workers_by_zone = {}
    for p in world.pops.values():
        if p['kind'] == 'resident' and p['group'] in SECTORS:
            workers_by_zone.setdefault(p['zone'], []).append(p)
    # Transfers from the region (pensions, child and unemployment benefits) and within families.
    for p in sorted(world.pops.values(), key=lambda p: p['id']):
        n = p['count']
        if n <= 0 or p['kind'] != 'resident':
            continue
        acc = 'pop:'+p['id']
        if p['group'] == 'retired':
            led.transfer('region', acc, n*PENSION_DAY, 'pensions', minute)
        elif p['group'] == 'youth':
            led.transfer('region', acc, n*CHILD_DAY, 'child benefit', minute)
            workers = workers_by_zone.get(p['zone'], [])
            employed = sum(w['employed'] for w in workers) or 1
            for w in workers:
                led.transfer('pop:'+w['id'], acc, n*FAMILY_SUPPORT_DAY*w['employed']/employed, 'family support', minute)
        else:
            inactive = p.get('inactive', 0)
            unemployed = n-p['employed']-inactive
            if unemployed > 0:
                led.transfer('region', acc, unemployed*UNEMPLOYMENT_DAY, 'unemployment benefit', minute)
            if inactive > 0:
                led.transfer('region', acc, inactive*UNEMPLOYMENT_DAY*.7, 'student and sickness benefit', minute)
    # Spending: necessities first, discretionary from what is left, scaled by income and price.
    for p in sorted(world.pops.values(), key=lambda p: p['id']):
        n = p['count']
        if n <= 0:
            continue
        acc = 'pop:'+p['id']
        zone = p['zone']
        if p['kind'] in ('tourist', 'holiday'):
            nights = n if p['kind'] == 'tourist' else 0
            budget = n*TOURIST_BUDGET_DAY*(1. if p['kind'] == 'tourist' else .45)
            h = hosp.get(zone)
            lodging = nights*(h['price'] if h else 0.)
            led.transfer('external', acc, budget+lodging, 'visitor spending', minute)
            if h and nights:
                lodging_orders.setdefault(zone, []).append((acc, nights))
            consumer_orders.setdefault(zone, []).append((acc, budget/1000*.62))
            food_orders.append((acc, n*.0004))
            if p['kind'] == 'tourist':
                trips = p.get('arrived', 0)+p.get('departing', 0)
                if trips and 'f_port' in world.firms:
                    led.transfer('external', acc, trips*world.firms['f_port']['price'], 'visitor spending', minute)
                    world.ferry_orders.append((acc, trips))
            continue
        balance = led.balance(acc)
        child = p['group'] == 'youth'
        housing = 0. if child else n*HOUSING_DAY*(.4 if p['kind'] == 'seasonal' else 1.)
        necessities = housing+n*(30. if child else OTHER_EXTERNAL_DAY)
        food_price = world.markets['food']['price']
        food_qty = n*PREFERENCES['food']*p['prefs']['food']
        income = p['income_ema']/max(1, n)
        affordable = max(0., balance+income*n*.5)
        scale = min(1., affordable/max(1., necessities+food_qty*food_price))
        led.transfer(acc, 'external', (necessities-housing*HOUSING_LOCAL_SHARE)*scale, 'housing and off-island spending', minute)
        if housing:
            construction_orders.append((acc, housing*HOUSING_LOCAL_SHARE*scale/1000))
        food_orders.append((acc, food_qty*scale))
        left = balance-necessities*scale-food_qty*food_price*scale
        wealth_days = left/max(1., income*n) if income > 0 else 0.
        services = zones_services.get(zone)
        price = services['price'] if services else 1000.
        baskets = n*PREFERENCES['consumer']*(.45 if child else 1.)*p['prefs']['consumer']*max(.25, min(1.8, (income/650)**.7))*(price/1000)**-p['elasticity']
        baskets *= max(.3, min(1.15, .55+wealth_days/60))
        baskets = max(0., min(baskets, max(0., left)/price*.9))
        if p['zone'] not in ('z01', 'z03') and baskets > 0:
            # Shopping trips to the main town's centre (Östercentrum).
            consumer_orders.setdefault('z03', []).append((acc, baskets*.22))
            baskets *= .78
        consumer_orders.setdefault(zone, []).append((acc, baskets))
    world.lodging_orders = lodging_orders
    world.consumer_orders = consumer_orders
    world.food_orders = food_orders
    world.construction_orders = construction_orders+[('region', PUBLIC_WORKS_DAY/1000)]


def record_income(world):
    """Update each POP's income EMA from the expected daily income (for spending decisions)."""
    for p in world.pops.values():
        n = p['count']
        if n <= 0 or p['kind'] in ('tourist', 'holiday'):
            continue
        if p['group'] in SECTORS:
            wage = WAGE[p['group']]*SHIFT_HOURS*(1-INCOME_TAX)*5/7
            inactive = p.get('inactive', 0)
            income = p['employed']*wage+(n-p['employed']-inactive)*UNEMPLOYMENT_DAY+inactive*UNEMPLOYMENT_DAY*.7
        elif p['group'] == 'retired':
            income = n*PENSION_DAY
        else:
            income = n*(CHILD_DAY+FAMILY_SUPPORT_DAY)
        p['income_ema'] = .9*p['income_ema']+.1*income if p['income_ema'] else income


# ---------------------------------------------------------------- monthly demography and migration
def monthly(world, minute):
    rng = world.streams['society']
    demo = world.demography['month']
    zones = world.zones
    zmap = world.zone_by_id
    st = world.society_stats
    # Births and deaths.
    for z in zones:
        zr = st['zone_residents'].get(z['id'], 0)
        births = stochastic_round(rng, zr*BIRTH_RATE/12)
        world.pops[z['id']+'_youth']['count'] += births
        demo['births'] += births
    for p in sorted(world.pops.values(), key=lambda p: p['id']):
        if p['kind'] != 'resident' or p['count'] <= 0:
            continue
        rate = {'retired': .043, 'youth': .0003}.get(p['group'], .0016)
        deaths = min(p['count'], stochastic_round(rng, p['count']*rate/12))
        remove_people(world, p, deaths)
        demo['deaths'] += deaths
    # Ageing: some school leavers go to the mainland, the rest enter the labour force as job seekers;
    # workers retire.
    for z in zones:
        youth = world.pops[z['id']+'_youth']
        n = min(youth['count'], stochastic_round(rng, youth['count']/(19*12)))
        away = min(n, stochastic_round(rng, n*STUDY_LEAVE_SHARE))
        emigrate(world, youth, away, minute)
        if n-away:
            E.move_people(world, youth, world.pops[f"{z['id']}_{best_sector(world, z['id'])}"], n-away)
        retired = world.pops[z['id']+'_retired']
        for g in SECTORS:
            p = world.pops[f"{z['id']}_{g}"]
            k = min(p['count'], stochastic_round(rng, p['count']/(46*12)))
            if k:
                leave_jobs(world, p, k)
                E.move_people(world, p, retired, k)
    # Off-island moves: life events for everyone, plus the push of unemployment and outages.
    utilities = zone_utilities(world)
    for p in sorted(world.pops.values(), key=lambda p: p['id']):
        if p['kind'] != 'resident' or p['group'] == 'youth' or p['count'] <= 0:
            continue
        outage_push = min(.01, world.zone_outage_hours(p['zone'], 90)/2500)
        base = (EMIGRATION_RATE_RETIRED if p['group'] == 'retired' else EMIGRATION_RATE)/12
        emigrate(world, p, stochastic_round(rng, p['count']*(base+outage_push/2)), minute)
        if p['group'] in SECTORS:
            unemployed = p['count']-p['employed']-p.get('inactive', 0)
            emigrate(world, p, stochastic_round(rng, max(0, unemployed)*UNEMPLOYED_EXIT/12), minute, prefer_unemployed=True)
    # Moves within the island, by logit over zones with free housing.
    for p in sorted(world.pops.values(), key=lambda p: p['id']):
        if p['kind'] != 'resident' or p['group'] == 'youth' or p['count'] <= 0:
            continue
        unemployed = p['count']-p['employed']-p.get('inactive', 0)
        outage_push = min(.01, world.zone_outage_hours(p['zone'], 90)/2500)
        rate = MOVE_RATE/12*(.25 if p['group'] == 'retired' else 1)
        movers = stochastic_round(rng, unemployed*(rate*3)+p['employed']*rate*.15+p['count']*outage_push)
        movers = min(movers, p['count'])
        if movers <= 0:
            continue
        here = utilities.get((p['zone'], p['group']), 0.)
        weights = []
        for z in zones:
            if z['id'] == p['zone']:
                continue
            u = utilities.get((z['id'], p['group']), 0.)
            free = housing_free(world, z)
            if free <= 0:
                continue
            weights.append((z['id'], u))
        top = max([u for _, u in weights]+[here])
        probs = [(zid, exp((u-top)/.35)) for zid, u in weights]
        probs.append(('stay', exp((here+.4-top)/.35)))
        total = sum(w for _, w in probs)
        for zid, w in probs:
            k = min(p['count'], stochastic_round(rng, movers*w/total))
            if k <= 0 or zid == 'stay':
                continue
            k = min(k, int(housing_free(world, zmap[zid])*HOUSEHOLD_SIZE))
            if k <= 0:
                continue
            leave_jobs(world, p, k, prefer_unemployed=True)
            E.move_people(world, p, world.pops[f"{zid}_{p['group']}"], k)
            demo['internal_moves'] += k
    # Immigration from the mainland, attracted by vacancies.
    vac = sum(max(0, f['desired_staff']-f['staff']) for f in world.firms.values() if f['status'] == 'operating')
    labour = sum(st['zone_working'].values()) or 1
    unemployment = sum(st['zone_unemployed'].values())/labour
    inflow = stochastic_round(rng, IMMIGRATION_PER_YEAR/12*min(2.5, max(.15, 1+4*vac/labour-6*max(0., unemployment-.05))))
    candidates = [(z, utilities.get((z['id'], 'services'), 0.)) for z in zones if housing_free(world, z) > 0]
    if candidates and inflow:
        top = max(u for _, u in candidates)
        total = sum(exp((u-top)/.35) for _, u in candidates)
        for z, u in candidates:
            k = stochastic_round(rng, inflow*exp((u-top)/.35)/total)
            k = min(k, int(housing_free(world, z)*HOUSEHOLD_SIZE))
            if k > 0:
                sector = best_sector(world, z['id'])
                target = world.pops[f"{z['id']}_{sector}"]
                target['count'] += k
                world.ledger.transfer('external', 'pop:'+target['id'], k*MOVING_WEALTH, 'immigration', minute)
                demo['immigration'] += k
    for p in world.pops.values():
        if 'inactive' in p:
            p['inactive'] = max(0, min(round(p['count']*.14), p['count']-p['employed']))
    refresh_stats(world)
    check_cap(world)


def emigrate(world, p, k, minute, prefer_unemployed=False):
    """k people of a POP leave for the mainland, taking their share of its money."""
    k = min(k, p['count'])
    if k <= 0:
        return
    leave_jobs(world, p, k, prefer_unemployed)
    share = world.ledger.balance('pop:'+p['id'])*k/p['count']
    world.ledger.transfer('pop:'+p['id'], 'external', share, 'emigration', minute)
    p['count'] -= k
    world.demography['month']['emigration'] += k


def leave_jobs(world, p, k, prefer_unemployed=False):
    """Before k people leave a POP, the employed among them give up their jobs."""
    if k <= 0:
        return
    unemployed = p['count']-p['employed']-p.get('inactive', 0)
    from_employed = max(0, k-unemployed) if prefer_unemployed else (round(k*p['employed']/p['count']) if p['count'] else 0)
    if from_employed:
        release_jobs(world, p, min(from_employed, p['employed']))


def remove_people(world, p, k, prefer_unemployed=False):
    """Take k people out of a POP; employed people taken leave their jobs."""
    if k <= 0:
        return
    unemployed = p['count']-p['employed']-p.get('inactive', 0)
    if prefer_unemployed:
        from_employed = max(0, k-unemployed)
    else:
        from_employed = round(k*p['employed']/p['count']) if p['count'] else 0
    p['count'] -= k
    if from_employed:
        release_jobs(world, p, from_employed)
    if 'inactive' in p:
        p['inactive'] = min(p['inactive'], p['count']-p['employed'])


def release_jobs(world, p, k):
    for fid in sorted(world.jobs, key=lambda f: -world.jobs[f].get(p['id'], 0)):
        if k <= 0:
            break
        n = world.jobs[fid].get(p['id'], 0)
        if n:
            take = min(n, k)
            world.jobs[fid][p['id']] = n-take
            if world.jobs[fid][p['id']] == 0:
                del world.jobs[fid][p['id']]
            world.firms[fid]['staff'] -= take
            p['employed'] -= take
            k -= take


def best_sector(world, zone_id):
    """Sector where a newcomer or school leaver in this zone is most likely to find work."""
    best, gap = 'services', -1
    for f in world.firms.values():
        if f['status'] != 'operating':
            continue
        z = world.zone_by_id[f['zone']]
        z0 = world.zone_by_id[zone_id]
        if hypot(z['x']-z0['x'], z['y']-z0['y']) > 35:
            continue
        g = f['desired_staff']-f['staff']
        if g > gap:
            best, gap = f['sector'], g
    return best


def housing_free(world, z):
    households = world.society_stats['zone_residents'].get(z['id'], 0)/HOUSEHOLD_SIZE
    return z['housing_units']-households


def zone_utilities(world):
    """Attractiveness of each zone for each group: jobs, wages, housing, commuting, amenities, outages."""
    st = world.society_stats
    out = {}
    jobs_near = {}
    for z in world.zones:
        open_jobs, staff = {}, {}
        for f in world.firms.values():
            if f['status'] != 'operating':
                continue
            fz = world.zone_by_id[f['zone']]
            d = hypot(fz['x']-z['x'], fz['y']-z['y'])
            if d > 35:
                continue
            w = exp(-d/18)
            open_jobs[f['sector']] = open_jobs.get(f['sector'], 0)+w*max(0, f['desired_staff']-f['staff'])
            staff[f['sector']] = staff.get(f['sector'], 0)+w*f['staff']
        jobs_near[z['id']] = (open_jobs, staff)
    for z in world.zones:
        open_jobs, staff = jobs_near[z['id']]
        households = st['zone_residents'].get(z['id'], 0)/HOUSEHOLD_SIZE
        tight = households/max(1, z['housing_units'])
        outage = world.zone_outage_hours(z['id'], 90)
        for g in GROUPS:
            jobs = (open_jobs.get(g, 0)+.2*staff.get(g, 0)**.5)/(1+st['zone_unemployed'].get(z['id'], 0)**.5)
            u = (.9*min(2., jobs/10) if g in SECTORS else 0.)+.7*z['amenity']-1.2*max(0., tight-.97)-.06*outage/24
            out[(z['id'], g)] = u
    return out
