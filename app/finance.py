"""Finite private credit and daily solvency; all cash movements remain double-entry.

Assumptions: 8% APR, at most two months' payroll plus 25% inventory collateral,
30-day liquidity cure, inventory liquidation at 65% of reference price. Public services
are budget funded; Powerbolaget's explicit free-investment financing is separate.
"""
from . import economy as E
from .params import WAGE, SHIFT_HOURS

APR = .08
CURE_DAYS = 30


def account(world, f):
    if 'credit' not in f:
        collateral = sum(q*world.markets.get(g, {}).get('ref', 0.) for g, q in f['inventory'].items())
        limit = max(250_000., 60*f['desired_staff']*WAGE[f['sector']]*SHIFT_HOURS+.25*collateral)
        f['credit'] = dict(limit=limit, debt=0., interest=0., distress_days=0, losses=0., repaid=0.)
    return f['credit']


def liquidity(world, f):
    c = account(world, f)
    return max(0., world.ledger.balance('firm:'+f['id'])+c['limit']-c['debt'])


def close_day(world, now):
    for f in world.firms.values():
        if f['kind'] in ('public', 'hospital') or f['status'] not in ('operating', 'construction', 'suspended'):
            continue
        c, led, key = account(world, f), world.ledger, 'firm:'+f['id']
        interest = c['debt']*APR/365
        led.transfer(key, 'bank', interest, 'loan interest', now)
        c['interest'] += interest
        bal = led.balance(key)
        if bal < 0:
            draw = min(-bal, max(0., c['limit']-c['debt']))
            led.transfer('bank', key, draw, 'bank credit', now)
            c['debt'] += draw
        else:
            reserve = max(100_000., f['desired_staff']*WAGE[f['sector']]*SHIFT_HOURS*7)
            repay = min(c['debt'], max(0., bal-reserve)*.25)
            led.transfer(key, 'bank', repay, 'loan repayment', now)
            c['debt'] -= repay
            c['repaid'] += repay
        bal = led.balance(key)
        distressed = c['debt'] >= .95*c['limit'] and f['ema_margin'] < 0
        c['distress_days'] = c['distress_days']+1 if distressed else max(0, c['distress_days']-1)
        if bal < -.01 or c['distress_days'] >= CURE_DAYS:
            liquidate(world, f, now)
        elif distressed and c['distress_days'] % 7 == 0 and f['status'] == 'operating':
            E.fire(world, f, max(1, round(f['staff']*.08)))
            f['staff'] = sum(world.jobs[f['id']].values())
            f['desired_staff'] = min(f['desired_staff'], f['staff'])
            world.log('finance', f"{f['name']} reduces staff under its credit limit", f['zone'], firm=f['id'])


def liquidate(world, f, now):
    c, led, key = account(world, f), world.ledger, 'firm:'+f['id']
    recovery = 0.
    disposal = {}
    for g, q in f['inventory'].items():
        value = max(0., q)*world.markets.get(g, {}).get('ref', 0.)*.65
        led.transfer('external', key, value, 'liquidation inventory', now, g, q)
        recovery += value
        disposal[g] = q
    f['inventory'] = {g: 0. for g in f['inventory']}
    E.fire(world, f, f['staff'])
    f['staff'] = f['desired_staff'] = 0
    for did in f['equipment']+f['devices']:
        d = world.devices[did]
        d.update(p=0., q=0., served=0.)
        if d['kind'] == 'equipment':
            d.update(state='off', want_on=False, run_min=0.)
    world.events.cancel(lambda e: e.get('device') in f['equipment'])
    for p in world.projects.values():
        if p.get('firm') == f['id'] and p['status'] == 'building':
            p['status'] = 'cancelled'
            world.events.cancel(lambda e: e.get('project') == p['id'])
    # Existing unpaid operating obligations are a recognized bank loss, never an unlimited loan.
    shortfall = max(0., -led.balance(key))
    led.transfer('bank', key, shortfall, 'insolvency loss', now)
    repay = min(c['debt'], max(0., led.balance(key)))
    led.transfer(key, 'bank', repay, 'liquidation repayment', now)
    c['repaid'] += repay
    c['losses'] += c['debt']-repay+shortfall
    c['debt'] = 0.
    residual = led.balance(key)
    if residual > 0:
        led.transfer(key, 'external', residual, 'liquidation equity', now)
    f['status'] = 'exited'
    f['liquidation'] = dict(t=now, inventory=disposal, recovery=recovery, bank_loss=c['losses'])
    world.network.dirty = True
    world.log('finance', f"{f['name']} exits; assets, debt and jobs settled (bank loss {c['losses']/1e6:.2f} MSEK)",
              f['zone'], firm=f['id'])
