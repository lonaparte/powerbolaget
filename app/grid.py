"""The electrical network as game data, and its link to the power-flow engine.

Buses, branches, turbines, storage and the mainland link live in world.grid as plain data (saved with
the game). Network compiles that data into an app.solvers GridModel (OpenDSS by default) once per
topology and then only updates injections every minute. Ids are lower case because OpenDSS folds
names to lower case.
"""
from math import hypot
from .solvers import Generator, GridFormer, GridModel, Line, Load, Source, Transformer, create_solver

BASES_KV = (220.0, 110.0, 33.0, 20.0, 0.69)
SOURCE_PU = 1.03         # voltage set point of the link converter (assumption)
SOURCE_MVASC = 1500.0    # stiffness of the converter station seen from the island (assumption)

# Sequence impedances per km and ratings. Generic engineering values, not taken from any operator.
LINE_TYPES = {
    #           r1     x1    c1 nF  r0    x0    c0 nF  amps  MSEK/km  label
    'OHL110': (.120, .400, 9.0, .300, 1.20, 5.0, 600, 6.0, '110 kV overhead line'),
    'CAB110': (.060, .120, 200., .120, .300, 200., 700, 16.0, '110 kV cable'),
    'OHL20': (.270, .360, 10.0, .500, 1.20, 5.0, 350, 1.2, '20 kV overhead line'),
    'CAB20': (.160, .110, 300., .400, .350, 300., 400, 2.0, '20 kV cable'),
    'CAB33': (.130, .120, 220., .300, .400, 220., 500, 2.4, '33 kV collector cable'),
    'HVDC': (.001, .010, 0.0, .001, .010, 0.0, 1400, 0.0, 'HVDC link (converter equivalent)'),
    # 220 kV subsea cable; about 95 % of its charging is compensated by shunt reactors at both ends (net c1).
    'CAB220': (.030, .120, 10., .090, .350, 10., 1100, 0.0, '220 kV AC subsea cable'),
}
TRANSFORMER_TYPES = {
    #            x %   load loss %  no-load %
    '110/20': (12.0, .35, .04), '110/33': (11.0, .35, .04), '33/0.69': (6.0, .90, .15), '220/110': (12.0, .25, .03),
}


def length(grid, a, b, detour=1.15):
    pa, pb = grid['buses'][a], grid['buses'][b]
    return max(.3, hypot(pa['x']-pb['x'], pa['y']-pb['y'])*detour)


def add_bus(grid, bid, name, kv, x, y, kind, **extra):
    grid['buses'][bid] = dict(id=bid, name=name, kv=kv, x=round(x, 3), y=round(y, 3), kind=kind, **extra)
    return bid


def add_line(grid, bid, a, b, ltype, circuits=1, km=None, **extra):
    km = round(km if km is not None else length(grid, a, b), 3)
    amps = LINE_TYPES[ltype][6]*circuits
    kv = grid['buses'][a]['kv']
    grid['branches'][bid] = dict(id=bid, kind='line', type=ltype, a=a, b=b, km=km, circuits=circuits, kv=kv,
                                 amps=amps, mva=round(3**.5*kv*amps/1000, 2), closed=True, tripped=False,
                                 repair_until=None, fault=None, **extra)
    return bid


def add_transformer(grid, bid, hv, lv, ttype, mva, **extra):
    grid['branches'][bid] = dict(id=bid, kind='transformer', type=ttype, a=hv, b=lv, mva=mva,
                                 kv=grid['buses'][hv]['kv'], closed=True, tripped=False, repair_until=None, fault=None, **extra)
    return bid


def in_service(branch):
    """Closed, not tripped and not waiting for repair. A sectionalised feeder runs while its faulted section is repaired."""
    return (branch['closed'] and not branch['tripped'] and not branch.get('planned') and not branch.get('retired')
            and (branch['repair_until'] is None or branch.get('section_out') is not None))


def hvac_active(grid):
    """The AC interconnector carries power: commissioned, a cable and the station transformer in service."""
    ac = grid.get('hvac')
    if not ac or ac['capacity'] <= 0:
        return False
    return any(in_service(grid['branches'][c]) for c in ac['cables']) and in_service(grid['branches'][ac['transformer']])


def update_source(grid):
    """The island's voltage reference: the mainland AC grid when the HVAC link is in service, otherwise
    the HVDC converter. With the AC link in service the HVDC runs as a controlled power injection."""
    grid['source_bus'] = 'mainland_ac' if hvac_active(grid) else 'mainland'
    return grid['source_bus']


def energized(grid):
    """Buses connected to a voltage source: the mainland link, or an enabled grid-forming battery."""
    roots = [grid['source_bus']]
    roots += [s['bus'] for s in forming_units(grid) if s.get('forming_active')]
    adjacency = {}
    for br in grid['branches'].values():
        if in_service(br):
            adjacency.setdefault(br['a'], []).append(br['b'])
            adjacency.setdefault(br['b'], []).append(br['a'])
    seen, stack = set(roots), list(roots)
    while stack:
        for nxt in adjacency.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def forming_units(grid):
    return list(grid['storage'].values())+list(grid.get('oil',{}).values())


