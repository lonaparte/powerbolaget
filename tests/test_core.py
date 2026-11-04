"""Calendar, random streams, event queue and ledger: the World Simulation Core's building blocks."""
import random
from app.calendar import label, parts, stamp, DAY, YEAR
from app.events import EventQueue
from app.ledger import Ledger
from app.rng import Streams


def test_fantasy_era_calendar_starts_on_year_one():
    assert label(0) == 'FE 1 · 01 Jan · 00:00'
    assert parts(0)['weekday'] == 0 and parts(0)['year'] == 1
    assert parts(YEAR)['year'] == 2 and parts(YEAR)['doy'] == 0
    assert label(YEAR-1) == 'FE 1 · 31 Dec · 23:59'
    assert stamp(800.257).startswith('FE0001-01-01T13:20:15.4')


def test_streams_are_independent_and_resume_exactly():
    a = Streams(5)
    first = [a['weather'].random() for _ in range(3)]
    b = Streams(5)
    b['faults'].random()
    assert [b['weather'].random() for _ in range(3)] == first
    saved = a.state()
    nxt = a['weather'].random()
    assert Streams(5, saved)['weather'].random() == nxt


def test_events_run_in_time_then_priority_order_and_survive_saving():
    q = EventQueue()
    q.push(10.5, 'equipment', 'equipment', device='x')
    q.push(10.5, 'fault', 'protection', target='branch', id='l1')
    q.push(3.25, 'restore', 'restore', id='l2')
    q2 = EventQueue(q.state())
    order = [q2.pop_before(11)['kind'] for _ in range(3)]
    assert order == ['restore', 'fault', 'equipment']
    assert q2.pop_before(100) is None
    ids = {e['event_id'] for e in EventQueue(q.state()).pending()}
    assert len(ids) == 3


def test_ledger_never_creates_money():
    led = Ledger()
    led.endow('a', 100.)
    rng = random.Random(1)
    for _ in range(500):
        led.transfer(rng.choice('abcd'), rng.choice('abcd'), rng.uniform(-50, 50), 'test')
    assert abs(sum(led.accounts.values())) < 1e-9
    assert Ledger(led.state()).accounts == led.accounts
