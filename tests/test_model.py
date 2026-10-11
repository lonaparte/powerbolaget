import math
from copy import deepcopy
import pytest
from app.engine import create, apply, evaluate, storage_rating
from app.wind import power_curve, farm
from app.protection import inverse_time
from app.network import Network
from app.errors import RuleError


def run(g, kind, **kw):
    return apply(g, dict(kind=kind, **kw))


def energy_error(g):
    t=g['totals']
    return t['wind_mwh']+t['import_mwh']-t['served_mwh']-t['export_mwh']-t['loss_mwh']-t['auxiliary_mwh']-t['battery_loss_mwh']-(g['battery']['energy_mwh']-14.4)


@pytest.mark.parametrize('speed,expected',[(0,0),(2.99,0),(3,0),(11.4,5),(20,5),(25,0),(30,0)])
def test_reference_curve(speed,expected):
    assert power_curve(speed)==pytest.approx(expected)


def test_density_wakes_and_restart_hysteresis():
    assert power_curve(8,1.1)<power_curve(8,1.225)
    g=create(); met=dict(speed_ms=10.,direction_deg=270.,density=1.225)
    rows=farm(g,met)
    assert rows[1]['available_mw']<rows[0]['available_mw']
    farm(g,dict(met,speed_ms=26),evolve=True)
    assert g['turbines'][0]['storm_lock']
    assert farm(g,met,evolve=True)[0]['available_mw']==0
    assert farm(g,met,evolve=True)[0]['available_mw']>0


def test_dispatch_day_energy_and_soc():
    g=run(create(),'advance',steps=96)
    assert abs(energy_error(g))<.002
    assert g['totals']['unserved_mwh']==pytest.approx(0)
    assert g['totals']['battery_loss_mwh']>0
    for m in g['history']:
        assert .15-1e-8<=m['soc']<=.90+1e-8
        assert -5.003<=m['grid_mw']<=12.003
        assert abs(m['balance_error_mw'])<.005
        assert m['max_loading_pct']<=100.01


def test_action_does_not_change_weather_or_past_state():
    g=run(create(),'advance',steps=4); original=deepcopy(g)
    newer=run(g,'settings',settings={'reserve_soc':.35})
    assert newer['snapshot']['weather']==g['snapshot']['weather']
    assert g==original
    batched=run(create(),'advance',steps=12)
    split=create()
    for _ in range(12):split=run(split,'advance')
    # Warm starts across a batch and fresh DSS contexts can differ within solver tolerance.
    assert batched['metrics']==pytest.approx(split['metrics'],abs=1e-4,rel=1e-6)
    assert batched['totals']==pytest.approx(split['totals'],abs=1e-4,rel=1e-6)


def test_calm_depletion_and_priority():
    g=run(create(),'weather',target='calm')
    g=run(g,'settings',settings={'import_limit_mw':2})
    g=run(g,'advance',steps=96)
    assert g['metrics']['supply_pct']<50
    assert g['metrics']['served_mw']==pytest.approx(g['metrics']['critical_served_mw'])
    assert g['metrics']['grid_mw']<=2.003
    assert abs(energy_error(g))<.002


def test_zero_import_depleted_storage_station_shutdown():
    g=create();g['battery']['energy_mwh']=3.6
    g=run(g,'weather',target='calm')
    g=run(g,'settings',settings={'import_limit_mw':0})
    assert g['metrics']['served_mw']==0
    assert g['metrics']['grid_mw']==0
    assert not g['snapshot']['network']['energized']
    g=run(g,'settings',settings={'import_limit_mw':12})
    assert g['metrics']['supply_pct']==pytest.approx(100)


@pytest.mark.parametrize('target',['collector_a','collector_b','harbor','transformer','grid','bess'])
def test_fault_isolation_and_repair(target):
    initial=create();g=run(initial,'fault',target=target)
    record=g['protection_records'][0]
    assert not g['breakers'][record['locked_breaker']]
    if target.startswith('collector'):
        indices=range(4) if target.endswith('a') else range(4,8)
        assert sum(g['snapshot']['turbines'][i]['output_mw'] for i in indices)==0
        assert g['metrics']['supply_pct']==pytest.approx(100)
    if target=='harbor':assert g['snapshot']['districts'][0]['served_mw']==0
    if target in ('transformer','grid'):assert g['metrics']['served_mw']==0
    if target=='grid':assert g['metrics']['wind_mw']==g['metrics']['battery_mw']==0
    if target=='bess':assert g['metrics']['battery_mw']==0
    with pytest.raises(RuleError):run(g,'repair',target=target)
    g=run(g,'advance',steps=record['repair_hours']*4)
    g=run(g,'repair',target=target)
    assert not g['faults']
    assert g['metrics']['supply_pct']==pytest.approx(100)


def test_relay_curve_breaker_failure_and_dead_zone():
    assert inverse_time(100,100,.1) is None
    assert inverse_time(1000,100,.1)==pytest.approx(.14*.1/(10**.02-1))
    g=run(create(),'fault',target='collector_a',breaker_failure=True)
    r=g['protection_records'][0]
    assert r['current_a']>r['pickup_a']
    assert r['clearing_s']==pytest.approx(r['relay_time_s']+.26)
    assert r['coordination_margin_s']>.2
    assert r['locked_breaker']=='farm'
    assert g['metrics']['wind_mw']==0
    with pytest.raises(RuleError):run(g,'fault',target='collector_b')


def test_construction_commissioning_and_battery_energy():
    g=create()
    for p in ('wind_phase2','battery_phase2','collector_upgrade'):g=run(g,'build',target=p)
    assert storage_rating(g)==(6,24)
    assert len(g['projects'])==3
    assert g['cash']==32_000_000
    with pytest.raises(RuleError):run(g,'build',target='wind_phase2')
    # Jump clock to a commissioning boundary to test the event, without pretending
    # omitted time has been simulated. The separate endurance test runs all intervals.
    g['step']=90*96-1
    g=run(g,'advance')
    assert storage_rating(g)==(12,48)
    assert 'wind_phase2' not in g['upgrades']
    assert abs(energy_error(g))<.002
    g['step']=180*96-1
    g=run(g,'advance')
    assert set(g['upgrades'])=={'wind_phase2','battery_phase2','collector_upgrade'}
    assert all(t['installed'] for t in g['snapshot']['turbines'])
    assert g['metrics']['max_loading_pct']<=100.01


def test_slow_local_setting_trips_upstream_first():
    g=run(create(),'settings',settings={'pickup_multiplier':3.,'tms':1.})
    g=run(g,'fault',target='collector_a')
    r=g['protection_records'][0]
    assert r['coordination_margin_s']<0
    assert r['locked_breaker']=='farm'
    assert r['clearing_s']==pytest.approx(r['backup_time_s']+.06)
    assert g['metrics']['wind_mw']==0
    assert [e['ms'] for e in r['timeline']]==sorted(e['ms'] for e in r['timeline'])


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,21,True])
def test_invalid_settings_are_rejected(value):
    with pytest.raises(RuleError):run(create(),'settings',settings={'import_limit_mw':value})


def test_annual_horizon_and_maintenance():
    g=create();base=g['metrics']['wind_mw']
    g=run(g,'maintenance',target='WT01')
    assert g['snapshot']['turbines'][0]['output_mw']==0
    assert g['metrics']['wind_mw']<base
    g['step']=35040
    with pytest.raises(RuleError):run(g,'advance')
