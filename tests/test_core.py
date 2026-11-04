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


def test_weather_follows_the_island_climate():
    """Targets from NASA POWER hourly data at 57.5 N, 18.5 E (2020-2024) and the Visby station averages."""
    import math
    import statistics as S
    from app import weather as W
    hours = [W.instant(1, h/24) for h in range(0, 365*24, 2)]
    wind = [w['wind_10m_ms'] for w in hours]
    cv = S.pstdev(wind)/S.mean(wind)
    assert .38 < cv < .52                                   # observed 0.45
    assert .03 < sum(v < 2 for v in wind)/len(wind) < .14   # calms, observed 8 %
    sectors = [0]*8
    for w in hours:
        sectors[int(((w['direction_deg']+22.5) % 360)//45)] += 1
    share = [n/len(hours) for n in sectors]
    assert max(share) == share[5] and min(share) > .04       # south-west prevails, every direction occurs
    july = [W.instant(1, 181+d+h/24)['temperature_c'] for d in range(31) for h in range(24)]
    swing = S.mean(max(july[i:i+24])-min(july[i:i+24]) for i in range(0, len(july), 24))
    assert 6.5 < swing < 10.5                                # Visby: 8.2 C
    midsummer, midwinter = W.sun(171), W.sun(354)
    assert 17.6 < midsummer['daylight_hours'] < 18.4 and 6.2 < midwinter['daylight_hours'] < 6.8
    assert W.sun(171)['elevation_deg'] > -10 > W.sun(354)['elevation_deg']   # light summer nights
    assert math.isclose(W.sun(171.5)['elevation_deg'], 90-57.5+23.44, abs_tol=.8)
