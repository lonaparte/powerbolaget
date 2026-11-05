import json
import pytest
from app.world import World
from app import materials as M, water as U, society as S


def test_every_inventory_good_balances_after_production_trade_and_finance(day_world):
    w=World(state=json.loads(json.dumps(day_world.state())))
    w.advance(1)  # settle the completed day at its next boundary
    result=M.report(w)
    assert result and max(abs(r['residual']) for r in result.values())<1e-6
    assert w.conservation_history
    assert max(abs(U.residual(tank)) for tank in w.water.values())<1e-6


def test_water_outage_depletes_storage_with_exact_volume_identity():
    w=World()
    zid='z01';tank=w.water[zid]
    tank['volume_m3']=tank['initial_m3']=.01
    d=w.devices[tank['device']]
    d['p'],d['served']=1.,0.
    U.integrate(w,1.)
    assert tank['volume_m3']==0 and tank['unmet_m3']>0
    assert U.residual(tank)==pytest.approx(0.,abs=1e-9)
    U.close_day(w)
    assert tank['availability']<.01


def test_preferences_are_heterogeneous_and_water_wages_change_utility():
    w=World()
    assert len({p['elasticity'] for p in w.pops.values()})>10
    normal=S.zone_utilities(w)[('z01','public')]
    w.water['z01']['availability']=0.
    assert S.zone_utilities(w)[('z01','public')]<normal-.7


def test_legacy_save_gets_public_water_and_a_new_goods_accounting_epoch():
    w=World()
    state=json.loads(json.dumps(w.state()))
    state.pop('water');state.pop('material_baseline')
    for key in list(state['devices']):
        if key.startswith('water_'):del state['devices'][key]
    for f in state['firms'].values():
        f['devices']=[d for d in f['devices'] if not d.startswith('water_')]
    loaded=World(state=state)
    loaded.advance(2)
    assert len(loaded.water)==len(loaded.zones)
    assert max(abs(r['residual']) for r in M.report(loaded).values())<1e-6
