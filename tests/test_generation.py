import json
import pytest
from app import generation as O, construction as C
from app.world import World, command
from app.saves import validate


def engine(w, mw=10.):
    p=C.start(w,O.plan(w,'vhn',mw,24.))
    C.commission(w,p['id'])
    return w.grid['oil'][p['asset']]


def test_backup_engine_start_ramp_and_fuel_heat_balance():
    w=World(seed=2)
    g=engine(w)
    command(w,dict(kind='generator_mode',target=g['id'],mode='on',setpoint=10.))
    initial=g['fuel_mwh']
    w.advance(9)
    assert g['state']=='starting' and g['energy_mwh']==0
    w.advance(8)
    assert g['state']=='running' and 0<g['p']<=g['p_mw'] and g['energy_mwh']>0
    assert initial-g['fuel_mwh']==pytest.approx(g['fuel_used'])
    assert g['energy_mwh']==pytest.approx(g['fuel_used']*g['eff'])
    assert g['fuel_used']==pytest.approx(g['energy_mwh']+g['waste_heat_mwh'])
    f=w.flows
    actual=sum(p*s for p,s in f['dev'].values())
    assert f['link']+sum(f['turb'].values())+sum(f['oil'].values())==pytest.approx(actual+f['losses'],abs=.05)
    validate(json.loads(json.dumps(w.state())))


def test_black_start_backup_can_restore_partial_island_without_mainland():
    w=World(seed=2)
    g=engine(w,30.)
    w.advance(2)
    for pole in ('pole1','pole2'):
        w.events.push(w.minute+.1,'fault','protection',target='pole',id=pole)
    w.advance(3)
    assert g['state']=='starting' and all(d['served']==0 for d in w.devices.values())
    w.advance(13)
    assert g['forming_active'] and g['p']>0
    assert sum(p*s for p,s in w.flows['dev'].values())>0
    assert w.perf['failures']==0


def test_converter_capability_circle_includes_voltage_dependent_current_limit():
    s=dict(p_mw=10.,q_mode='fixed',q_setpoint=100.)
    p,q=O.injection(s,10.,1.)
    assert p*p+q*q==pytest.approx(11.**2)
    lowp,lowq=O.injection(s,10.,.5)
    assert lowp*lowp+lowq*lowq==pytest.approx(5.5**2)
    assert lowp<p


def test_storage_fade_preserves_stored_energy_and_retires_at_service_limit():
    s=dict(e_mwh=100.,soc=.5,cycles_mwh=0.,status='ok',forming_active=False)
    O.age_storage(s,8760.)
    assert s['soh']==pytest.approx(.985)
    assert s['soc']*s['e_mwh']==pytest.approx(50.)
    s['cycles_mwh']=2*100.*6000
    O.age_storage(s,0.)
    assert s['soh']<.8 and s['status']=='retired'
