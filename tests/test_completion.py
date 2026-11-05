"""Regression cases from the specification audit; exercise behavior and conservation."""
import json
import pytest
from app import economy as E, energy as N
from app.world import World, command, CommandError
from app import retail as R, finance as F


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


def test_fixed_contract_does_not_shift_load_for_unbilled_spot_prices():
    w = World(seed=1)
    f = w.firms['f_cement']
    f['inventory']['rawmeal'] = .7*f['limits']['rawmeal']
    key = 'firm:'+f['id']
    def planned(spot):
        w.events.cancel(lambda e: e['kind'] == 'equipment')
        w.energy_price = lambda t: spot
        E.plan_hour(w, 60)
        return {e['device']: e['on'] for e in w.events.pending() if e['kind'] == 'equipment'}
    low = planned(.2)
    assert low == planned(4.)
    c = R.offer(w, 'industry', 'floating', 0)
    c['index'] = 'spot'
    w.contracts[key] = c
    assert planned(.2)['f_cement_rawmill1'] is True
    assert 'f_cement_rawmill1' not in planned(4.)


def test_new_retail_policy_preserves_signed_contract_and_renews_at_expiry():
    w = World(seed=1)
    owner = 'firm:f_cement'
    initial = w.tariff('industry', 0, owner)
    signed = dict(w.contracts[owner])
    command(w, dict(kind='retail_policy', category='industry', policy=dict(network_fee=2., fixed_markup=.5)))
    assert w.tariff('industry', 1, owner) == initial
    assert w.contracts[owner] == signed
    assert w.tariff('industry', signed['expires'], owner) > initial
    w.price_observations = dict(sum=18., hours=24)
    R.close_month(w)
    assert w.price_avg == .75 and w.price_observations['hours'] == 0


def test_private_credit_is_finite_and_exit_settles_jobs_and_losses():
    w = World(seed=1)
    f = w.firms['f_brewery']
    c = F.account(w, f)
    c.update(limit=100., debt=90.)
    key = 'firm:'+f['id']
    w.ledger.transfer(key, 'external', w.ledger.balance(key)+25., 'test shock')
    F.close_day(w, 1440)
    assert f['status'] == 'exited'
    assert f['staff'] == 0 and not w.jobs[f['id']]
    assert c['debt'] == 0 and c['losses'] >= 0
    assert w.ledger.balance(key) == pytest.approx(0.)
    assert all(d['p'] == 0 for d in (w.devices[i] for i in f['equipment']))
    assert all(p['employed'] == sum(s.get(p['id'], 0) for s in w.jobs.values()) for p in w.pops.values())
    assert sum(w.ledger.accounts.values()) == pytest.approx(0., abs=1e-4)


def test_surplus_cash_repays_private_debt_with_interest():
    w = World(seed=1)
    f = w.firms['f_feed']
    c = F.account(w, f)
    c['debt'] = 100_000.
    w.ledger.transfer('bank', 'firm:'+f['id'], 2e6, 'test loan')
    F.close_day(w, 1440)
    assert c['interest'] > 0 and c['repaid'] > 0 and c['debt'] < 100_000.
