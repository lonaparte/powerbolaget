"""OpenDSS backend (OpenDSSDirect.py): the only module that imports the OpenDSS library."""
from opendssdirect import dss
from .model import GridModel, Line, Load, Generator, SolverError, Transformer

NAME = 'OpenDSSDirect.py'


class Backend:
    """Builds a GridModel in a private OpenDSS context and answers the Solver contract."""

    def __init__(self, model: GridModel):
        self.d = dss.NewContext()
        s = model.source
        commands = ['clear', f'set defaultbasefrequency={model.frequency_hz}',
                    f'new circuit.{s.name} basekv={s.kv} pu={s.pu} phases=3 bus1={s.bus} mvasc3={s.mvasc3} mvasc1={s.mvasc1}']
        commands += [self._command(e) for e in model.elements]
        commands += [f"set voltagebases=[{' '.join(str(v) for v in model.voltage_bases_kv)}]", 'calcvoltagebases',
                     'set mode=snapshot controlmode=off maxiterations=100 tolerance=.000001']
        self.d('\n'.join(commands))

    @staticmethod
    def _command(e):
        if isinstance(e, Transformer):
            return (f'new transformer.{e.name} phases=3 windings=2 buses=[{e.hv_bus} {e.lv_bus}] conns=[delta wye] '
                    f'kvs=[{e.hv_kv} {e.lv_kv}] kvas=[{e.kva} {e.kva}] xhl={e.x_pct} %loadloss={e.load_loss_pct} %noloadloss={e.no_load_loss_pct}')
        if isinstance(e, Line):
            return (f'new line.{e.name} bus1={e.bus1} bus2={e.bus2} phases=3 length={e.length_km} units=km r1={e.r1} x1={e.x1} '
                    f"r0={e.r0} x0={e.x0} c1={e.c1_nf} c0={e.c0_nf} normamps={e.amps}{'' if e.closed else ' enabled=no'}")
        if isinstance(e, Load):
            limits = '' if e.vmin_pu is None else f' vminpu={e.vmin_pu} vmaxpu={e.vmax_pu}'
            return f'new load.{e.name} bus1={e.bus} phases=3 kv={e.kv} kw={e.kw} pf={e.pf} model=1{limits}'
        if isinstance(e, Generator):
            return f'new generator.{e.name} bus1={e.bus} phases=3 kv={e.kv} kw=0 kvar=0 kva={e.kva} model=1 vminpu={e.vmin_pu} vmaxpu={e.vmax_pu}'
        raise TypeError(f'Unsupported network element {e!r}')

    def set_enabled(self, kind, name, enabled):
        self.d(f"edit {kind}.{name} enabled={'yes' if enabled else 'no'}")

    def set_generator(self, name, kw=None, kvar=None):
        self.d.Generators.Name(name)
        if kw is not None: self.d.Generators.kW(kw)
        if kvar is not None: self.d.Generators.kvar(kvar)

    def set_load(self, name, kw, pf):
        self.d.Loads.Name(name)
        self.d.Loads.kW(kw)
        self.d.Loads.PF(pf)

    def solve(self):
        self.d.Solution.Solve()
        return bool(self.d.Solution.Converged())

    def bus_voltage_pu(self, bus):
        self.d.Circuit.SetActiveBus(bus)
        return min(self.d.Bus.puVmagAngle()[::2])

    def line_flow(self, name):
        self.d.Circuit.SetActiveElement('line.'+name)
        powers = self.d.CktElement.Powers()
        return max(self.d.CktElement.CurrentsMagAng()[::2]), sum(powers[:6:2])/1000

    def transformer_flow(self, name):
        self.d.Circuit.SetActiveElement('transformer.'+name)
        powers = self.d.CktElement.Powers()
        return sum(powers[:8:2]), sum(powers[1:8:2])

    def losses_mw(self):
        return self.d.Circuit.Losses()[0]/1e6

    def source_mw(self):
        return -self.d.Circuit.TotalPower()[0]/1000

    def short_circuit(self, bus, r_ohm):
        d = self.d
        for name in d.Generators.AllNames(): d(f'edit generator.{name} enabled=no')
        for name in d.Loads.AllNames(): d(f'edit load.{name} enabled=no')
        d(f'new fault.study phases=3 bus1={bus} r={r_ohm}')
        d('set mode=snapshot loadmodel=admittance'); d.Solution.Solve()
        if not d.Solution.Converged(): raise SolverError('Short-circuit calculation did not converge.')
        d.Circuit.SetActiveElement('fault.study')
        current = max(d.CktElement.CurrentsMagAng()[::2])
        return current, self.bus_voltage_pu(bus)
