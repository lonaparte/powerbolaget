"""The running world: conservation, continuity, physics bookkeeping, protection and saves."""
import hashlib
import json
import math
import pytest
from app import grid as G
from app import loads as L
from app import society as S
from app.calendar import DAY, HOUR
from app.construction import BuildError, add_storage
from app.saves import SaveError, validate
from app.world import CommandError, World, command


def digest(w):
    s = w.state()
    s.pop('saved')
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()


def test_money_people_and_jobs_balance_after_a_day(day_world):
    w = day_world
    assert abs(sum(w.ledger.accounts.values())) < 1e-3
    for p in w.pops.values():
        assert 0 <= p['employed'] <= p['count']
        assert p['employed'] == sum(staff.get(p['id'], 0) for staff in w.jobs.values())
    for f in w.firms.values():
        assert f['staff'] == sum(w.jobs[f['id']].values())
    assert len(w.pops) <= 10_000
    assert w.perf['failures'] == 0


def test_monthly_population_account_is_exact():
    w = World(seed=3)
    w.advance(120)
    start = S.residents(w)
    w.demography['month']['start'] = start
    w.settle_month(w.minute)
    m = w.demography['months'][-1]
    assert m['end'] == m['start']+m['births']-m['deaths']+m['immigration']-m['emigration']
    assert m['end'] == S.residents(w)


