"""Backend-neutral three-phase network description and the solver contract.

Game code describes the grid with these records and talks to a Solver; it never imports a
power-system library. Units: kV, kVA, kW, kvar, km, ohm/km and nF/km; per-unit voltages.
"""
from dataclasses import dataclass, field
from typing import Optional, Protocol, Union


class SolverError(RuntimeError):
    """A backend could not produce a converged solution."""


@dataclass(frozen=True)
class Source:
    """External grid as a Thevenin equivalent behind the slack bus."""
    name: str
    bus: str
    kv: float
    pu: float
    mvasc3: float
    mvasc1: float


@dataclass(frozen=True)
class Transformer:
    """Two-winding transformer, delta on the high-voltage side and grounded wye on the low-voltage side."""
    name: str
    hv_bus: str
    lv_bus: str
    hv_kv: float
    lv_kv: float
    kva: float
    x_pct: float
    load_loss_pct: float
    no_load_loss_pct: float
    kind = 'transformer'


@dataclass(frozen=True)
class Line:
    """Three-phase line or cable with sequence impedances per km."""
    name: str
    bus1: str
    bus2: str
    length_km: float
    r1: float
    x1: float
    r0: float
    x0: float
    c1_nf: float
    c0_nf: float
    amps: float
    closed: bool = True
    kind = 'line'


@dataclass(frozen=True)
class Load:
    """Constant-power load; vmin_pu/vmax_pu bound the constant-power region when given."""
    name: str
    bus: str
    kv: float
    kw: float
    pf: float
    vmin_pu: Optional[float] = None
    vmax_pu: Optional[float] = None
    kind = 'load'


@dataclass(frozen=True)
class Generator:
    """Constant-power injection such as a wind turbine or a battery converter."""
    name: str
    bus: str
    kv: float
    kva: float
    vmin_pu: float = .8
    vmax_pu: float = 1.2
    kind = 'generator'


@dataclass(frozen=True)
class GridFormer:
    """A converter that can form the voltage of an electrical island (out of service until enabled)."""
    name: str
    bus: str
    kv: float
    mvasc: float
    pu: float = 1.0
    kind = 'vsource'


Element = Union[Transformer, Line, Load, Generator, GridFormer]


@dataclass
class Results:
    """One converged snapshot, in MW, Mvar, A and per unit. Branch tuples: (P1, Q1, P2, Q2, Imax) with
    P1/Q1 entering terminal 1 and P2/Q2 entering terminal 2; a branch's losses are P1 + P2."""
    converged: bool
    iterations: int
    bus_vm: dict
    bus_va: dict
    branches: dict
    source_p_mw: float
    source_q_mvar: float
    losses_mw: float
    formers: dict = field(default_factory=dict)   # grid-forming sources: {name: (P MW, Q Mvar) injected}


    loads: dict = field(default_factory=dict)     # actual P/Q including voltage dependence
    generators: dict = field(default_factory=dict)
    fault_mw: float = 0.0  # resistive fault dissipation, included in losses_mw


@dataclass
class GridModel:
    """A complete network. Elements keep their order so every backend builds the same circuit."""
    source: Source
    elements: list = field(default_factory=list)
    voltage_bases_kv: tuple = ()
    frequency_hz: float = 50


class Solver(Protocol):
    """What game code may ask of an electrical backend. Element names are the model names."""

    def set_enabled(self, kind: str, name: str, enabled: bool) -> None:
        """Switch an element in or out of service."""

    def set_faults(self, faults: dict) -> None:
        """Active balanced shunts: {id: {bus, r in ohm}}. Missing faults are disabled."""

    def set_reference(self, name: str, pu: float, angle: float, mvasc: float) -> None:
        """Controlled positive-sequence voltage reference for RMS event windows."""

    def set_generator(self, name: str, kw: Optional[float] = None, kvar: Optional[float] = None) -> None:
        """Set a generator's output; None leaves that quantity unchanged."""

    def set_load(self, name: str, kw: float, pf: float) -> None:
        """Set a load's active power and power factor."""

    def set_tap(self, name: str, tap: float) -> None:
        """Per-unit tap of a transformer's low-voltage winding (above 1 raises the low-voltage side)."""

    def set_powers(self, loads: dict, generators: dict) -> None:
        """Set many injections at once: {name: (kW, kvar)}; generator kW may be negative (charging)."""

    def results(self) -> Results:
        """Every bus voltage and branch flow of the last solution."""

    def solve(self) -> bool:
        """Run a snapshot AC power flow and report whether it converged."""

    def bus_voltage_pu(self, bus: str) -> float:
        """Lowest phase-to-neutral voltage magnitude at a bus."""

    def line_flow(self, name: str) -> tuple:
        """(highest phase current in A over both terminals, active power entering terminal 1 in MW)."""

    def transformer_flow(self, name: str) -> tuple:
        """(active kW, reactive kvar) entering the high-voltage terminal."""

    def losses_mw(self) -> float:
        """Total active losses of the circuit."""

    def source_mw(self) -> float:
        """Active power drawn from the external grid; negative means export."""

    def short_circuit(self, bus: str, r_ohm: float) -> tuple:
        """Bolted three-phase fault fed by the source only: (fault current A, lowest bus voltage pu).

        The study takes all loads and generators out of service, so the solver is not reused afterwards.
        """
