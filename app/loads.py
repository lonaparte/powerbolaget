"""Load Profile Engine: from plans to continuous minute-level P/Q requests (spec section 7).

Two kinds of load devices are attached to buses:
- Aggregated devices (households, shops, public services, lodging, farms). Their size driver (occupied
  households, staff, guests, herd) changes at most hourly. At each hour boundary the engine anchors at
  the value requested now and ramps linearly to the next target, so a new plan never causes a step.
  Time-of-day shapes are smooth periodic functions and heating comes from a thermal model, so the
  requested power is continuous in time.
- Equipment (kilns, mills, crushers, dryers, shore power). These are discrete state machines; a start,
  stop or trip is a real event and is not smoothed.
Requests are what devices ask for. What they receive comes back from the energy model each minute.
"""
from math import exp, pi, sin, tan, acos
from .calendar import HOUR, is_rest_day, parts

PRIORITY = {'flexible': 1, 'commercial': 2, 'residential': 3, 'industry': 4, 'critical': 5}
UA_HOUSEHOLD = .125        # kW/K per household (assumption)
C_HOUSEHOLD = 7.5          # kWh/K per household
T_DESIGN = -16.0


def bump(h, mu, sigma):
    d = abs(h-mu) % 24
    d = min(d, 24-d)
    return exp(-.5*(d/sigma)**2)


def window(h, start, end, edge=.45):
    """Smooth opening-hours plateau between start and end (hours)."""
    return 1/(1+exp(-(h-start)/edge))/(1+exp(-(end-h)/edge))


def residential_shape(h, rest):
    """Appliances, lighting and hot water per occupied household, kW."""
    morning = bump(h, 9.3, 1.6)*.20 if rest else bump(h, 7.2, 1.0)*.26
    day = bump(h, 13.0, 2.4)*(.16 if rest else .07)
    return .30+morning+day+.48*bump(h, 19.0, 2.1)+.08*bump(h, 22.5, 1.2)


def open_hours(h, minute):
    p = parts(minute)
    if p['doy'] in (357, 358, 0, 171):
        return .15*window(h, 11, 15)
    if p['weekday'] == 6:
        return .55*window(h, 11, 16)
    if p['weekday'] == 5:
        return .8*window(h, 10, 16.5)
    return window(h, 8.5, 19.0)


def office_hours(h, minute):
    return .2*window(h, 7, 21) if is_rest_day(minute) else window(h, 7.3, 16.8, .6)


def cop(t_out):
    return max(1.6, min(4.2, 2.6+.055*t_out))


def heating_setpoint(h):
    return 19.6+.9*window(h, 6.0, 22.5, .7)


def lerp_scale(d, t):
    if t >= d['t1']:
        return d['s1']
    if t <= d['t0']:
        return d['s0']
    return d['s0']+(d['s1']-d['s0'])*(t-d['t0'])/(d['t1']-d['t0'])


def new_device(did, kind, owner, bus, priority, pf, **extra):
    return dict(id=did, kind=kind, owner=owner, bus=bus, priority=PRIORITY[priority], pf=pf, p=0., q=0., served=1.,
                e_req=0., e_srv=0., **extra)


def aggregated(did, kind, owner, bus, priority, pf, scale, **extra):
    return new_device(did, kind, owner, bus, priority, pf, s0=scale, s1=scale, t0=0, t1=0, **extra)


def equipment(did, owner, bus, name, p_mw, pf, priority='industry', ramp_min=3, restart_min=15, warmup_min=0,
              warmup_share=0., role='', rate=0.):
    """A machine. warmup: after a trip, minutes at warmup_share of rated power before it produces again."""
    return new_device(did, 'equipment', owner, bus, priority, pf, name=name, role=role, rate=rate, p_rated=p_mw,
                      state='off', since=0., want_on=False, ramp_min=ramp_min, restart_min=restart_min,
                      warmup_min=warmup_min, warmup_share=warmup_share, ready_at=0., run_min=0.)


def retarget(d, now, scale):
    """Hourly plan: start from the value requested now, reach `scale` one hour later."""
    current = lerp_scale(d, now)
    d['s0'], d['t0'], d['s1'], d['t1'] = current, now, scale, now+HOUR


