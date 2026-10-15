"""Game grid model: the 110/35/10 kV coastal network with individual 0.69 kV turbine transformers.

This module turns game state into an app.solvers.model description and interprets the results;
the numerical work is done by an electrical backend from app.solvers.
"""
from math import sqrt
from .parameters import DISTRICTS, TURBINES
from .wind import commissioned
from .planning import fleet
from .solvers import GridModel, Generator, Line, Load, Source, SolverError, Transformer, create_solver


class Network:
    def __init__(self, upgraded=False, game=None):
        self.collector_amps = 500 if upgraded else 300
        self.units=fleet(game or {'plants':[]})
        self.plants=(game or {}).get('plants',[])
        self.unit_buses={t['id'].lower():t['id'].lower() for t in TURBINES}
        self.extra_lines={};self.extra_transformers={};self.plant_buses={}
        e = [
            Transformer('grid','utility','hub',110,35,31500,10,.5,.05),
            Transformer('city','hub','city',35,10,20000,8,.6,.08),
            Load('aux','hub',35,50,.98),
            Generator('bess','hub',35,6600),
        ]
        for string in ('a','b'):
            for k in range(4):
                i = k+(0 if string=='a' else 4)
                t = TURBINES[i]['id'].lower()
                prev = 'hub' if k==0 else f'{string}{k}'
                bus = f'{string}{k+1}'
                e += [Line(t,prev,bus,2.5 if k==0 else .882,.12,.10,.36,.30,200,100,self.collector_amps),
                      Transformer(t,bus,t,35,.69,5500,6,.8,.1),
                      Generator(t,t,.69,5500)]
        for a in DISTRICTS:
            e += [Line(a['id'],'city',a['id'],a['km'],.12,.09,.36,.27,150,70,a['amps']),
                  Load(a['id'],a['id'],10,1,a['pf'],.75,1.25)]
        for plant in self.plants:
            prefix=plant['id'].lower();p=plant['plan'];kv=p['collector_kv']
            root=next(n['id'] for n in p['nodes'] if n['kind']=='substation')
            bus=lambda nid:prefix+'_'+nid.lower()+'_bus'
            self.plant_buses[plant['id']]=[bus(n['id']) for n in p['nodes']]
            name=prefix+'__export'
            self.extra_transformers[name]=dict(kva=p['transformer_mva']*1000,plant=plant['id'])
            e.append(Transformer(name,'hub',bus(root),35,kv,p['transformer_mva']*1000,p['transformer_x_pct'],.5,.05))
            for n in p['nodes']:
                if n['kind']!='turbine':continue
                name=prefix+'_'+n['id'].lower();lv=name+'_lv';self.unit_buses[name]=lv
                self.extra_transformers[name]=dict(kva=n['transformer_mva']*1000,plant=plant['id'])
                self.plant_buses[plant['id']].append(lv)
                e += [Transformer(name,bus(n['id']),lv,kv,.69,n['transformer_mva']*1000,n['transformer_x_pct'],.8,.1),
                      Generator(name,lv,.69,n['rated_mw']*1100)]
            for edge in p['edges']:
                name=prefix+'_'+edge['id'].lower()
                self.extra_lines[name]=dict(amps=edge['amps'],plant=plant['id'],closed=edge['closed'])
                e.append(Line(name,bus(edge['source']),bus(edge['target']),edge['length_km'],edge['r_ohm_km'],edge['x_ohm_km'],
                              edge['r_ohm_km']*3,edge['x_ohm_km']*3,edge['c_nf_km'],edge['c_nf_km']/2,edge['amps'],edge['closed']))
        self.solver = create_solver(GridModel(Source('coastal','utility',110,1.02,1000,800),e,(110,66,35,10,.69),50))

    def configure(self, game):
        s = self.solver
        self.enabled_buses = ['hub']
        s.set_enabled('transformer','city',game['breakers']['transformer'])
        if game['breakers']['transformer']: self.enabled_buses.append('city')
        for i,t in enumerate(TURBINES):
            enabled = commissioned(game,i) and game['breakers']['farm'] and game['breakers']['collector_'+t['string']]
            name=t['id'].lower()
            for cls in ('line','transformer','generator'):
                s.set_enabled(cls,name,enabled)
            if enabled: self.enabled_buses.append(name)
        for a in DISTRICTS:
            enabled=game['breakers'][a['id']] and game['breakers']['transformer']
            s.set_enabled('line',a['id'],enabled)
            s.set_enabled('load',a['id'],enabled)
            if enabled: self.enabled_buses.append(a['id'])
        for plant in self.plants:
            on=game['breakers'].get('plant_'+plant['id'],True)
            if on:self.enabled_buses.extend(self.plant_buses[plant['id']])
            for name,info in self.extra_transformers.items():
                if info['plant']==plant['id']:s.set_enabled('transformer',name,on)
            for name,info in self.extra_lines.items():
                if info['plant']==plant['id']:s.set_enabled('line',name,on and info['closed'])
            for t in self.units:
                if t['farm_id']==plant['id']:s.set_enabled('generator',t['id'].lower(),on)

    def solve(self, wind, loads, battery_mw, battery_mva=6.6, voltage_control=True):
        s = self.solver
        for i, mw in enumerate(wind):
            s.set_generator(self.units[i]['id'].lower(),mw*1000,0)
        for area in DISTRICTS:
            s.set_load(area['id'],loads[area['id']]*1000,area['pf'])
        s.set_generator('bess',battery_mw*1000,0)
        converged = s.solve()
        q = 0.
        if voltage_control:
            for i,mw in enumerate(wind):
                if mw <= 0: continue
                name=self.units[i]['id'].lower()
                v=s.bus_voltage_pu(self.unit_buses[name])
                qcap=sqrt(max(0,(self.units[i]['rated_mw']*1.1)**2-mw**2))
                wq=max(-qcap,min(qcap,(1.01-v)*45))
                s.set_generator(name,kvar=wq*1000)
            voltage = s.bus_voltage_pu('hub')
            # Volt-var droop with deadband and inverter capability circle.
            error = 1.02-voltage
            qmax = sqrt(max(0,battery_mva*battery_mva-battery_mw*battery_mw))
            q = max(-qmax,min(qmax,(error-.005*(1 if error>0 else -1))*150)) if abs(error)>.005 else 0.
            s.set_generator('bess',kvar=q*1000)
            converged = s.solve()
        if not converged:
            raise SolverError('Power flow did not converge; action was not saved.')
        enabled = set(getattr(self,'enabled_buses',[]))
        volts = {bus: s.bus_voltage_pu(bus) if bus in enabled else 0.
                 for bus in ['hub','city']+[a['id'] for a in DISTRICTS]+[t['id'].lower() for t in TURBINES]+[b for buses in self.plant_buses.values() for b in buses]}
        lines = {}
        for name, amps in [(t['id'].lower(),self.collector_amps) for t in TURBINES]+[(a['id'],a['amps']) for a in DISTRICTS]+[(n,v['amps']) for n,v in self.extra_lines.items()]:
            current, p_mw = s.line_flow(name)
            lines[name] = dict(amps=current, loading_pct=current/amps*100,p_mw=p_mw)
        transformer = {}
        for name,kva in [('grid',31500),('city',20000)]+[(n,v['kva']) for n,v in self.extra_transformers.items()]:
            p, qt = s.transformer_flow(name)
            transformer[name] = sqrt(p**2+qt**2)/kva*100
        loss = s.losses_mw()
        grid = s.source_mw()
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
        current, voltage = self.solver.short_circuit(bus,.01)
        return dict(current_a=current, fault_voltage_pu=voltage, fault_bus=bus,
                    basis='OpenDSS three-phase bolted fault; grid contribution only, excluding converter fault dynamics')
