"""Selective fault-zone operations and relay timing. Not an EMT relay emulator."""
from math import isfinite
from .network import Network
from .errors import RuleError

NAMES={'collector_a':'Collector A','collector_b':'Collector B','harbor':'Harbor feeder',
       'transformer':'City transformer','grid':'External grid','bess':'Battery system','farm':'Farm export breaker','pcc':'Grid connection'}

def inverse_time(current, pickup, tms):
    """IEC standard inverse shape, independent of the illustrative setting choice."""
    ratio=current/pickup
    return None if ratio<=1 else .14*tms/(ratio**.02-1)


def event(game,text,kind='info'):
    game['events'].insert(0,dict(step=game['step'],kind=kind,text=text))
    del game['events'][100:]


def inject(game, target, fail_breaker=False):
    if target not in ('collector_a','collector_b','harbor','transformer','grid','bess'):
        raise RuleError('Unknown fault location.')
    if target in game['faults']:
        raise RuleError('Equipment is still isolated. Repair and reset first.')
    if not game['breakers']['pcc'] and target not in ('grid','bess'):
        raise RuleError('The grid is off. Short-circuit studies require a connected grid.')
    if target.startswith('collector') and (not game['breakers']['farm'] or not game['breakers'][target]):
        raise RuleError('Collector already isolated; an energized fault cannot be repeated on a dead circuit.')
    if target in ('harbor','transformer') and not game['breakers']['transformer']:
        raise RuleError('City transformer is isolated; an energized fault cannot be applied.')
    timeline=[dict(ms=0,text='Fault occurs; relay sampling starts')]
    result=dict(target=target,current_a=None,basis='Discrete protection event; no electromagnetic transient simulation')
    lock=target
    if target=='grid':
        # Anti-islanding, no invented grid-forming capability on this follow-grid PCS.
        timeline += [dict(ms=200,text='27 / anti-islanding trips PCC, turbines and grid-following storage'),dict(ms=260,text='PCC breaker opens; city loses power pending grid restoration')]
        game['breakers']['pcc']=False
        lock='pcc'; repair=4
        function='27 / anti-islanding'
    elif target=='bess':
        timeline += [dict(ms=0,text='BMS battery fault blocks charging and discharging'),dict(ms=80,text='Battery DC contactor and AC breaker isolate the system')]
        game['breakers']['bess']=False
        repair=8; function='BMS / PCS trip'
    else:
        net=Network('collector_upgrade' in game['upgrades'],game)
        net.configure(game)
        result.update(net.short_circuit(target))
        amp=500 if 'collector_upgrade' in game['upgrades'] else 300
        pickup=(amp if target.startswith('collector') else 260)*game['settings']['pickup_multiplier']
        t51=inverse_time(result['current_a'],pickup,game['settings']['tms'])
        if target=='transformer':
            primary=.03; function='87T differential (ideal zone logic)'; backup=.45
        else:
            t50=.03 if result['current_a']>=pickup*8 else None
            candidates=[v for v in (t50,t51) if v is not None]
            primary=min(candidates) if candidates else None
            function='50 instantaneous overcurrent' if t50 is not None and primary==t50 else '51 standard inverse time'
            # Time-graded upstream backup, independent slower setting.
            backup=max(.45,(inverse_time(result['current_a'],pickup, .3) or 1.)+.25)
        if primary is None:
            primary=backup
            lock='farm' if target.startswith('collector') else 'transformer'
            function='Upstream backup protection'
        set_primary=primary
        if backup<primary:
            # User settings can destroy selectivity. The upstream relay wins the race.
            primary=backup
            lock='farm' if target.startswith('collector') else 'transformer'
            function='Upstream backup trips first (slow local setting)'
            timeline.append(dict(ms=round(primary*1000),text=function+'; local relay has not tripped'))
            clearing=primary+.06
        else:
            timeline.append(dict(ms=round(primary*1000),text=function+' trip'))
            if fail_breaker:
                timeline.append(dict(ms=round((primary+.06)*1000),text='Local breaker fails; fault current persists'))
                upstream=min(primary+.2,backup)
                timeline.append(dict(ms=round(upstream*1000),text='50BF breaker-failure trip' if upstream==primary+.2 else 'Upstream timed backup trips before breaker-failure protection'))
                lock='farm' if target.startswith('collector') else 'transformer'
                clearing=upstream+.06
            else:
                clearing=primary+.06
        game['breakers'][lock]=False
        timeline.append(dict(ms=round(clearing*1000),text=f'{NAMES[lock]} breaker opens; 86 lockout prevents reclosing onto the fault'))
        repair=12 if target=='transformer' else 6
        result.update(pickup_a=pickup,relay_time_s=primary,primary_setting_time_s=set_primary,backup_time_s=backup,
                      coordination_margin_s=backup-set_primary,clearing_s=clearing)
    game['faults'][target]=dict(lock=lock,since=game['step'],repair_after=game['step']+repair*4)
    result.update(function=function,timeline=timeline,step=game['step'],breaker_failure=fail_breaker,
                  locked_breaker=lock,repair_hours=repair)
    game['protection_records'].insert(0,result)
    del game['protection_records'][20:]
    event(game,f'{NAMES[target]} fault: {function}, isolating {NAMES[lock]}; minimum repair time: {repair} hours.','trip')


def repair(game,target):
    f=game['faults'].get(target)
    if not f: raise RuleError('No fault awaits reset on this equipment.')
    if game['step'] < f['repair_after']:
        raise RuleError(f"Repair incomplete; time remaining: {(f['repair_after']-game['step'])/4:g} hours.")
    lock=f['lock']
    del game['faults'][target]
    # Shared upstream lock stays open until all implicated faults are cleared.
    if not any(a['lock']==lock for a in game['faults'].values()):
        game['breakers'][lock]=True
    event(game,f'{NAMES[target]} repaired; lockout released and supply recalculated.','complete')