def request(d, t, w, ctx):
    """Requested MW of a device at minute t (may be fractional) given weather w."""
    h = (t % 1440)/60
    kind = d['kind']
    if kind == 'equipment':
        return equipment_power(d, t, ctx)
    s = lerp_scale(d, t)
    temp = w['temperature_c']
    if kind == 'residential':
        appliances = s*residential_shape(h, ctx['rest'])
        heat = d['heat_electric_kw']
        return (appliances+heat)/1000
    if kind == 'services':
        dark = 1-min(1., w['irradiance_w_m2']/250)
        return s*(.28+(.95+.18*dark)*open_hours(h, t)+.05*max(0., 17-temp)*.45)/1000
    if kind == 'public':
        return (s*(.26+.78*office_hours(h, t)+.045*max(0., 17-temp)*.35)+d.get('base_kw', 0.))/1000
    if kind == 'lodging':
        beds = d['beds']
        return (beds*(.045+.035*max(0., 16-temp)*.5)+s*(.28+.34*bump(h, 8, 1.5)+.38*bump(h, 20, 2.2)))/1000
    if kind == 'farm':
        milking = .6+.9*bump(h, 6, 1.0)+.9*bump(h, 17, 1.0)
        return (s*.085*milking+d.get('base_kw', 0.)+.02*s*max(0., 5-temp))/1000
    raise ValueError(kind)


def equipment_power(d, t, ctx):
    state, rated = d['state'], d['p_rated']
    load = 1+.025*sin(2*pi*t/37+len(d['id']))   # small smooth process variation
    if state == 'running':
        return rated*load
    if state == 'starting':
        return rated*min(1., (t-d['since'])/max(1, d['ramp_min']))
    if state == 'warmup':
        return rated*d['warmup_share']
    if state == 'stopping':
        return rated*max(0., 1-(t-d['since'])/2)
    return 0.


def heating_demand(d, t, w):
    """Residential heating: thermal power the zone's heating systems ask for, and its electric share."""
    h = (t % 1440)/60
    households = d['heated']
    ua, cap = UA_HOUSEHOLD*households, C_HOUSEHOLD*households
    t_set = heating_setpoint(h)
    thermal = ua*(t_set-w['temperature_c'])+cap*(t_set-d['t_in'])/2.0
    thermal = max(0., min(thermal, 1.6*ua*(21-T_DESIGN)))
    electric_share = d['direct']+d['heat_pump']/cop(w['temperature_c'])
    return thermal, thermal*electric_share


def update_thermal(d, w, thermal, electric_served_fraction, minutes):
    """Advance the zone's indoor temperature; only the electric part of heating is lost in an outage."""
    elec_part = d['direct']+d['heat_pump']
    delivered = thermal*((1-elec_part)+elec_part*electric_served_fraction)
    households = d['heated']
    gains = .35*households+.04*w['irradiance_w_m2']*households/100
    ua, cap = UA_HOUSEHOLD*households, C_HOUSEHOLD*households
    d['t_in'] += minutes/60*(delivered+gains-ua*(d['t_in']-w['temperature_c']))/cap


def q_from_p(p, pf):
    return p*tan(acos(pf)) if pf < 1 else 0.


def step_equipment(d, t, energized):
    """State transitions that depend on time and supply (not on plans)."""
    st = d['state']
    if st in ('running', 'starting', 'warmup', 'stopping') and not energized:
        trip(d, t)
        return
    if st == 'starting' and t-d['since'] >= d['ramp_min']:
        d['state'], d['since'] = 'running', t
    elif st == 'warmup' and t-d['since'] >= d['warmup_min']:
        d['state'], d['since'] = 'running', t
    elif st == 'stopping' and t-d['since'] >= 2:
        d['state'], d['since'] = 'off', t
    elif st == 'tripped' and energized and d['want_on'] and t >= d['ready_at']:
        d['state'], d['since'] = ('warmup' if d['warmup_min'] else 'starting'), t
    elif st == 'off' and d['want_on'] and energized and t >= d['ready_at']:
        d['state'], d['since'] = 'starting', t


def trip(d, t):
    d['state'], d['since'] = 'tripped', t
    d['ready_at'] = t+d['restart_min']
    d['trips'] = d.get('trips', 0)+1


def command(d, t, on):
    """A planned start or stop at time t."""
    d['want_on'] = on
    if on and d['state'] in ('off', 'stopping') and t >= d['ready_at']:
        d['state'], d['since'] = 'starting', t
    elif not on and d['state'] in ('running', 'starting', 'warmup'):
        d['state'], d['since'] = 'stopping', t
