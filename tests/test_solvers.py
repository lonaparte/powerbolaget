"""Electrical backends live only in app/solvers and all honour the same contract."""
import ast
import sys
from pathlib import Path
import pytest
from app.solvers import BACKENDS, create_solver
from app.solvers.model import GridModel, Line, Load, Solver, Source

APP = Path(__file__).resolve().parents[1]/'app'
# Third-party packages allowed outside app/solvers: the web layer and input validation, never calculation.
SERVICE_LIBRARIES = {'fastapi', 'pydantic'}


def imported_roots(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split('.')[0]


def test_calculation_libraries_are_imported_only_in_app_solvers():
    outside = {}
    for path in APP.rglob('*.py'):
        if 'solvers' in path.relative_to(APP).parts: continue
        extra = {m for m in imported_roots(path) if m not in sys.stdlib_module_names and m != 'app' and m not in SERVICE_LIBRARIES}
        if extra: outside[str(path.relative_to(APP))] = sorted(extra)
    assert not outside, f'Move these imports behind an app/solvers backend: {outside}'


def feeder():
    return GridModel(Source('test', 'source', 10, 1.0, 100, 100),
                     [Line('cable', 'source', 'load', 1, .1, .1, .3, .3, 0, 0, 300), Load('demand', 'load', 10, 1000, 1.0)], (10,))


@pytest.mark.parametrize('name', sorted(BACKENDS))
def test_backend_honours_the_solver_contract(name):
    solver = create_solver(feeder(), name)
    assert all(callable(getattr(solver, m, None)) for m in Solver.__dict__ if not m.startswith('_'))
    assert solver.solve()
    voltage, (amps, p_mw) = solver.bus_voltage_pu('load'), solver.line_flow('cable')
    assert .99 < voltage < 1
    assert amps == pytest.approx(1000/(10*3**.5*voltage), rel=.01)
    assert solver.source_mw() == pytest.approx(1+solver.losses_mw(), abs=1e-6)
    assert p_mw == pytest.approx(solver.source_mw(), abs=1e-3)
    solver.set_load('demand', 2000, 1.0)
    assert solver.solve() and solver.bus_voltage_pu('load') < voltage
    current, fault_voltage = create_solver(feeder(), name).short_circuit('load', .01)
    assert current > 1000 and fault_voltage < .1


@pytest.mark.parametrize('name', sorted(BACKENDS))
def test_opening_a_branch_leaves_a_sane_solution(name):
    """Opening the only branch to a bus must not corrupt the rest of the solution (OpenDSS returns a
    'converged' solution with absurd losses if the branch is disabled instead of switched open)."""
    model = GridModel(Source('test', 'source', 10, 1.0, 100, 100),
                      [Line('a', 'source', 'mid', 1, .1, .1, .3, .3, 10, 5, 300), Line('b', 'mid', 'end', 1, .1, .1, .3, .3, 10, 5, 300),
                       Load('l_mid', 'mid', 10, 500, 1.0), Load('l_end', 'end', 10, 500, 1.0)], (10,))
    solver = create_solver(model, name)
    solver.set_powers({'l_mid': (500, 0), 'l_end': (500, 0)}, {})
    assert solver.solve()
    before = solver.results()
    solver.set_enabled('line', 'b', False)
    solver.set_powers({'l_mid': (500, 0), 'l_end': (0, 0)}, {})
    assert solver.solve()
    after = solver.results()
    assert 0 <= after.losses_mw < before.losses_mw < .1
    assert after.source_p_mw == pytest.approx(.5+after.losses_mw, abs=1e-3)
    solver.set_enabled('line', 'b', True)
    solver.set_powers({'l_mid': (500, 0), 'l_end': (500, 0)}, {})
    assert solver.solve() and solver.results().source_p_mw == pytest.approx(before.source_p_mw, abs=1e-6)


def test_two_bus_ac_matches_closed_form_voltage_current_and_losses():
    """Independent high-voltage root of the exact balanced two-bus power equation."""
    import math
    p,q,r,x=2e6,.6e6,.4,.3
    source_squared=10000.**2/3
    cross=2*(r*p/3+x*q/3)-source_squared
    constant=(r*r+x*x)*(p*p+q*q)/9
    receiving_squared=(-cross+math.sqrt(cross*cross-4*constant))/2
    current=math.hypot(p,q)/(3*math.sqrt(receiving_squared))
    expected_pu=math.sqrt(receiving_squared/source_squared)
    model=GridModel(Source('reference','source',10.,1.,1e9,1e9),[
        Line('line','source','end',1.,r,x,r,x,0.,0.,1000.),
        Load('load','end',10.,p/1000,p/math.hypot(p,q),vmin_pu=.7,vmax_pu=1.3)],(10.,))
    solver=create_solver(model)
    assert solver.solve()
    result=solver.results()
    assert result.bus_vm['end']==pytest.approx(expected_pu,abs=2e-6)
    assert result.branches['line'][4]==pytest.approx(current,rel=2e-5)
    assert result.losses_mw==pytest.approx(3*current**2*r/1e6,rel=2e-5)


def test_fault_shunt_reports_actual_voltage_dependent_delivery():
    model=feeder()
    solver=create_solver(model)
    solver.set_faults({'test':dict(bus='load',r=.1)})
    assert solver.solve()
    result=solver.results()
    assert result.bus_vm['load']<.3
    assert result.loads['demand'][0]<.15  # requested 1 MW is not delivered during the sag
    assert result.fault_mw==pytest.approx(10.**2/.1*result.bus_vm['load']**2,rel=1e-6)
    assert result.source_p_mw==pytest.approx(result.loads['demand'][0]+result.losses_mw,abs=1e-5)
    solver.set_faults({})
    assert solver.solve() and solver.results().loads['demand'][0]==pytest.approx(1.,rel=1e-5)
