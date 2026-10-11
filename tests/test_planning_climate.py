from copy import deepcopy
import math
import pytest
from app.engine import create, apply, check_plan, storage_rating
from app.planning import default_plan, normalize, audit, commission
from app.errors import RuleError
from app.construction import schedule, marine_weather
from app.climate import conditions, instant, normal, solar_day


def test_continuous_climate_at_midnight_month_year_and_noise_knots():
    keys=['wind_10m_ms','speed_ms','temperature_c','cloud_fraction','wave_height_m','irradiance_w_m2','daylight_hours']
    # Include every day boundary, all 2 h / 4 h noise knots, and the year boundary.
    for seed in [0,42,999]:
        for time in [i/12 for i in range(12*366+1)]:
            left=instant(seed,time-1e-7);right=instant(seed,time+1e-7)
            for key in keys:assert abs(right[key]-left[key])<.02,(seed,time,key,left[key],right[key])
            delta=(right['direction_deg']-left['direction_deg']+180)%360-180
            assert abs(delta)<.001
    for key in ['WS10M','T2M','ALLSKY_SFC_SW_DWN']:
        assert normal(key,0)==pytest.approx(normal(key,365),abs=1e-10)


def test_climate_is_function_plus_seeded_variation_and_solar_geometry():
    assert conditions(42,1234)==conditions(42,1234)
    assert conditions(42,1234)!=conditions(43,1234)
    assert conditions(42,95.999)['wind_10m_ms']==pytest.approx(conditions(42,96.001)['wind_10m_ms'],abs=.001)
    winter=conditions(42,355*96);summer=conditions(42,171*96)
    assert 6<winter['daylight_hours']<8
    assert 16<summer['daylight_hours']<18
    for day in [0,90,171,270,355]:
        vals=[conditions(42,day*96+i) for i in range(96)]
        assert vals[0]['irradiance_w_m2']==0
        assert max(w['irradiance_w_m2'] for w in vals)>0
        assert sum(w['irradiance_w_m2'] for w in vals)*.25/1000==pytest.approx(vals[0]['daily_solar_kwh_m2'])
        assert all(math.isfinite(x) for w in vals for x in w.values() if isinstance(x,(int,float)))
        assert all(.05<=w['cloud_fraction']<=.98 for w in vals)
        for hour in [0,8,12,23]:
            assert marine_weather(42,day*24+hour)==(vals[hour*4]['wind_10m_ms'],vals[hour*4]['wave_height_m'])


def test_plan_validation_and_free_wiring():
    p=default_plan();assert not audit(p)['errors']
    p['edges'][0]['closed']=False
    assert audit(p)['errors']
    g=apply(create(),dict(kind='plan_save',plan=p))
    assert not g['draft']['edges'][0]['closed'] # Disconnected drafts can be saved.
    with pytest.raises(RuleError):apply(g,dict(kind='plan_build',plan=p))
    p['edges'].append(dict(p['edges'][0],id='Tie',source='T01',target='T03',closed=True))
    assert not audit(p)['errors']
    p['edges'][0]['closed']=True
    assert audit(p)['warnings'] # Closed ring is supported, with coordination warning.
    assert not check_plan(g,p)['errors']
    p['edges'][0]['source']='missing'
    with pytest.raises(RuleError):normalize(p)


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(construction_days=1),
    lambda p:p['nodes'][1].update(rated_mw=float('nan')),
    lambda p:p['nodes'][1].update(id='x\nnew generator.evil'),
    lambda p:p['nodes'][2].update(id='t01'),
    lambda p:p['nodes'][1].update(transformer_mva=1),
    lambda p:p.update(storage_power_mw=3,storage_capacity_mwh=0),
    lambda p:p['resources'].update(installation_vessels=1.5),
])
def test_invalid_plans_rejected(mutate):
    p=default_plan();mutate(p)
    with pytest.raises(RuleError):normalize(p)


