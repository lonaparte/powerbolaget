"""Energy model operations: wind, automatic dispatch, storage, protection and faults (spec section 6).

Every turbine is its own device with a power curve, availability, faults and maintenance; wakes inside
a farm follow the Jensen (Park) engineering model. Each minute the automatic operator balances the
island: the mainland link (two HVDC poles) is the slack within its rating, batteries shave peaks and
arbitrage prices, surplus wind is curtailed and, as a last resort, load is shed by priority class. The
AC power flow (OpenDSS through app.solvers) then gives voltages, flows and losses. Protection acts on
faults, overloads and voltage; a non-converged power flow is reported as a numerical failure, never
as a blackout.
"""
from math import exp, log, radians, sin, cos, sqrt
from .windfield import hub_speed
from . import grid as G
from .island import TURBINE_MODELS
from .calendar import parts

AIR = 1.225
WAKE_K = .075
# Failures per year (assumptions): per 100 km for lines, per unit otherwise.
FAULT_RATE = {'OHL110': 2.2, 'OHL20': 6.0, 'CAB110': .6, 'CAB20': 1.2, 'CAB33': 1.2, 'CAB220': .15, 'transformer': .02,
              'turbine_minor': 2.5, 'turbine_major': .15, 'pole': 1.0, 'storage': .4}
TRANSIENT_SHARE = {'OHL110': .75, 'OHL20': .65}
REPAIR_HOURS = {'OHL110': (6, 30), 'OHL20': (3, 12), 'CAB110': (72, 400), 'CAB20': (24, 120), 'CAB33': (24, 150), 'CAB220': (240, 1500),
                'transformer': (120, 720), 'turbine_minor': (8, 60), 'turbine_major': (200, 900), 'pole': (6, 72),
                'storage': (24, 240)}


# ---------------------------------------------------------------- wind
def power_curve(model, v, density):
    m = TURBINE_MODELS[model]
    if v < m['cut_in'] or v >= m['cut_out']:
        return 0.
    if v >= m['rated_speed']:
        return m['mw']
    frac = (v**3-m['cut_in']**3)/(m['rated_speed']**3-m['cut_in']**3)
    return m['mw']*min(1., frac*density/AIR)


def capacity_factor(model, mean_hub, k=2.2, density=1.225):
    """Expected share of rated output at a site with this mean hub wind, for Weibull-distributed winds
    (shape 2.2), before wakes, outages and curtailment."""
    from math import gamma
    scale = mean_hub/gamma(1+1/k)
    total, step = 0., .1
    for i in range(1, 320):
        v = i*step
        pdf = k/scale*(v/scale)**(k-1)*exp(-(v/scale)**k)
        total += power_curve(model, v, density)*pdf*step
    return total/TURBINE_MODELS[model]['mw']


def thrust(model, v):
    m = TURBINE_MODELS[model]
    if v < m['cut_in'] or v >= m['cut_out']:
        return 0.
    return min(.8, .8*(m['rated_speed']/max(v, .1))**2.6)


_wake_cache = {}


def wake_factors(grid, farm_id, direction, ct):
    """Speed factor for each turbine of a farm: Jensen top-hat wakes, root-sum-square superposition."""
    geometry=hash(tuple((tid,grid['turbines'][tid]['x'],grid['turbines'][tid]['y'],grid['turbines'][tid]['rotor'],grid['turbines'][tid]['status'])
                        for tid in grid['farms'][farm_id]['turbines']))
    key = (farm_id, round(direction), round(ct, 2), grid.get('version', 0),geometry)
    hit = _wake_cache.get(key)
    if hit is not None:
        return hit
    ids = [t for t in grid['farms'][farm_id]['turbines'] if grid['turbines'][t]['status'] not in ('construction','retired')]
    heading = radians(direction+180)
    hx, hy = sin(heading), cos(heading)
    out = {}
    for j in ids:
        tj = grid['turbines'][j]
        total = 0.
        for i in ids:
            if i == j:
                continue
            ti = grid['turbines'][i]
            dx, dy = (tj['x']-ti['x'])*1000, (tj['y']-ti['y'])*1000
            x = dx*hx+dy*hy
            if x <= 0:
                continue
            r = abs(-dx*hy+dy*hx)
            R = ti['rotor']/2
            Rw = R+WAKE_K*x
            if r >= Rw+R:
                continue
            overlap = 1. if r <= Rw-R else (Rw+R-r)/(2*R)
            total += ((1-sqrt(1-ct))*(R/Rw)**2*overlap)**2
        out[j] = max(.3, 1-sqrt(total))
    if len(_wake_cache) > 20000:
        _wake_cache.clear()
    _wake_cache[key] = out
    return out


