"""Regression cases from the specification audit; exercise behavior and conservation."""
import json
import pytest
from app import economy as E, energy as N
from app.world import World, command, CommandError


def production_hour(w):
    f = w.firms['f_cement']
    for did in f['equipment']:
        w.devices[did]['run_min'] = 60.
    before = dict(f['inventory'])
    E.settle_hour(w, 0, 60)
    return f['inventory']['cement']-before['cement']


def test_industrial_labor_and_installed_capacity_limit_throughput():
    w = World(seed=1)
    f = w.firms['f_cement']
    assert production_hour(w) == pytest.approx(320.)
    f['staff'] = 0
    assert production_hour(w) == 0
    f['staff'] = f['desired_staff']
    f['capacity_factor'] = 1.15
    assert production_hour(w) == pytest.approx(368.)


def test_full_silo_does_not_consume_or_destroy_goods():
    f = E.firm('test', 'Test', 'cement', 'industry', 'z01', 'z01', 'cement', 'island',
               inventory={'clinker': 100., 'cement': 99.9}, limits={'cement': 100.})
    made = E.produce(f, 'cement', 320., {'clinker': .93}, output=True)
    assert made == pytest.approx(.1)
    assert f['inventory']['clinker'] == pytest.approx(100.-made*.93)
    assert f['inventory']['cement'] == 100.
    assert f['materials']['produced']['cement'] == pytest.approx(made)
    assert f['materials']['consumed']['clinker'] == pytest.approx(made*.93)
    assert E.produce(f, 'cement', 320., {'clinker': .93}, output=True) == 0


def test_protection_is_invariant_to_repeated_solves_at_the_same_time():
    w = World(seed=1)
    w.advance(1)
    bid = 'l_lnk_vhn'
    br = w.grid['branches'][bid]
    N.overload_check(w, 0., {bid: 1.3})
    for _ in range(5):
        assert N.overload_check(w, 0., {bid: 1.3}) == []
    N.overload_check(w, .5, {bid: 1.3})
    assert br['stress'] == pytest.approx(.5*.3**1.5*4)
    assert N.overload_check(w, 1.5, {bid: 1.3}) == []
    assert N.overload_check(w, 1.6, {bid: 1.3}) == [bid]


def test_command_retry_is_idempotent_across_save_and_conflicts_are_rejected():
    w = World(seed=1)
    c = dict(kind='build', request_id='build-1', build=dict(type='storage', station='vhn', p_mw=10., hours=2.))
    reply = command(w, c)
    projects, cash = len(w.projects), w.ledger.balance('pb')
    assert command(w, c) == reply
    assert len(w.projects) == projects and w.ledger.balance('pb') == cash
    restored = World(state=json.loads(json.dumps(w.state())))
    assert command(restored, c) == reply
    assert len(restored.projects) == projects
    with pytest.raises(CommandError, match='different command'):
        command(w, dict(c, build=dict(c['build'], p_mw=20.)))
