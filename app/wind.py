"""Deterministic correlated weather, density correction and directional Jensen wakes."""
from math import sin, cos, pi, sqrt, hypot
import random
from .parameters import TURBINE, TURBINES, INITIAL_TURBINES
from .planning import fleet, installed, enabled


def weather(game, evolve=False):
    from .climate import conditions
    return conditions(game['seed'],game['step'],game['weather'])


def power_curve(v, density=1.225, parameters=None):
    """Anchored cubic reference approximation, NOT a measured OEM power curve."""
    p=parameters or TURBINE
    if v < p['cut_in'] or v >= p['cut_out']:
        return 0.
    ve = v * (density / TURBINE['rho_ref']) ** (1/3)
    return p['rated_mw'] * min(1., max(0., (ve**3-p['cut_in']**3)/(p['rated_speed']**3-p['cut_in']**3)))


def commissioned(game, index):
    return installed(game,index)


def farm(game, met, evolve=False):
    # Meteorological direction is FROM; convert to flow-to Cartesian vector.
    a = (270-met['direction_deg'])*pi/180
    dx, dy = cos(a), sin(a)
    result = []
    machines=fleet(game)
    speeds=[met['speed_ms']*(t['hub_m']/90)**.11 for t in machines]
    # Update every machine before calculating wakes; results must not depend on list order.
    if evolve:
        for i,memory in enumerate(game['turbines']):
            if not commissioned(game,i): continue
            if speeds[i]>=machines[i]['cut_out']:
                memory['storm_lock']=True; memory['restart_count']=0
            elif memory['storm_lock']:
                memory['restart_count']=memory['restart_count']+1 if speeds[i]<machines[i]['restart_speed'] else 0
                if memory['restart_count']>=2: memory['storm_lock']=False
    for i, t in enumerate(machines):
        installed = commissioned(game, i)
        memory = game['turbines'][i]
        deficits = []
        for j, other in enumerate(machines):
            if j == i or not commissioned(game,j) or game['turbines'][j]['maintenance'] or game['turbines'][j]['storm_lock']:
                continue
            if t['farm_id']!=other['farm_id'] or not enabled(game,other) or not other['cut_in']<=speeds[j]<other['cut_out']:
                continue
            sx, sy = t['x_m']-other['x_m'], t['y_m']-other['y_m']
            down, cross = sx*dx+sy*dy, abs(-sx*dy+sy*dx)
            radius = other['rotor_m']/2+.05*down
            if down > 0 and cross < radius+t['rotor_m']/2:
                # Smooth partial rotor overlap approximation; k=.05, Ct=.8 assumed.
                overlap = min(1., max(0., (radius+t['rotor_m']/2-cross)/t['rotor_m']))
                deficits.append((1-sqrt(1-.8))/(1+2*.05*down/other['rotor_m'])**2*overlap)
        loss = min(.65, sqrt(sum(v*v for v in deficits)))
        effective = speeds[i]*(1-loss)
        free = power_curve(speeds[i],met['density'],t) if installed else 0.
        available = power_curve(effective,met['density'],t) if installed else 0.
        reason = 'Operating'
        if not installed: reason = 'Reserved'
        elif memory['maintenance']: reason = 'Under maintenance'
        elif memory['storm_lock'] or speeds[i] >= t['cut_out']: reason = 'Storm shutdown'
        elif speeds[i] < t['cut_in']: reason = 'Below cut-in wind'
        elif not game['breakers']['pcc']: reason = 'Anti-islanding shutdown'
        elif not enabled(game,t): reason = 'Collector isolated'
        if reason != 'Operating': available = 0.
        result.append(dict(**t, installed=installed, effective_ms=effective, available_mw=available,
                           free_mw=free, wake_loss_pct=loss*100, status=reason))
    return result