def available_wind(world, t, w):
    """Available power of each turbine (MW) and its hub wind speed, before curtailment."""
    grid = world.grid
    out = {}
    for farm_id, farm in grid['farms'].items():
        ids = farm['turbines']
        if not ids:
            continue
        sample = grid['turbines'][ids[0]]
        v_ref = hub(sample, w, t, world.seed)
        factors = wake_factors(grid, farm_id, w['direction_deg'], thrust(sample['model'], v_ref))
        for tid in ids:
            tb = grid['turbines'][tid]
            if tb['status'] == 'construction':
                continue
            v = hub(tb, w, t, world.seed)*factors.get(tid, 1.)
            tb['v'] = v
            if tb['status'] != 'ok' or tb['grid_wait'] > t:
                out[tid] = 0.
                continue
            if v >= TURBINE_MODELS[tb['model']]['cut_out']:
                tb['high_wind'] = True
            elif tb.get('high_wind') and v < TURBINE_MODELS[tb['model']]['cut_out']-3:
                tb['high_wind'] = False
            iced = w['icing_risk'] > .55
            out[tid] = 0. if tb.get('high_wind') or iced else power_curve(tb['model'], v, w['density'])
    return out


def hub(tb, w, t, seed):
    return hub_speed(w, tb['hub'], tb['x'], tb['y'], t/1440, seed)


# ---------------------------------------------------------------- dispatch
def hvdc_capacity(world):
    poles = [p for p in world.grid['link']['poles'] if p['status'] == 'ok']
    branch = world.grid['branches']['hvdc']
    if not G.in_service(branch):
        return 0.
    return sum(p['mw'] for p in poles)


def hvac_capacity(world):
    ac = world.grid.get('hvac')
    if not ac or not G.hvac_active(world.grid):
        return 0.
    cables = sum(1 for c in ac['cables'] if G.in_service(world.grid['branches'][c]))
    return min(ac['capacity'], ac['cable_mw']*cables)


def link_capacity(world):
    return hvdc_capacity(world)+hvac_capacity(world)


def sync_formers(world, t):
    """Select a qualified reference when connections fail; capacity/SOC still limit dispatch."""
    units=G.forming_units(world.grid)
    islanded=link_capacity(world)<=0
    candidates=[u for u in units if u['grid_forming'] and u['status']=='ok' and
                (u.get('soc',0.)>.05 or (u.get('state')=='running' and u.get('fuel_mwh',0.)>0))]
    active=next((u for u in candidates if u.get('forming_active')),None)
    chosen=(active or max(candidates,key=lambda s:s['p_mw'],default=None)) if islanded else None
    for u in units:
        enable=chosen is u
        if bool(u.get('forming_active'))!=enable:
            world.network.set_forming(u['id'],enable)
            world.log('protection',f"{u['name']} {'takes over' if enable else 'releases'} voltage/frequency reference",None,source=u['id'])
            if enable:
                from . import dynamics as D
                D.start(world,t,'island reference takeover '+u['id'])
    if chosen:
        for tb in world.grid['turbines'].values():
            if tb['grid_wait']>=1e12 and tb['bus_lv'] in world.network.energized:
                tb['grid_wait']=t+8