def model(grid, devices):
    """GridModel of the whole network; out-of-service branches are built but disabled."""
    elements = []
    ac_source = grid['source_bus'] == 'mainland_ac'
    for br in grid['branches'].values():
        if br.get('planned') or (ac_source and br['id'] == 'hvdc'):
            continue
        if br['kind'] == 'line':
            r1, x1, c1, r0, x0, c0, amps, *_ = LINE_TYPES[br['type']]
            n = br['circuits']
            rating = br.get('rating_factor',1.)
            elements.append(Line(br['id'], br['a'], br['b'], br['km'], r1/n/rating, x1/n, r0/n/rating, x0/n, c1*n, c0*n, br.get('amps', amps*n),
                                 closed=in_service(br)))
        else:
            x, ll, nl = TRANSFORMER_TYPES[br['type']]
            hv, lv = grid['buses'][br['a']], grid['buses'][br['b']]
            elements.append(Transformer(br['id'], br['a'], br['b'], hv['kv'], lv['kv'], br['mva']*1000, x, ll, nl))
    for t in grid['turbines'].values():
        if t['status'] != 'construction':
            elements.append(Generator(t['id'], t['bus_lv'], .69, t['mw']*1100))
    for s in grid['storage'].values():
        if s['status'] != 'construction':
            kv = grid['buses'][s['bus']]['kv']
            elements.append(Generator(s['id'], s['bus'], kv, s['p_mw']*1100))
            if s['grid_forming']:
                elements.append(GridFormer(s['id']+'_gf', s['bus'], kv, max(50., 6*s['p_mw'])))
    for g in grid.get('oil',{}).values():
        kv=grid['buses'][g['bus']]['kv']
        elements.append(Generator(g['id'],g['bus'],kv,g['p_mw']*1100))
        elements.append(GridFormer(g['id']+'_gf',g['bus'],kv,max(20.,5*g['p_mw'])))
    if ac_source:
        mw = sum(p['mw'] for p in grid['link']['poles'])
        elements.append(Generator('hvdc_conv', grid['link']['bus'], 110., mw*1100))
    for d in devices.values():
        elements.append(Load(d['id'], d['bus'], grid['buses'][d['bus']]['kv'], 0.0, 1.0, vmin_pu=.7, vmax_pu=1.3))
    src = grid['buses'][grid['source_bus']]
    pu = 1.0 if ac_source else SOURCE_PU
    return GridModel(Source('island', grid['source_bus'], src['kv'], pu, SOURCE_MVASC, SOURCE_MVASC), elements, BASES_KV)


class Network:
    """Runtime companion of world.grid: the compiled solver and the latest solution. Not saved."""

    def __init__(self, grid, devices, backend='opendss'):
        self.grid, self.devices, self.backend = grid, devices, backend
        self.solver = None
        self.result = None
        self.dirty = True
        self.energized = set()

    def compile(self):
        update_source(self.grid)
        self.solver = create_solver(model(self.grid, self.devices), self.backend)
        for br in self.grid['branches'].values():
            if br.get('planned'):
                continue
            if br['kind'] == 'transformer' and not in_service(br):
                self.solver.set_enabled('transformer', br['id'], False)
            if br['kind'] == 'transformer' and br.get('tap', 1.0) != 1.0:
                self.solver.set_tap(br['id'], br['tap'])
        for s in forming_units(self.grid):
            if s['grid_forming'] and s['status'] != 'construction' and s.get('forming_active'):
                self.solver.set_enabled('vsource', s['id']+'_gf', True)
        self.energized = energized(self.grid)
        self.dirty = False

    def switch(self, branch_id):
        """Apply a branch's current service state to the compiled solver."""
        br = self.grid['branches'][branch_id]
        ac = self.grid.get('hvac') or {}
        if branch_id in ac.get('cables', ()) or branch_id == ac.get('transformer') or branch_id == 'hvdc':
            # The voltage reference may change (AC grid or HVDC converter): rebuild the circuit.
            update_source(self.grid)
            self.dirty = True
            self.energized = energized(self.grid)
            return
        if self.solver is not None:
            self.solver.set_enabled('line' if br['kind'] == 'line' else 'transformer', branch_id, in_service(br))
        self.energized = energized(self.grid)

    def set_tap(self, branch_id, tap):
        self.grid['branches'][branch_id]['tap'] = tap
        if self.solver is not None:
            self.solver.set_tap(branch_id, tap)

    def set_forming(self, storage_id, active):
        s = self.grid['storage'].get(storage_id) or self.grid.get('oil',{})[storage_id]
        s['forming_active'] = bool(active)
        if self.solver is not None and s['grid_forming']:
            self.solver.set_enabled('vsource', storage_id+'_gf', bool(active))
        self.energized = energized(self.grid)

    def solve(self, loads, generators):
        """loads/generators: {id: (MW, Mvar)}. Returns the solver Results. A solution that fails the
        plausibility check is retried once from a freshly built circuit (flat start)."""
        if self.dirty or self.solver is None:
            self.compile()
        kw = {k: (p*1000, q*1000) for k, (p, q) in loads.items()}
        gen = {k: (p*1000, q*1000) for k, (p, q) in generators.items()}
        scale = sum(abs(p) for p, _ in loads.values())+sum(abs(p) for p, _ in generators.values())+5
        for attempt in range(2):
            self.solver.set_powers(kw, gen)
            self.solver.solve()
            res = self.solver.results()
            if res.converged and plausible(res, scale):
                break
            res.converged = False
            if attempt == 0:
                self.compile()
        self.result = res
        return res


def plausible(res, scale):
    """Reject numerically broken solutions: non-finite values or losses beyond any physical scale."""
    from math import isfinite
    if not (isfinite(res.losses_mw) and isfinite(res.source_p_mw)) or abs(res.losses_mw) > .25*scale:
        return False
    return all(isfinite(v) for v in res.bus_vm.values())
