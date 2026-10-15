"""One entry point for Powerbolaget's external dependencies.

  python tools/deps.py install   install the pinned set from requirements.lock, run pip check, verify the backends
  python tools/deps.py check     import every electrical backend in app/solvers and solve a two-bus test feeder
  python tools/deps.py lock      re-pin requirements.lock from the groups in pyproject.toml

Direct dependencies are declared once, by role, in pyproject.toml. The lock targets Python 3.12 on
Linux, the interpreter of the Docker image. To add an electrical library: add it to the "solvers"
group, install it in a Python 3.12 environment, run `lock`, then add its backend to app/solvers/.
"""
from importlib.metadata import distribution
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT/'requirements.lock'
PYTHON = (3, 12)


def groups(*names):
    """Direct requirements of the named groups in pyproject.toml, or of every group."""
    declared = tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['dependency-groups']
    return [r for name in (names or declared) for r in declared[name]]


def install():
    if sys.version_info[:2] != PYTHON:
        raise SystemExit(f'requirements.lock is pinned for Python {PYTHON[0]}.{PYTHON[1]}; run this command with that interpreter.')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(LOCK)], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    if (ROOT/'app'/'solvers').is_dir(): check()
    else: print('app/ is not present yet; run `python tools/deps.py check` once it is copied.')


def check():
    """Every registered backend must import and solve a 10 kV feeder: 1 MW over 1 km of cable."""
    sys.path.insert(0, str(ROOT))
    from app.solvers import BACKENDS, backend, create_solver
    from app.solvers.model import GridModel, Line, Load, Source
    feeder = GridModel(Source('check', 'source', 10, 1.0, 100, 100),
                       [Line('cable', 'source', 'load', 1, .1, .1, .3, .3, 0, 0, 300), Load('demand', 'load', 10, 1000, 1.0)], (10,))
    for name in BACKENDS:
        solver = create_solver(feeder, name)
        if not solver.solve(): raise SystemExit(f'{name}: test feeder did not converge')
        voltage = solver.bus_voltage_pu('load')
        if not .95 < voltage < 1: raise SystemExit(f'{name}: implausible test feeder voltage {voltage:.4f} pu')
        print(f'{name}: {backend(name).NAME} ready, test feeder {voltage:.4f} pu, import {solver.source_mw():.3f} MW')


def lock():
    """Record the installed closure of every group; install new direct dependencies first."""
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    pending, seen = groups(), {}
    while pending:
        name = canonicalize_name(Requirement(pending.pop()).name)
        if name in seen: continue
        d = distribution(name); seen[name] = d.version
        for text in d.requires or []:
            r = Requirement(text)
            if r.marker is None or r.marker.evaluate({'extra': ''}): pending.append(r.name)
    LOCK.write_text('\n'.join(f'{n}=={v}' for n, v in sorted(seen.items()))+'\n', encoding='utf-8')
    print(f'Locked {len(seen)} packages in {LOCK.name}')


if __name__ == '__main__':
    commands = {'install': install, 'check': check, 'lock': lock}
    if len(sys.argv) != 2 or sys.argv[1] not in commands: raise SystemExit(__doc__)
    commands[sys.argv[1]]()