def test_hourly_plans_do_not_step_the_load(day_world):
    """Aggregated loads ramp between hourly targets: the change across an hour boundary is no larger
    than ordinary minute-to-minute changes (spec 7.2)."""
    w = World(seed=11)
    w.advance(30)
    series = {d: [] for d, dev in w.devices.items() if dev['kind'] != 'equipment'}
    for _ in range(180):
        w.advance(1)
        for d in series:
            series[d].append((w.minute-1, w.devices[d]['p']))
    for d, pts in series.items():
        steps = [abs(b[1]-a[1]) for a, b in zip(pts, pts[1:])]
        boundary = [abs(b[1]-a[1]) for a, b in zip(pts, pts[1:]) if b[0] % HOUR == 0]
        typical = sorted(steps)[len(steps)//2]
        assert max(boundary) <= max(4*typical, 2e-3), d


def test_every_minute_balances_power(day_world):
    w = day_world
    f = w.flows
    served = sum(p*s for p, s in f['dev'].values())
    supply = f['link']+sum(f['turb'].values())+sum(f['storage'].values())
    assert supply == pytest.approx(served+f['losses'], abs=.05)


def test_energy_bookkeeping_matches_the_minutes(day_world):
    h = list(day_world.history_hour)[-1]
    assert h['served'] <= h['load']+1e-9
    assert h['wind'] <= h['wind_avail']+1e-6
    assert h['load'] == pytest.approx(h['served']+h['unserved'], rel=1e-6, abs=1e-6)


def test_outage_trips_equipment_at_once_and_restart_waits():
    w = World(seed=2)
    w.advance(10)
    command(w, dict(kind='switch', target='l_kal_ind', closed=False))
    w.advance(1)
    kiln = w.devices['f_cement_kiln']
    assert kiln['state'] == 'tripped' and kiln['served'] == 0
    assert 'ind_kal' not in w.network.energized
    command(w, dict(kind='switch', target='l_kal_ind', closed=True))
    w.advance(45)
    assert kiln['state'] == 'warmup'          # a tripped kiln needs hours before it produces again
    assert w.devices['res_z11']['served'] == 1.0


def test_fault_protection_and_repair_restore_supply():
    w = World(seed=4)
    w.advance(5)
    t = w.minute+.25
    w.events.push(t, 'fault', 'protection', target='branch', id='f_z18', cause='test')
    w.advance(1)
    br = w.grid['branches']['f_z18']
    assert br['tripped'] and 'z18' not in w.network.energized
    assert w.devices['res_z18']['served'] == 0
    if br['repair_until'] is None:            # transient fault: auto-reclose
        w.advance(1)
    else:
        w.advance(int(br['repair_until']-w.minute)+2)
    assert not br['tripped'] and 'z18' in w.network.energized
    assert any(e['kind'] == 'protection' for e in w.logbook)


def test_a_feeder_fault_is_sectionalised_before_the_repair():
    w = World(seed=4)
    w.advance(5)
    # Cable faults are permanent. The single-circuit feeder trips, then switching re-feeds most customers.
    w.events.push(w.minute+.25, 'fault', 'protection', target='branch', id='f_z06', cause='test')
    w.advance(1)
    br = w.grid['branches']['f_z06']
    assert br['tripped'] and w.devices['res_z06']['served'] == 0
    w.advance(151)
    assert not br['tripped'] and br['repair_until'] is not None and 'z06' in w.network.energized
    share = br['section_out']
    assert .15 <= share <= .35
    assert w.devices['res_z06']['served'] == pytest.approx(1-share)
    w.events.cancel(lambda e: e.get('id') == 'f_z06' and e.get('reason') == 'repair completed')
    br['repair_until'] = w.minute+5
    w.events.push(br['repair_until'], 'restore', 'restore', id='f_z06', reason='repair completed')
    w.advance(7)
    assert br['section_out'] is None and br['repair_until'] is None and w.devices['res_z06']['served'] == 1
    # The sea cable to the islet has no other path: its customers wait for the repair.
    w.events.push(w.minute+.25, 'fault', 'protection', target='branch', id='f_z14', cause='test')
    w.advance(200)
    assert w.grid['branches']['f_z14']['tripped'] and w.devices['res_z14']['served'] == 0
    assert w.perf['failures'] == 0


def test_grid_forming_battery_carries_the_island_when_the_link_is_lost():
    w = World(seed=5)
    w.advance(5)
    sid = add_storage(w, dict(station='vhn', p_mw=60., e_mwh=240., grid_forming=True))
    w.grid['storage'][sid]['soc'] = .9
    for pole in ('pole1', 'pole2'):
        w.events.push(w.minute+.1, 'fault', 'protection', target='pole', id=pole)
    w.advance(3)
    s, f = w.grid['storage'][sid], w.flows
    assert s['forming_active'] and 'z01' in w.network.energized
    # The battery is the island's slack: it discharges to cover a deficit or absorbs surplus wind.
    load = sum(p*share for p, share in f['dev'].values())
    assert abs(f['link']) < .05
    assert sum(f['turb'].values())+f['storage'][sid] == pytest.approx(load+f['losses'], abs=.05)
    assert abs(s['p']) > .5 and s['soc'] != .9
    served = sum(d['served'] for d in w.devices.values())/len(w.devices)
    assert served > .3


def test_link_loss_without_grid_forming_is_a_blackout():
    w = World(seed=5)
    w.advance(5)
    for pole in ('pole1', 'pole2'):
        w.events.push(w.minute+.1, 'fault', 'protection', target='pole', id=pole)
    w.advance(2)
    assert all(d['served'] == 0 for d in w.devices.values())
    assert w.perf['failures'] == 0            # a blackout is physical, not a numerical failure


def test_same_seed_same_world():
    a, b = World(seed=9), World(seed=9)
    a.advance(240)
    b.advance(240)
    assert digest(a) == digest(b)


def test_save_and_load_continue_within_tolerance():
    a = World(seed=12)
    a.advance(200)
    state = json.loads(json.dumps(a.state()))
    b = World(state=validate(state))
    a.advance(300)
    b.advance(300)
    sa, sb = a.state(), b.state()
    assert sa['minute'] == sb['minute'] and sa['events'] == sb['events']
    assert [p['count'] for p in sa['pops'].values()] == [p['count'] for p in sb['pops'].values()]
    for k, v in sa['ledger']['accounts'].items():
        assert sb['ledger']['accounts'][k] == pytest.approx(v, rel=1e-6, abs=1e-3)


def test_building_a_turbine_commissions_it_into_the_power_flow():
    w = World(seed=6)
    w.advance(10)
    with pytest.raises(CommandError):
        command(w, dict(kind='build', build=dict(type='turbine', model='PB-5.6', x=70.0, y=40.0)))   # sea
    with pytest.raises(CommandError):
        command(w, dict(kind='build', build=dict(type='turbine', model='PB-5.6', x=18.6, y=82.0)))   # town
    with pytest.raises(CommandError):
        command(w, dict(kind='build', build=dict(type='turbine', model='PB-5.6', x=46.25, y=90.75)))  # quarry
    command(w, dict(kind='build', build=dict(type='turbine', model='PB-5.6', x=30.25, y=60.25)))
    pid, project = next((k, v) for k, v in w.projects.items() if v['kind'] == 'turbine')
    tid = project['turbine']
    assert w.grid['turbines'][tid]['status'] == 'construction'
    w.events.cancel(lambda e: e.get('project') == pid)
    w.events.push(w.minute+1, 'commission', 'commission', project=pid)
    w.advance(30)
    assert w.grid['turbines'][tid]['status'] == 'ok'
    assert tid in w.flows['turb']
    assert w.ledger.balance('pb') < 400e6


def test_saves_with_unsafe_ids_or_unknown_types_are_rejected():
    w = World(seed=1)
    s = json.loads(json.dumps(w.state()))
    bad = json.loads(json.dumps(s))
    bad['grid']['buses']['a b\nredirect x'] = next(iter(bad['grid']['buses'].values()))
    with pytest.raises(SaveError):
        validate(bad)
    bad = json.loads(json.dumps(s))
    next(iter(bad['grid']['branches'].values()))['type'] = 'XYZ'
    with pytest.raises(SaveError):
        validate(bad)
    assert validate(s) is s


def test_hvac_link_takes_over_the_voltage_reference_and_fails_over_to_hvdc():
    from app import energy as N
    w = World(seed=8)
    w.advance(10)
    assert w.grid['source_bus'] == 'mainland' and N.hvac_capacity(w) == 0
    w.interconnector_stage(0)
    w.advance(5)
    f = w.flows
    assert w.grid['source_bus'] == 'mainland_ac' and N.hvac_capacity(w) == 150
    served = sum(p*s for p, s in f['dev'].values())
    assert f['link_ac']+f['link_dc']+sum(f['turb'].values()) == pytest.approx(served+f['losses'], abs=.05)
    assert max(v for v in f['vm'].values()) < 1.06
    w.events.push(w.minute+.1, 'fault', 'protection', target='branch', id='hvac_1', cause='test')
    w.advance(2)
    assert w.grid['source_bus'] == 'mainland'          # the HVDC converter forms the island again
    assert all(d['served'] == 1 for d in w.devices.values() if d['bus'] in w.network.energized and d['p'] > 0)
    assert w.perf['failures'] == 0
