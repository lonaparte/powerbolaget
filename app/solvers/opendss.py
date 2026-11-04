"""OpenDSS backend (OpenDSSDirect.py): the only module that imports the OpenDSS library."""
import math
from opendssdirect import dss
from .model import GridFormer, GridModel, Line, Load, Generator, Results, SolverError, Transformer

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
        for e in model.elements:
            if isinstance(e, Line) and not e.closed:
                self.set_enabled('line', e.name, False)

    @staticmethod
    def _command(e):
        if isinstance(e, Transformer):
            return (f'new transformer.{e.name} phases=3 windings=2 buses=[{e.hv_bus} {e.lv_bus}] conns=[delta wye] '
                    f'kvs=[{e.hv_kv} {e.lv_kv}] kvas=[{e.kva} {e.kva}] xhl={e.x_pct} %loadloss={e.load_loss_pct} %noloadloss={e.no_load_loss_pct}')
        if isinstance(e, Line):
            return (f'new line.{e.name} bus1={e.bus1} bus2={e.bus2} phases=3 length={e.length_km} units=km r1={e.r1} x1={e.x1} '
                    f"r0={e.r0} x0={e.x0} c1={e.c1_nf} c0={e.c0_nf} normamps={e.amps}")
        if isinstance(e, Load):
            limits = '' if e.vmin_pu is None else f' vminpu={e.vmin_pu} vmaxpu={e.vmax_pu}'
            return f'new load.{e.name} bus1={e.bus} phases=3 kv={e.kv} kw={e.kw} pf={e.pf} model=1{limits}'
        if isinstance(e, GridFormer):
            return f'new vsource.{e.name} bus1={e.bus} phases=3 basekv={e.kv} pu={e.pu} mvasc3={e.mvasc} mvasc1={e.mvasc} enabled=no'
        if isinstance(e, Generator):
            return f'new generator.{e.name} bus1={e.bus} phases=3 kv={e.kv} kw=0 kvar=0 kva={e.kva} model=1 vminpu={e.vmin_pu} vmaxpu={e.vmax_pu}'
        raise TypeError(f'Unsupported network element {e!r}')

    def set_enabled(self, kind, name, enabled):
        # Lines and transformers are switched by opening both terminals. Disabling them instead leaves
        # buses without any admittance to ground, and OpenDSS then reports a converged but meaningless
        # solution.
        if kind in ('line', 'transformer'):
            verb = 'close' if enabled else 'open'
            self.d(f'{verb} {kind}.{name} term=1\n{verb} {kind}.{name} term=2')
        else:
            self.d(f"edit {kind}.{name} enabled={'yes' if enabled else 'no'}")

    def set_generator(self, name, kw=None, kvar=None):
        self.d.Generators.Name(name)
        if kw is not None: self.d.Generators.kW(kw)
        if kvar is not None: self.d.Generators.kvar(kvar)

    def set_load(self, name, kw, pf):
        self.d.Loads.Name(name)
        self.d.Loads.kW(kw)
        self.d.Loads.PF(pf)

    def set_tap(self, name, tap):
        self.d.Transformers.Name(name)
        self.d.Transformers.Wdg(2)
        self.d.Transformers.Tap(tap)

    def set_powers(self, loads, generators):
        d = self.d
        for name, (kw, kvar) in loads.items():
            d.Loads.Name(name); d.Loads.kW(kw); d.Loads.kvar(kvar)
        for name, (kw, kvar) in generators.items():
            d.Generators.Name(name); d.Generators.kW(kw); d.Generators.kvar(kvar)

    def results(self):
        d = self.d
        nodes, mags, volts = d.Circuit.AllNodeNames(), d.Circuit.AllBusMagPu(), d.Circuit.AllBusVolts()
        vm, va = {}, {}
        for i, node in enumerate(nodes):
            bus, _, phase = node.partition('.')
            if phase == '1':
                re, im = volts[2*i], volts[2*i+1]
                vm[bus] = mags[i]
                va[bus] = math.degrees(math.atan2(im, re))
        names, powers, currents = d.PDElements.AllNames(), d.PDElements.AllPowers(), d.PDElements.AllMaxCurrents()
        terminals, conductors = d.PDElements.AllNumTerminals(), d.PDElements.AllNumConductors()
        branches, k = {}, 0
        for name, nt, nc, imax in zip(names, terminals, conductors, currents):
            sums = []
            for _ in range(nt):
                sums.append((sum(powers[k+2*j] for j in range(nc))/1000, sum(powers[k+2*j+1] for j in range(nc))/1000))
                k += 2*nc
            kind, _, short = name.partition('.')
            if kind.lower() in ('line', 'transformer'):
                (p1, q1), (p2, q2) = sums[0], sums[-1]
                branches[short.lower()] = (p1, q1, p2, q2, imax)
        # Circuit.TotalPower sums every voltage source, so read each one: the mainland source and the
        # grid-forming batteries are reported separately.
        formers, main = {}, (0., 0.)
        for name in d.Vsources.AllNames():
            d.Circuit.SetActiveElement('vsource.'+name)
            if not d.CktElement.Enabled():
                continue
            pw = d.CktElement.Powers()
            pq = (-sum(pw[0:6:2])/1000, -sum(pw[1:6:2])/1000)
            if name == 'source':
                main = pq
            else:
                formers[name] = pq
        return Results(bool(d.Solution.Converged()), d.Solution.Iterations(), vm, va, branches, main[0], main[1],
                       d.Circuit.Losses()[0]/1e6, formers)

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