def dispatch(world, t, requests, avail):
    """Decide served fractions, turbine set points and storage power for one minute.
    requests: {device: (P, Q)}; avail: {turbine: MW}. Returns (served, turbine_mw, storage_mw)."""
    grid, devices = world.grid, world.devices
    energized = world.network.energized
    settings = world.settings
    served = {}
    load = 0.
    by_class = {}
    # Customers on an isolated faulted feeder section wait for the repair crew.
    for did, (p, q) in requests.items():
        d = devices[did]
        if d['bus'] not in energized:
            served[did] = 0.
            continue
        served[did] = 1.
        load += p*served[did]
        by_class.setdefault(d['priority'], []).append(did)
    wind = {tid: p for tid, p in avail.items() if grid['turbines'][tid]['bus_lv'] in energized}
    for tid in avail:
        if tid not in wind:
            avail[tid] = 0.
    if world.frequency_hz>50.2:
        factor=max(0.,1.-(world.frequency_hz-50.2)/1.3)
        wind={k:p*factor for k,p in wind.items()}
    if settings.get('frequency_shed'):
        shed(by_class,requests,served,load*settings['frequency_shed'])
        load=sum(requests[k][0]*share for k,share in served.items())
    w_total = sum(wind.values())
    losses = world.last_losses if world.last_losses else .02*load
    cap = link_capacity(world)
    margin = settings['link_margin']
    imp_cap, exp_cap = cap*(1-margin), cap*(1-margin)
    islanded = cap <= 0
    storage = {sid: s for sid, s in grid['storage'].items() if s['status'] == 'ok' and s['bus'] in energized}
    st_mw = {sid: 0. for sid in grid['storage']}
    oil=sum(g['p'] for g in grid.get('oil',{}).values() if g['status']=='ok' and g['state']=='running'
            and not g.get('forming_active') and g['bus'] in energized)
    need = load+losses-w_total-oil
    price, avg = world.energy_price(t), world.price_avg
    for sid, s in storage.items():
        st_mw[sid] = storage_setpoint(s, need, imp_cap, exp_cap, price, avg, islanded)
        need-=st_mw[sid]
    need+=sum(st_mw.values())
    engine = next((s for s in grid.get('oil',{}).values() if s.get('forming_active')),None)
    former = next((sid for sid, s in storage.items() if s.get('forming_active')), None)
    if islanded and former:
        # The grid-forming battery is the island's slack: it covers the residual within its limits.
        s = storage[former]
        residual = need-sum(v for k, v in st_mw.items() if k != former)
        dis_max = discharge_limit(s)
        ch_max = charge_limit(s)
        st_mw[former] = 0.
        if residual > dis_max:
            shed(by_class, requests, served, residual-dis_max)
        elif residual < -ch_max:
            curtail(wind, -ch_max-residual)
        link = 0.
    elif islanded and engine:
        residual=need-sum(st_mw.values())
        maximum=min(engine['p_mw'],engine['fuel_mwh']*engine['eff']*60)
        minimum=.2*engine['p_mw']
        if residual>maximum:
            shed(by_class,requests,served,residual-maximum)
        elif residual<minimum:
            curtail(wind,minimum-residual)
        link=0.
    elif islanded:
        link = 0.
    else:
        link = need-sum(st_mw.values())
        if link > imp_cap:
            extra = link-imp_cap
            for sid, s in storage.items():
                more = min(extra, discharge_limit(s)-st_mw[sid])
                if more > 0:
                    st_mw[sid] += more
                    extra -= more
            if extra > 1e-6:
                shed(by_class, requests, served, extra)
        elif link < -exp_cap:
            extra = -exp_cap-link
            for sid, s in storage.items():
                more = min(extra, charge_limit(s)+st_mw[sid])
                if more > 0:
                    st_mw[sid] -= more
                    extra -= more
            if extra > 1e-6:
                curtail(wind, extra)
    for tid in avail:
        avail[tid] = wind.get(tid, 0.)
    # With the AC link in service the HVDC is scheduled: it carries its share of the exchange, the AC
    # link (the slack) the rest.
    world.hvdc_setpoint = 0.
    if not islanded and world.grid['source_bus'] == 'mainland_ac':
        dc = hvdc_capacity(world)
        world.hvdc_setpoint = max(-dc, min(dc, link*dc/max(1e-9, cap)))
    return served, avail, st_mw


def storage_setpoint(s, need, imp_cap, exp_cap, price, avg, islanded):
    mode = s['mode']
    if mode == 'hold':
        return 0.
    if islanded:
        if s.get('forming_active'):
            return 0.
        return min(discharge_limit(s),max(0.,need)) if need>=0 else -min(charge_limit(s),-need)
    if mode == 'charge':
        return -min(s['setpoint'], charge_limit(s))
    if mode == 'discharge':
        return min(s['setpoint'], discharge_limit(s))
    reserve = .35 if s['grid_forming'] else .12
    p = 0.
    if need > .82*imp_cap:
        p = min(discharge_limit(s, reserve), need-.82*imp_cap)
    elif need < -.85*exp_cap:
        p = -min(charge_limit(s), -.85*exp_cap-need)
    elif price > 1.18*avg and s['soc'] > reserve+.15:
        p = min(discharge_limit(s, reserve), .5*s['p_mw'])
    elif price < .86*avg and s['soc'] < .92:
        p = -min(charge_limit(s), .5*s['p_mw'])
    return p


def discharge_limit(s, reserve=.05):
    energy = max(0., (s['soc']-reserve)*s['e_mwh'])
    return min(s['p_mw'], energy*60)


def charge_limit(s):
    energy = max(0., (.98-s['soc'])*s['e_mwh'])
    return min(s['p_mw'], energy*60/s['eff'])


def shed(by_class, requests, served, amount):
    """Shed `amount` MW, lowest priority class first; within a class, an equal share of every device."""
    for prio in sorted(by_class):
        if amount <= 1e-9:
            break
        ids = by_class[prio]
        total = sum(requests[d][0]*served[d] for d in ids)
        if total <= 0:
            continue
        cut = min(1., amount/total)
        for d in ids:
            served[d] *= 1-cut
        amount -= total*cut


