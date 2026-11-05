import json
import numpy as np
import pytest
from app.solvers.rms import advance,derivative
from app.world import World
from app.construction import add_storage


def test_swing_rocof_and_rk4_match_independent_linear_state_solution():
    c=dict(inertia=2.,governor_s=.5,droop=.05,damping=1.)
    assert derivative([0.,0.,0.,1.02],.1,0.,1.02,.1,c)[1]==pytest.approx(-1.25)
    a=np.array([[-.25,12.5],[-.8,-2.]])
    b=np.array([-2.5,.4])
    equilibrium=-np.linalg.solve(a,b)
    eigen,vectors=np.linalg.eig(a)
    expected=equilibrium+np.real(vectors @ np.diag(np.exp(eigen*2.)) @ np.linalg.solve(vectors,np.array([0.,.1])-equilibrium))
    y=[0.,0.,.1,1.02]
    for _ in range(100):
        y=advance(y,.2,0.,1.02,.2,c,.02)
    assert y[1:3]==pytest.approx(expected,abs=2e-7)


def island_event(at=5.1):
    w=World(seed=5)
    w.advance(5)
    sid=add_storage(w,dict(station='vhn',p_mw=60.,e_mwh=240.,grid_forming=True))
    w.grid['storage'][sid]['soc']=.9
    for pole in ('pole1','pole2'):
        w.events.push(at,'fault','protection',target='pole',id=pole)
    return w


def test_island_event_is_coupled_network_dynamics_and_finishes_without_event_growth():
    w=island_event()
    w.advance(2)
    event=w.archive.waveforms[-1]
    assert event['status']=='complete' and 450<=len(event['samples'])<=550
    assert len(w.events.heap)<100
    freq=[s[1] for s in event['samples']]
    assert max(freq)-min(freq)>.001 and all(45<f<55 for f in freq)
    assert event['actions'] and w.perf['failures']==0
    assert 'bess1' in event['object_samples']
    for s in event['samples']:
        assert s[4]+s[5]+s[6]+s[7]==pytest.approx(s[3]+s[8],abs=.05)


def test_save_in_middle_of_event_preserves_controllers_and_continues():
    w=island_event(5.99)
    w.advance(1)
    assert w.rms['active']
    restored=World(state=json.loads(json.dumps(w.state())))
    w.advance(1);restored.advance(1)
    assert restored.frequency_hz==pytest.approx(w.frequency_hz,abs=.02)
    assert restored.grid['storage']['bess1']['soc']==pytest.approx(w.grid['storage']['bess1']['soc'],abs=1e-4)
    assert restored.archive.waveforms[-1]['status']=='complete'