def test_schedule_depends_on_quantities_resources_and_weather(monkeypatch):
    import app.construction as construction
    p=default_plan();base=schedule(p,0)
    crews=deepcopy(p);crews['resources'].update(engineering_teams=2,electrical_teams=2,installation_vessels=2,supply_lines=2)
    assert schedule(crews,0)['finish_step']<base['finish_step']
    bigger=deepcopy(p)
    for t in bigger['nodes'][1:]:t.update(rated_mw=10,transformer_mva=11,rotor_m=180,hub_m=120)
    assert schedule(bigger,0)['finish_step']>base['finish_step']
    for phase in base['phases']:
        for dependency in phase['dependencies']:
            assert phase['start_hour']>=next(d['end_hour'] for d in base['phases'] if d['id']==dependency)
    assert base['critical_path'][-1]=='commission'
    assert base['days']==pytest.approx(base['finish_step']/96,abs=.005)
    monkeypatch.setattr(construction,'marine_weather',lambda seed,hour:(0,0))
    clear=schedule(p,0)
    gate=next(x for x in clear['phases'] if x['id']=='foundation')['start_hour']
    monkeypatch.setattr(construction,'marine_weather',lambda seed,hour:(30,6) if gate<=hour<gate+240 else (0,0))
    delayed=schedule(p,0)
    assert delayed['weather_wait_vessel_hours']>=240
    assert delayed['finish_step']>clear['finish_step']


def test_plan_commissioning_is_frozen_and_drives_real_ac_network():
    g=create();original=deepcopy(g);p=default_plan();p['collector_kv']=66
    p['nodes'][1].update(rated_mw=7,transformer_mva=8,hub_m=120,rotor_m=150)
    p.update(storage_power_mw=2,storage_capacity_mwh=8)
    report=check_plan(g,p);assert not report['errors'];assert g==original
    after=apply(g,dict(kind='plan_build',plan=p));project=after['projects'][0]
    assert after['cash']==pytest.approx(g['cash']-report['cost'])
    assert len(after['snapshot']['turbines'])==8
    p['nodes'][1]['rated_mw']=5
    after=apply(after,dict(kind='plan_save',plan=p))
    assert after['projects'][0]['plan']['nodes'][1]['rated_mw']==7
    after['step']=project['finish']-2
    after=apply(after,dict(kind='advance',steps=1));assert not after['plants']
    after=apply(after,dict(kind='advance',steps=1));assert len(after['plants'])==1
    assert storage_rating(after)==(8,32)
    units=[t for t in after['snapshot']['turbines'] if t['farm_id']=='P01']
    assert len(units)==4 and units[0]['rated_mw']==7 and units[0]['hub_m']==120
    assert 'p01_l01' in after['snapshot']['network']['lines']
    assert 'p01_t01' in after['snapshot']['network']['transformer_pct']
    assert abs(after['metrics']['balance_error_mw'])<.005
    assert after['metrics']['max_loading_pct']<=100.01
    t=after['totals']
    err=t['wind_mwh']+t['import_mwh']-t['served_mwh']-t['export_mwh']-t['loss_mwh']-t['auxiliary_mwh']-t['battery_loss_mwh']-(after['battery']['energy_mwh']-14.4)
    assert abs(err)<.002
    after=apply(after,dict(kind='maintenance',target='P01_T01'))
    assert next(t for t in after['snapshot']['turbines'] if t['id']=='P01_T01')['output_mw']==0


def test_cable_parameters_change_actual_currents_and_losses():
    g=create();p=default_plan();one=check_plan(g,p)
    for edge in p['edges']:edge['r_ohm_km']*=2;edge['length_km']*=2
    two=check_plan(g,p)
    assert not one['errors'] and not two['errors']
    assert two['preview']['network']['losses_mw']>one['preview']['network']['losses_mw']
    assert two['schedule']['phases'][4]['work_hours']>one['schedule']['phases'][4]['work_hours']