def curtail(wind, amount):
    total = sum(wind.values())
    if total <= 0:
        return
    keep = max(0., 1-amount/total)
    for tid in wind:
        wind[tid] *= keep


# ---------------------------------------------------------------- faults and protection
def sample_faults(world, hour_start):
    """Draw the faults of the coming hour from rates scaled by weather, age and maintenance."""
    rng = world.streams['faults']
    grid = world.grid
    w = world.weather_now
    wind = w['wind_10m_ms']
    storm = 1+3*max(0., (wind-12)/5)**2
    ohl_mult = storm*(1+7*w['thunder_risk'])*(1+4*w['icing_risk'])
    per_hour = 1/8760
    for br in sorted(grid['branches'].values(), key=lambda b: b['id']):
        if not G.in_service(br) or br['id'] == 'hvdc':
            continue
        if br['kind'] == 'line':
            rate = FAULT_RATE[br['type']]*br['km']/100*(ohl_mult if br['type'].startswith('OHL') else 1)
        else:
            rate = FAULT_RATE['transformer']*(1+2*w['thunder_risk'])
        if rng.random() < rate*per_hour:
            world.events.push(hour_start+rng.random()*60, 'fault', 'protection', target='branch', id=br['id'],
                              cause=fault_cause(br, w))
    for tb in sorted(grid['turbines'].values(), key=lambda t: t['id']):
        if tb['status'] != 'ok':
            continue
        ageing = 1+.04*tb['age']+.6*min(2., (world.minute-tb['maintained'])/(365*1440))
        for kind in ('turbine_minor', 'turbine_major'):
            if rng.random() < FAULT_RATE[kind]*ageing*(1+2*w['icing_risk'])*per_hour:
                world.events.push(hour_start+rng.random()*60, 'fault', 'protection', target='turbine', id=tb['id'],
                                  severity=kind)
                break
    for pole in grid['link']['poles']:
        if pole['status'] == 'ok' and rng.random() < FAULT_RATE['pole']*per_hour*(1+w['thunder_risk']):
            world.events.push(hour_start+rng.random()*60, 'fault', 'protection', target='pole', id=pole['id'])
    for s in sorted(grid['storage'].values(), key=lambda s: s['id']):
        if s['status'] == 'ok' and rng.random() < FAULT_RATE['storage']*per_hour:
            world.events.push(hour_start+rng.random()*60, 'fault', 'protection', target='storage', id=s['id'])


def fault_cause(br, w):
    if br['kind'] == 'transformer':
        return 'internal fault'
    if not br['type'].startswith('OHL'):
        return 'cable insulation failure'
    if w['thunder_risk'] > .2:
        return 'lightning'
    if w['icing_risk'] > .3:
        return 'ice load'
    if w['wind_10m_ms'] > 12:
        return 'tree or debris in storm'
    return 'insulator flashover'


def sectionalise(world, br):
    """Transfer delay for a real normally-open alternative feeder, subject to a flow study."""
    tie=world.grid['branches'].get(br.get('transfer_tie'))
    if not tie or tie['a'] not in world.network.energized or tie.get('retired') or tie['repair_until'] is not None:
        return None
    return br.get('switching_minutes',45.),0.


def repair_minutes(world, kind):
    lo, hi = REPAIR_HOURS[kind]
    rng = world.streams['faults']
    return 60*lo*exp(rng.random()*log(hi/lo))


def overload_check(world, t, loading):
    """Inverse-time thermal protection of branches; returns branches to trip now."""
    trips = []
    if any(b.get('active_fault') for b in world.grid['branches'].values()):
        # Fault-current clearing belongs to the coordinated relays. A minute-scale thermal
        # surrogate must not bypass the breaker sequence or strand an uncleared fault.
        for bid in loading:
            world.grid['branches'][bid]['stress_t']=t
        return trips
    for bid, x in loading.items():
        br = world.grid['branches'][bid]
        previous = br.get('stress_t', t)
        dt = max(0., t-previous)  # minutes, including fractional event timestamps
        br['stress_t'] = max(t, previous)
        if not G.in_service(br) or br['a'] not in world.network.energized:
            br['stress'] = 0.
            continue
        stress = br.get('stress', 0.)
        if x > 1.0:
            stress += (x-1.0)**1.5*4*dt
        else:
            stress = max(0., stress-.05*dt)
        br['stress'] = stress
        if stress >= 1.0 and G.in_service(br):
            trips.append(bid)
    return trips
