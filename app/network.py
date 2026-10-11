"""Real OpenDSS 110/35/10 kV AC network, individual 0.69 kV turbine transformers."""
from math import sqrt, tan, acos
from opendssdirect import dss
from .parameters import DISTRICTS, TURBINES
from .wind import commissioned
from .planning import fleet


class Network:
    def __init__(self, upgraded=False, game=None):
        self.d = dss.NewContext()
        self.collector_amps = 500 if upgraded else 300
        self.units=fleet(game or {'plants':[]})
        self.plants=(game or {}).get('plants',[])
        self.unit_buses={t['id'].lower():t['id'].lower() for t in TURBINES}
        self.extra_lines={};self.extra_transformers={};self.plant_buses={}
        c = [
            'clear', 'set defaultbasefrequency=50',
            'new circuit.coastal basekv=110 pu=1.02 phases=3 bus1=utility mvasc3=1000 mvasc1=800',
            'new transformer.grid phases=3 windings=2 buses=[utility hub] conns=[delta wye] kvs=[110 35] kvas=[31500 31500] xhl=10 %loadloss=.5 %noloadloss=.05',
            'new transformer.city phases=3 windings=2 buses=[hub city] conns=[delta wye] kvs=[35 10] kvas=[20000 20000] xhl=8 %loadloss=.6 %noloadloss=.08',
            'new load.aux bus1=hub phases=3 kv=35 kw=50 pf=.98 model=1',
            'new generator.bess bus1=hub phases=3 kv=35 kw=0 kvar=0 kva=6600 model=1 vminpu=.8 vmaxpu=1.2',
        ]
        for string in ('a','b'):
            for k in range(4):
                i = k+(0 if string=='a' else 4)
                t = TURBINES[i]['id'].lower()
                prev = 'hub' if k==0 else f'{string}{k}'
                bus = f'{string}{k+1}'
                c += [f'new line.{t} bus1={prev} bus2={bus} phases=3 length={2.5 if k==0 else .882} units=km r1=.12 x1=.10 r0=.36 x0=.30 c1=200 c0=100 normamps={self.collector_amps}',
                      f'new transformer.{t} phases=3 windings=2 buses=[{bus} {t}] conns=[delta wye] kvs=[35 .69] kvas=[5500 5500] xhl=6 %loadloss=.8 %noloadloss=.1',
                      f'new generator.{t} bus1={t} phases=3 kv=.69 kw=0 kvar=0 kva=5500 model=1 vminpu=.8 vmaxpu=1.2']
        for a in DISTRICTS:
            c += [f"new line.{a['id']} bus1=city bus2={a['id']} phases=3 length={a['km']} units=km r1=.12 x1=.09 r0=.36 x0=.27 c1=150 c0=70 normamps={a['amps']}",
                  f"new load.{a['id']} bus1={a['id']} phases=3 kv=10 kw=1 pf={a['pf']} model=1 vminpu=.75 vmaxpu=1.25"]
        for plant in self.plants:
            prefix=plant['id'].lower();p=plant['plan'];kv=p['collector_kv']
            nodes={n['id']:n for n in p['nodes']}
            root=next(n['id'] for n in p['nodes'] if n['kind']=='substation')
            bus=lambda nid:prefix+'_'+nid.lower()+'_bus'
            self.plant_buses[plant['id']]=[bus(n['id']) for n in p['nodes']]
            name=prefix+'__export'
            self.extra_transformers[name]=dict(kva=p['transformer_mva']*1000,plant=plant['id'])
            c.append(f"new transformer.{name} phases=3 windings=2 buses=[hub {bus(root)}] conns=[delta wye] kvs=[35 {kv}] kvas=[{p['transformer_mva']*1000} {p['transformer_mva']*1000}] xhl={p['transformer_x_pct']} %loadloss=.5 %noloadloss=.05")
            for n in p['nodes']:
                if n['kind']!='turbine':continue
                name=prefix+'_'+n['id'].lower();lv=name+'_lv';self.unit_buses[name]=lv
                self.extra_transformers[name]=dict(kva=n['transformer_mva']*1000,plant=plant['id'])
                self.plant_buses[plant['id']].append(lv)
                c += [f"new transformer.{name} phases=3 windings=2 buses=[{bus(n['id'])} {lv}] conns=[delta wye] kvs=[{kv} .69] kvas=[{n['transformer_mva']*1000} {n['transformer_mva']*1000}] xhl={n['transformer_x_pct']} %loadloss=.8 %noloadloss=.1",
                      f"new generator.{name} bus1={lv} phases=3 kv=.69 kw=0 kvar=0 kva={n['rated_mw']*1100} model=1 vminpu=.8 vmaxpu=1.2"]
            for edge in p['edges']:
                name=prefix+'_'+edge['id'].lower()
                self.extra_lines[name]=dict(amps=edge['amps'],plant=plant['id'],closed=edge['closed'])
                c.append(f"new line.{name} bus1={bus(edge['source'])} bus2={bus(edge['target'])} phases=3 length={edge['length_km']} units=km r1={edge['r_ohm_km']} x1={edge['x_ohm_km']} r0={edge['r_ohm_km']*3} x0={edge['x_ohm_km']*3} c1={edge['c_nf_km']} c0={edge['c_nf_km']/2} normamps={edge['amps']} enabled={'yes' if edge['closed'] else 'no'}")
        c += ['set voltagebases=[110 66 35 10 .69]', 'calcvoltagebases',
              'set mode=snapshot controlmode=off maxiterations=100 tolerance=.000001']
        self.d('\n'.join(c))

    def configure(self, game):
        self.enabled_buses = ['hub']
        self.d(f"edit transformer.city enabled={'yes' if game['breakers']['transformer'] else 'no'}")
        if game['breakers']['transformer']: self.enabled_buses.append('city')
        for i,t in enumerate(TURBINES):
            enabled = commissioned(game,i) and game['breakers']['farm'] and game['breakers']['collector_'+t['string']]
            name=t['id'].lower()
            for cls in ('line','transformer','generator'):
                self.d(f"edit {cls}.{name} enabled={'yes' if enabled else 'no'}")
            if enabled: self.enabled_buses.append(name)
        for a in DISTRICTS:
            enabled=game['breakers'][a['id']] and game['breakers']['transformer']
            self.d(f"edit line.{a['id']} enabled={'yes' if enabled else 'no'}")
            self.d(f"edit load.{a['id']} enabled={'yes' if enabled else 'no'}")
            if enabled: self.enabled_buses.append(a['id'])
        for plant in self.plants:
            on=game['breakers'].get('plant_'+plant['id'],True)
            if on:self.enabled_buses.extend(self.plant_buses[plant['id']])
            for name,info in self.extra_transformers.items():
                if info['plant']==plant['id']:self.d(f"edit transformer.{name} enabled={'yes' if on else 'no'}")
            for name,info in self.extra_lines.items():
                if info['plant']==plant['id']:self.d(f"edit line.{name} enabled={'yes' if on and info['closed'] else 'no'}")
            for t in self.units:
                if t['farm_id']==plant['id']:self.d(f"edit generator.{t['id'].lower()} enabled={'yes' if on else 'no'}")

    def solve(self, wind, loads, battery_mw, battery_mva=6.6, voltage_control=True):
        d = self.d
        for i, mw in enumerate(wind):
            d.Generators.Name(self.units[i]['id'].lower())
            d.Generators.kW(mw*1000)
            d.Generators.kvar(0)
        for area in DISTRICTS:
            d.Loads.Name(area['id'])
            d.Loads.kW(loads[area['id']]*1000)
            d.Loads.PF(area['pf'])
        d.Generators.Name('bess')
        d.Generators.kW(battery_mw*1000)
        d.Generators.kvar(0)
        d.Solution.Solve()
        q = 0.
        if voltage_control:
            for i,mw in enumerate(wind):
                if mw <= 0: continue
                name=self.units[i]['id'].lower()
                d.Circuit.SetActiveBus(self.unit_buses[name])
                v=min(d.Bus.puVmagAngle()[::2])
                qcap=sqrt(max(0,(self.units[i]['rated_mw']*1.1)**2-mw**2))
                wq=max(-qcap,min(qcap,(1.01-v)*45))
                d.Generators.Name(name); d.Generators.kvar(wq*1000)
            d.Circuit.SetActiveBus('hub')
            voltage = min(d.Bus.puVmagAngle()[::2])
            # Volt-var droop with deadband and inverter capability circle.
            error = 1.02-voltage
            qmax = sqrt(max(0,battery_mva*battery_mva-battery_mw*battery_mw))
            q = max(-qmax,min(qmax,(error-.005*(1 if error>0 else -1))*150)) if abs(error)>.005 else 0.
            d.Generators.Name('bess'); d.Generators.kvar(q*1000)
            d.Solution.Solve()
        if not d.Solution.Converged():
            raise RuntimeError('Power flow did not converge; action was not saved.')
        volts = {}
        for bus in ['hub','city']+[a['id'] for a in DISTRICTS]+[t['id'].lower() for t in TURBINES]+[b for buses in self.plant_buses.values() for b in buses]:
            d.Circuit.SetActiveBus(bus)
            volts[bus] = min(d.Bus.puVmagAngle()[::2]) if bus in getattr(self,'enabled_buses',[]) else 0.
        lines = {}
        for name, amps in [(t['id'].lower(),self.collector_amps) for t in TURBINES]+[(a['id'],a['amps']) for a in DISTRICTS]+[(n,v['amps']) for n,v in self.extra_lines.items()]:
            d.Circuit.SetActiveElement('line.'+name)
            current = max(d.CktElement.CurrentsMagAng()[::2])
            p = d.CktElement.Powers()
            lines[name] = dict(amps=current, loading_pct=current/amps*100,p_mw=sum(p[:6:2])/1000)
        transformer = {}
        for name,kva in [('grid',31500),('city',20000)]+[(n,v['kva']) for n,v in self.extra_transformers.items()]:
            d.Circuit.SetActiveElement('transformer.'+name)
            p = d.CktElement.Powers()
            transformer[name] = sqrt(sum(p[:8:2])**2+sum(p[1:8:2])**2)/kva*100
        loss = d.Circuit.Losses()[0]/1e6
        grid = -d.Circuit.TotalPower()[0]/1000
        balance = sum(wind)+battery_mw+grid-sum(loads.values())-.05-loss
        return dict(voltages=volts, lines=lines, transformer_pct=transformer,
                    losses_mw=loss, grid_mw=grid, battery_mvar=q,balance_error_mw=balance,
                    min_voltage=min(v for v in volts.values() if v>0),max_voltage=max(volts.values()),
                    max_loading_pct=max(max(a['loading_pct'] for a in lines.values()),*transformer.values()))

    def short_circuit(self, target):
        """Grid-only 3φ bolted fault contribution; IBR contribution deliberately excluded."""
        mapping = {'collector_a':('a1','wt01'),'collector_b':('b1','wt05'),
                   'harbor':('harbor','harbor'),'transformer':('city','harbor')}
        bus, line = mapping[target]
        d = self.d
        # A fresh context is used exclusively for fault study.
        for name in d.Generators.AllNames(): d(f'edit generator.{name} enabled=no')
        for name in d.Loads.AllNames(): d(f'edit load.{name} enabled=no')
        d(f'new fault.study phases=3 bus1={bus} r=.01')
        d('set mode=snapshot loadmodel=admittance'); d.Solution.Solve()
        if not d.Solution.Converged(): raise RuntimeError('Short-circuit calculation did not converge.')
        d.Circuit.SetActiveElement('fault.study')
        current = max(d.CktElement.CurrentsMagAng()[::2])
        d.Circuit.SetActiveBus(bus)
        voltage = min(d.Bus.puVmagAngle()[::2])
        return dict(current_a=current, fault_voltage_pu=voltage, fault_bus=bus,
                    basis='OpenDSS three-phase bolted fault; grid contribution only, excluding converter fault dynamics')
