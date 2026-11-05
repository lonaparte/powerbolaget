import pytest
import copy
from app import construction as C, engineering as X, grid as G, energy as N
from app.world import World, command, plan_build, CommandError


def complete(w, build):
    p = C.start(w, plan_build(w, dict(build)))
    C.commission(w, p['id'])
    return p


def test_independent_station_needs_a_real_connection_and_routes_change_impedance():
    w = World(seed=2)
    station = complete(w, dict(type='station', x=30.25,y=60.25,mv_kv=33.,mva=40.))['asset']
    w.advance(1)
    bus = w.substations[station]['hv_bus']
    assert bus not in w.network.energized
    a = w.substations['rom']['hv_bus']
    ca, cb = w.grid['buses'][a], w.grid['buses'][bus]
    route = [[ca['x'],ca['y']],[31.,65.],[cb['x'],cb['y']]]
    p = complete(w, dict(type='line', a=a,b=bus,line_type='CAB110',route=route))
    br = w.grid['branches'][p['asset']]
    assert br['route'] == route and br['km'] == pytest.approx(p['km'])
    w.advance(1)
    assert bus in w.network.energized
    q = complete(w, dict(type='turbine',model='PB-3.6',x=30.25,y=60.25,
                         connect_bus=w.substations[station]['mv_bus']))
    tb = w.grid['turbines'][q['turbine']]
    assert w.grid['branches'][tb['id']+'_cable']['a'] == w.substations[station]['mv_bus']
    w.advance(1)
    assert tb['bus_lv'] in w.network.energized and w.perf['failures'] == 0


def test_invalid_voltage_or_route_cannot_be_built():
    w = World()
    with pytest.raises(C.BuildError, match='voltage'):
        X.plan_line(w,'vhn_110','rom_20','CAB110')
    with pytest.raises(C.BuildError, match='endpoints'):
        X.plan_line(w,'vhn','rom','CAB110',[[0,0],[1,1]])


def test_commissioning_impact_is_a_read_only_current_condition_study():
    w=World(seed=8)
    w.advance(2)
    plan=plan_build(w,dict(type='storage',station='vhn',p_mw=10,hours=2))
    before=copy.deepcopy(w.state())
    result=X.impact(w,plan)
    assert w.state()==before
    assert result['minute']==w.minute and 'not a future forecast' in result['assumption']
    assert result['before']['converged'] and result['after']['converged']
    assert result['after']['minimum_voltage_pu'] > .8


def test_links_are_player_led_with_capacity_constraints_and_source_handover():
    w = World()
    assert not any(e['kind']=='interconnector' for e in w.events.pending())
    assert not any(p['kind']=='interconnector' and p['status']=='building' for p in w.projects.values())
    with pytest.raises(C.BuildError, match='envelope'):
        X.plan_link(w,'HVAC',500.,'rom')
    complete(w,dict(type='interconnector',technology='HVAC',p_mw=300.,station='rom'))
    w.advance(2)
    assert N.hvac_capacity(w)==300. and w.grid['source_bus']=='mainland_ac'
    assert w.grid['branches']['l_stk_lnk']['b']=='rom_110'
    assert w.perf['failures']==0


def test_work_lockout_cancellation_and_retirement():
    w = World()
    command(w,dict(kind='asset_work',target='l_kal_ind',action='maintenance'))
    pid = next(p['id'] for p in w.projects.values() if p['kind']=='asset_work')
    assert not G.in_service(w.grid['branches']['l_kal_ind'])
    with pytest.raises(CommandError,match='locked'):
        command(w,dict(kind='switch',target='l_kal_ind',closed=True))
    command(w,dict(kind='cancel_project',target=pid))
    assert G.in_service(w.grid['branches']['l_kal_ind'])
    p = C.start(w,X.plan_asset(w,'l_kal_ind','decommission'))
    C.commission(w,p['id'])
    assert w.grid['branches']['l_kal_ind']['retired']
    with pytest.raises(CommandError):
        command(w,dict(kind='switch',target='l_kal_ind',closed=True))
