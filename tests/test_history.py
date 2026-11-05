import json
import pytest
from app.world import World, command
from app.history import export, as_csv


def test_layered_history_survives_save_and_matches_metered_energy():
    w=World(seed=2)
    command(w,dict(kind='record',target='f_cement_kiln',recording=True))
    w.advance(121)
    data=export(w,'f_cement_kiln','hour')
    assert len(data['rows'])==2 and data['fields'][2]==('served_mwh','MWh')
    assert data['rows'][0][2]>0
    minute=export(w,'f_cement_kiln','minute',start=60,end=90)
    assert len(minute['rows'])==31
    b=World(state=json.loads(json.dumps(w.state())))
    assert export(b,'f_cement_kiln','hour')==data
    assert export(b,'f_cement_kiln','minute',60,90)==minute
    assert len(b.entity_hist['f_cement_kiln'])==2
    global_rows=export(w)['rows']
    assert sum(r[2] for r in global_rows)==pytest.approx(sum(h['served'] for h in w.history_hour),abs=.002)
    assert 'served_mwh [MWh]' in as_csv(data)


def test_hour_settlement_retry_cannot_duplicate_production_or_payments():
    w=World()
    w.advance(61)
    old=json.dumps(w.state(),sort_keys=True)
    w.settle_hour(0,60)
    assert json.dumps(w.state(),sort_keys=True)==old
    with pytest.raises(ValueError,match='contiguous'):
        w.settle_hour(90,150)


def test_semantic_exchanges_distinguish_intents_forecasts_actuals_and_versions():
    w=World()
    w.advance(61)
    assert set(w.messages)=={'ActivityPlan','DemandTrajectory','PhysicalResult','EconomicSettlement'}
    for kind,msg in w.messages.items():
        assert msg['schema']=='powerbolaget.exchange/1' and len(msg['id'])==24
        assert msg['clock_unit']=='minute' and msg['units']['energy']=='MWh'
        assert msg['valid_to']>=msg['valid_from'] and msg['mapping_version']>=1
    assert w.messages['ActivityPlan']['meaning']=='intent'
    assert w.messages['DemandTrajectory']['meaning']=='forecast'
    assert w.messages['EconomicSettlement']['meaning']=='actual'


def test_minute_recording_is_opt_in_and_bounded():
    w=World()
    w.advance(2)
    assert not w.archive.minutes
    for key in list(w.devices)[:8]:
        command(w,dict(kind='record',target=key))
    with pytest.raises(ValueError,match='8 objects'):
        w.archive.record(w,list(w.devices)[8],True)


def test_exports_mark_intervals_held_after_numerical_failure():
    w=World()
    command(w,dict(kind='record',target='res_z01'))
    w.advance(2)
    w.archive.invalid(0.,1.)
    data=export(w,'res_z01','minute')
    assert data['invalid_intervals']==[[0.,1.]]
    assert 'held after numerical failure' in as_csv(data)


def test_unsafe_new_solver_settings_in_a_save_are_rejected():
    from app.saves import validate,SaveError
    w=World()
    data=json.loads(json.dumps(w.state()))
    data['grid']['branches']['f_z06']['id']='f_z06\nredirect bad'
    with pytest.raises(SaveError):validate(data)
    data=json.loads(json.dumps(w.state()))
    data['grid']['branches']['f_z06']['active_fault']={'bus':'z06','r':'1\nredirect bad'}
    with pytest.raises(SaveError):validate(data)
