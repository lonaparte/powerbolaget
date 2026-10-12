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
