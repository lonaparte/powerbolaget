import pytest
from app import protection as P
from app.world import World


def test_iec_standard_inverse_reference_curve():
    assert P.inverse_time(200.,100.,.1)==pytest.approx(1.062902702,rel=1e-8)
    assert P.inverse_time(100.,100.) is None
    assert P.inverse_time(1000.,100.)<P.inverse_time(200.,100.)


def test_fault_current_selects_primary_and_disabled_primary_uses_backup():
    w=World(seed=1)
    w.advance(2)
    br=w.grid['branches']['f_z06']
    normal=P.study(w,br)
    assert normal['current_a']>normal['selected']['pickup_a']
    assert normal['selected']['branch']==br['id']
    assert normal['selected']['seconds']>0
    br['relay']={'enabled':False}
    backup=P.study(w,br)
    assert backup['selected']['role']=='backup' and backup['selected']['branch']!=br['id']
    assert P.study(w,br,1e5)['selected'] is None


def test_transfer_is_rejected_when_the_real_tie_is_overloaded():
    w=World(seed=4)
    w.advance(5)
    br=w.grid['branches']['f_z06']
    tie=w.grid['branches'][br['transfer_tie']]
    tie['amps']=1.
    w.events.push(w.minute+.1,'fault','protection',target='branch',id=br['id'],cause='test',permanent=True)
    w.advance(50)
    assert not tie['closed'] and br['tripped']
    assert w.devices['res_z06']['served']==0
    assert any('transfer rejected' in e['text'] for e in w.logbook)
