"""Electrical calculation backends: the only package that may import a power-system library.

Game code describes the network with app.solvers.model records and calls create_solver(); each
backend module adapts one external library to the Solver contract. To add a library: declare it
in the [solvers] group of pyproject.toml, run `python tools/deps.py lock`, write
app/solvers/<name>.py with a Backend class, and register it in BACKENDS. `python tools/deps.py
install` then installs it everywhere, and `python tools/deps.py check` verifies every backend.
"""
from importlib import import_module
from .model import Generator, GridFormer, GridModel, Line, Load, Results, Solver, SolverError, Source, Transformer

BACKENDS = {'opendss': 'opendss'}  # backend name -> module in this package
DEFAULT = 'opendss'


def backend(name=DEFAULT):
    """Import and return a backend module; the library is loaded only when first used."""
    return import_module('.'+BACKENDS[name], __name__)


def create_solver(model: GridModel, name=DEFAULT) -> Solver:
    return backend(name).Backend(model)
