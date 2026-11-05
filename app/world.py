"""World Simulation Core: the one authoritative state, the event clock and the main loop (spec 2-3).

Order of work at each minute boundary (spec 3.2):
  1. energy of the interval just ended is integrated from the last solved state (MW x time -> MWh);
  2. on an hour/day/month boundary the completed period is settled first (production, bills, markets,
     wages, demography), then the society and economy make plans for the next period from what is known
     now (forecasts, not the future);
  3. the load engine requests P/Q, the operator dispatches, the AC power flow is solved and protection
     checks the result;
  4. events queued inside the minute (equipment starts at :20:15, a breaker trip at :34:12.4) are
     handled at their own timestamps: integrate up to the event, apply it, solve again, continue.
Modules own their data (society: POPs; economy: firms; load engine: devices; energy: grid); solvers are
tools that read a snapshot and return results.
"""
import time as _time
import hashlib
import json
from collections import deque
from math import sqrt
from . import construction as C
from . import economy as E
from . import energy as N
from . import grid as G
from . import loads as L
from . import society as S
from . import weather as W
from . import retail as R
from . import finance as F
from . import generation as O
from . import history as H
from .exchange import message
from . import protection as P
from . import dynamics as D
from . import materials as M
from . import water as U
from .metrics import Timing
from .calendar import DAY, HOUR, is_rest_day, label, month_index, parts, stamp
from .events import EventQueue
from .ledger import Ledger
from .params import (EXPORT_FEE, GRID_OM_SEK_KM_YEAR, INDUSTRY_CONTRACT_DISCOUNT, LOCAL_CONSTRUCTION_SHARE,
                     NETWORK_FEE, PRICE_BASE, RETAIL_MARGIN, STORAGE_OM_SEK_MW_YEAR, WIND_OM_SEK_MW_YEAR)
from .rng import Streams
from . import __version__ as VERSION

SAVE_FORMAT = 'powerbolaget.world'
LOST = 1e12          # 'waiting for the grid' (finite, so saves stay valid JSON)
SCHEMA = 1
HISTORY_HOURS = 24*90


class World:
    def __init__(self, seed=1, state=None, backend='opendss'):
        self.backend = backend
        self.archive=H.Archive((state or {}).get('archive'))
        self.messages=(state or {}).get('messages',{})
        self.rms=(state or {}).get('rms',{})
        self.frequency_hz=(state or {}).get('frequency_hz',50.)
        self.physics_valid=(state or {}).get('physics_valid',True)
        if state is None:
            self._fresh(seed)
        else:
            self._load(state)
        self.material_baseline=(state or {}).get('material_baseline') or M.baseline(self)
        self.conservation_history=(state or {}).get('conservation_history',[])
        if getattr(self, 'network', None) is None:
            self.network = G.Network(self.grid, self.devices, backend)
        self.flows = None
        self.t_now = float(self.minute)
        self.minute_series = deque(maxlen=1440)
        self.entity_hist = {k:deque(v,maxlen=168) for k,v in (state or {}).get('entity_hist',{}).items()}
        self.settled_until=(state or {}).get('settled_until',self.history_hour[-1]['t']+60 if self.history_hour else 0)
        self.perf = dict(minutes=0, solve_ms=deque(maxlen=2000), step_ms=deque(maxlen=2000), failures=0)
        self.perf.update(all_solve=Timing(),all_step=Timing())
        self.ferry_orders = []
        self.hvdc_setpoint = 0.
        self.consumer_orders, self.lodging_orders, self.food_orders, self.construction_orders = {}, {}, [], []
        self.command_receipts = (state or {}).get('command_receipts', {})

    # ------------------------------------------------------------ creation and saves
    def _fresh(self, seed):
        from .worldgen import generate
        self.network = None
        self.seed = int(seed)
        self.minute = 0
        self.streams = Streams(self.seed)
        self.events = EventQueue()
        self.ledger = Ledger()
        self.devices = {}
        self.projects = {}
        self.counters = {}
        self.settings = dict(link_margin=.03, storage_reserve=.35)
        self.retail_policy, self.retail_version, self.contracts = R.default_policy(), 1, {}
        self.price_observations = dict(sum=0., hours=0)
        self.demography = dict(month=self._blank_demo(), months=[])
        self.history_hour = deque(maxlen=HISTORY_HOURS)
        self.history_day = []
        self.logbook = deque(maxlen=400)
        self.outage = {}                # zone -> deque of daily customer-weighted outage hours
        self.price_avg = PRICE_BASE
        self.contract_price = PRICE_BASE
        self.last_losses = 0.
        self.commands = []
        self.acc = self._blank_acc()
        self.weather_now = W.instant(self.seed, 0.)
        self.construction_backlog = 0.
        self.outage_today = {}
        generate(self)
        U.create(self)
        self.network = G.Network(self.grid, self.devices, self.backend)
        self.demography['month']['start'] = S.residents(self)
        self.plan_hour(0, prime=True)
        self.log('world', f'{self.island_name()} enters year 1 of the Fantasy Era', None)

    def _load(self, s):
        self.network = None
        if s.get('format') != SAVE_FORMAT or s.get('schema') != SCHEMA:
            raise ValueError('Not a Powerbolaget world save of this version.')
        self.seed = int(s['seed'])
        self.minute = int(s['minute'])
        self.streams = Streams(self.seed, s['streams'])
        self.events = EventQueue(s['events'])
        self.ledger = Ledger(s['ledger'])
        for key in ('zones', 'grid', 'devices', 'pops', 'firms', 'jobs', 'markets', 'projects', 'counters', 'settings',
                    'demography', 'substations', 'history_day', 'commands', 'acc', 'price_avg', 'contract_price',
                    'last_losses', 'construction_backlog', 'outage_today'):
            setattr(self, key, s[key])
        self.history_hour = deque(s['history_hour'], maxlen=HISTORY_HOURS)
        self.retail_policy = s.get('retail_policy', R.default_policy())
        self.retail_version = s.get('retail_version', 1)
        self.contracts = s.get('contracts', {})
        self.price_observations = s.get('price_observations', dict(sum=0., hours=0))
        self.grid.setdefault('oil',{})
        P.add_ties(self)
        self.water=s.get('water')
        if self.water is None:
            S.refresh_stats(self)
            U.create(self)
        self.events.cancel(lambda e: e['kind'] == 'interconnector')
        for br in self.grid['branches'].values():
            fault=br.get('active_fault')
            if not fault or self.events.pending(lambda e:e['kind']=='fault_guard' and e.get('id')==br['id']):
                continue
            relay=next(iter(self.events.pending(lambda e:e['kind'] in ('relay_check','relay_trip') and e.get('id')==br['id'])),{})
            when=max(self.minute+1e-6,fault.get('since',self.minute)+P.PERSISTENT_FAULT_BACKUP_S/60)
            self.events.push(when,'fault_guard','protection',id=br['id'],permanent=relay.get('permanent',True),
                             cause=relay.get('cause','persisted severe fault'))
        legacy = self.projects.get('tso_hvac')
        if legacy and legacy['status'] == 'building':
            legacy['status'] = 'cancelled'
        self.logbook = deque(s['logbook'], maxlen=400)
        self.outage = {k: deque(v, maxlen=120) for k, v in s['outage'].items()}
        self.zone_by_id = {z['id']: z for z in self.zones}
        self.weather_now = W.instant(self.seed, self.minute/1440)
        S.refresh_stats(self)

    def state(self):
        """Everything needed to continue the game exactly (spec 10.3); display caches are left out."""
        return dict(format=SAVE_FORMAT, schema=SCHEMA, version=VERSION, saved=stamp(self.minute), seed=self.seed,
                    minute=self.minute, streams=self.streams.state(), events=self.events.state(),
                    ledger=self.ledger.state(), zones=self.zones, grid=self.grid, devices=self.devices, pops=self.pops,
                    firms=self.firms, jobs=self.jobs, markets=self.markets, projects=self.projects, counters=self.counters,
                    settings=self.settings, demography=self.demography, substations=self.substations,
                    history_hour=list(self.history_hour), history_day=self.history_day, logbook=list(self.logbook),
                    outage={k: list(v) for k, v in self.outage.items()}, commands=self.commands, acc=self.acc,
                    price_avg=self.price_avg, contract_price=self.contract_price, last_losses=self.last_losses,
                    construction_backlog=self.construction_backlog, outage_today=self.outage_today,
                    command_receipts=self.command_receipts, retail_policy=self.retail_policy,
                    retail_version=self.retail_version, contracts=self.contracts, price_observations=self.price_observations,
                    archive=self.archive.state(),messages=self.messages,settled_until=self.settled_until,
                    entity_hist={k:list(v) for k,v in self.entity_hist.items()},rms=self.rms,frequency_hz=self.frequency_hz,
                    water=self.water,material_baseline=self.material_baseline,conservation_history=self.conservation_history,
                    physics_valid=self.physics_valid)

    @staticmethod
    def _blank_demo():
        return dict(births=0, deaths=0, immigration=0, emigration=0, internal_moves=0, tourist_arrivals=0,
                    tourist_departures=0, tourists_turned_away=0, holiday_in=0, holiday_out=0, seasonal_in=0, seasonal_out=0,
                    start=0)

    @staticmethod
    def _blank_acc():
        return dict(load_req=0., load_srv=0., wind_avail=0., wind=0., link_import=0., link_export=0., battery_dis=0.,
                    battery_ch=0., oil=0., losses=0., minutes=0., vmin=2., unserved_zone={}, maxload=0., import_cost=0.,
                    export_revenue=0.)

    def island_name(self):
        from .island import NAME
        return NAME

    def next_id(self, kind):
        self.counters[kind] = self.counters.get(kind, 0)+1
        return self.counters[kind]

    def log(self, kind, text, zone, **refs):
        entry = dict(id=self.next_id('log'), t=round(self.t_now if hasattr(self, 't_now') else self.minute, 3),
                     label=label(self.minute), kind=kind, text=text, zone=zone, **refs)
        self.logbook.append(entry)
        if D.active(self):
            win=D.window(self)
            if win and kind in ('protection','fault','restore','shedding','numerical'):
                win['actions'].append(dict(seconds=(self.t_now-win['t'])*60,kind=kind,text=text,**refs))
        return entry

    # ------------------------------------------------------------ external boundary
    def energy_price(self, t):
        """Mainland reference electricity price, SEK/kWh, constant within each hour."""
        hour_start = t-(t % 60)
        day = hour_start/1440
        h = (hour_start % 1440)/60
        doy = parts(hour_start)['doy']
        from math import cos, pi
        seasonal = 1+.32*cos(2*pi*(doy-15)/365)
        shape = .82+.22*L.bump(h, 8.5, 1.6)+.32*L.bump(h, 18.5, 2.0)-.04*L.bump(h, 3.5, 2.5)
        if is_rest_day(hour_start):
            shape = .85+.18*L.bump(h, 18.5, 2.4)
        weather = W.noise(self.seed+101, day, 20, 4.)*.22-.12*W.noise(self.seed, day, 0)
        from math import exp
        return max(.05, PRICE_BASE*seasonal*shape*exp(weather))

    def tariff(self, cls, t, owner=None):
        return R.price(self, cls, t, owner)

    def forecast(self, issued, t):
        return W.forecast(self.seed, issued/1440, t/1440)

    def zone_outage_hours(self, zone, days=30):
        d = self.outage.get(zone)
        if not d:
            return 0.
        return sum(list(d)[-days:])

    def pay_construction(self, payer, amount, minute, category):
        """Construction spending: a local share as work units from the island's construction firm, the rest off-island."""
        local = amount*LOCAL_CONSTRUCTION_SHARE
        cf = self.firms.get('f_construction')
        if cf and cf['status'] == 'operating':
            units = local/cf['price']
            self.ledger.transfer(payer, 'firm:f_construction', local, category, minute, 'construction', units)
            cf['today']['revenue'] += local
            cf['today']['sold'] += units
            self.construction_backlog = .97*self.construction_backlog+local
        else:
            self.ledger.transfer(payer, 'external', local, category, minute)
        self.ledger.transfer(payer, 'external', amount-local, category, minute)

    def start_firm_expansion(self, f, capex):
        pid = f"x{self.next_id('expansion')}"
        months = 8 if f['kind'] in ('services', 'hospitality') else 14
        self.projects[pid] = dict(id=pid, kind='expansion', firm=f['id'], cost=capex, paid=0., start=self.minute,
                                  finish=self.minute+months*30*DAY, status='building', zone=f['zone'],
                                  title=f"{f['name']}: capacity expansion", owner='firm:'+f['id'])
        self.events.push(self.minute+months*30*DAY, 'commission', 'commission', project=pid)
        self.log('economy', f"{f['name']} invests {capex/1e6:.0f} MSEK in more capacity", f['zone'], firm=f['id'], project=pid)

    # ------------------------------------------------------------ main loop
    def advance(self, minutes, budget_s=None):
        """Run the world forward by whole minutes (stops early if a wall-clock budget is exhausted)."""
        start = _time.perf_counter()
        end = self.minute+int(minutes)
        while self.minute < end:
            m = self.minute
            t0 = _time.perf_counter()
            self.t_now = float(m)
            self.boundary(m)
            self.solve_now(m)
            while True:
                ev = self.events.pop_before(m+1)
                if ev is None:
                    break
                te = max(ev['time'], self.t_now)
                self.integrate(te)
                changed=self.handle(ev)
                if changed is not False:
                    self.solve_now(te)
            self.integrate(float(m+1))
            self.minute = m+1
            self.perf['minutes'] += 1
            elapsed=(_time.perf_counter()-t0)*1000
            self.perf['step_ms'].append(elapsed)
            self.perf['all_step'].add(elapsed)
            if budget_s is not None and _time.perf_counter()-start > budget_s:
                break

    def boundary(self, m):
        if m % HOUR == 0:
            if m > 0:
                self.settle_hour(m-HOUR, m)
            if m % DAY == 0:
                if m > 0:
                    self.settle_day(m)
                p = parts(m)
                if p['day'] == 1:
                    if m > 0:
                        self.settle_month(m)
                    if p['month'] == 1 and m > 0:
                        self.contract_price = self.price_avg
                self.start_day(m)
            self.plan_hour(m)

    # ------------------------------------------------------------ minute physics
    def requests(self, t, w):
        ctx = dict(rest=is_rest_day(t))
        U.targets(self)
        out = {}
        for did, d in self.devices.items():
            if d['kind'] == 'residential':
                thermal, elec = L.heating_demand(d, t, w)
                d['heat_thermal_kw'], d['heat_electric_kw'] = thermal, elec
            p = max(0., L.request(d, t, w, ctx))
            if d['owner'][0] == 'firm' and self.firms[d['owner'][1]]['status'] not in ('operating', 'construction'):
                p = 0.
            out[did] = (p, L.q_from_p(p, d['pf']))
        return out

    def solve_now(self, t):
        """Requests, dispatch, power flow and protection at time t (minutes)."""
        w = self.weather_now = W.instant(self.seed, t/1440)
        for d in self.devices.values():
            if d['kind'] == 'equipment':
                L.step_equipment(d, t, d['bus'] in self.network.energized or self.network.dirty)
        if self.network.dirty:
            self.network.compile()
        reqs = self.requests(t, w)
        avail = N.available_wind(self, t, w)
        O.step(self,t,reqs,avail)
        N.sync_formers(self,t)
        wind_avail = sum(p for tid, p in avail.items() if self.grid['turbines'][tid]['bus_lv'] in self.network.energized)
        for s in self.grid['storage'].values():
            if s.get('forming_active') and s['soc'] <= .02:
                self.network.set_forming(s['id'], False)
                self.log('protection', f"{s['name']} is empty: the island grid collapses", None, storage=s['id'])
                self.grid_lost_turbines(t)
        served, turb, st = N.dispatch(self, t, reqs, avail)
        res = self._power_flow(reqs, served, turb, st)
        if res is not None and res.converged:
            cap = N.link_capacity(self)
            link = res.source_p_mw+(self.hvdc_setpoint if self.grid['source_bus'] == 'mainland_ac' else 0.)
            limit = cap*(1-self.settings['link_margin']/2)
            if cap > 0 and (link > limit+.3 or link < -limit-.3):
                # Correct the loss estimate once: shed or curtail exactly the excess and solve again.
                excess = link-limit if link > 0 else link+limit
                if excess > 0:
                    by_class = {}
                    for did in served:
                        if served[did] > 0:
                            by_class.setdefault(self.devices[did]['priority'], []).append(did)
                    N.shed(by_class, reqs, served, excess)
                else:
                    N.curtail(turb, -excess)
                res = self._power_flow(reqs, served, turb, st)
        self.apply_solution(t, w, reqs, served, turb, st, res)
        if self.flows is not None:
            self.flows['wind_avail'] = wind_avail

    def _power_flow(self, reqs, served, turb, st):
        loads = {did: (p*served[did], q*served[did]) for did, (p, q) in reqs.items()}
        gens = {}
        vm=(self.flows or {}).get('vm',{})
        for tid,tb in self.grid['turbines'].items():
            if tb['status']!='construction':
                pq=O.injection(tb,turb.get(tid,0.),vm.get(tb['bus_lv'],tb.get('vm',1.))) if tb['status']=='ok' and tb['grid_wait']<=self.t_now else (0.,0.)
                gens[tid]=pq
                if tid in turb:
                    turb[tid]=pq[0]
                tb['q']=pq[1]
        if self.grid['source_bus'] == 'mainland_ac':
            gens['hvdc_conv'] = (getattr(self, 'hvdc_setpoint', 0.), 0.)
        for sid, s in self.grid['storage'].items():
            if s['status'] != 'construction':
                gens[sid] = (0.,0.) if s.get('forming_active') or s['status']!='ok' else O.injection(s,st.get(sid,0.),vm.get(s['bus'],s.get('vm',1.)))
                st[sid]=gens[sid][0]
                s['q']=gens[sid][1]
        for gid,g in self.grid.get('oil',{}).items():
            p=g['p'] if g['status']=='ok' and g['state']=='running' and g['bus'] in self.network.energized else 0.
            gens[gid]=(0.,0.) if g.get('forming_active') else O.injection(g,p,vm.get(g['bus'],g.get('vm',1.)))
            g['q']=gens[gid][1]
            if not g.get('forming_active'):
                g['p']=gens[gid][0]
        t0 = _time.perf_counter()
        D.prepare(self,self.t_now)
        try:
            res = self.network.solve(loads, gens)
        except Exception as exc:     # a numerical failure is not a blackout
            self.physics_valid=False
            self.perf['failures'] += 1
            self.log('numerical', f'Power flow failed: {exc}', None)
            if D.active(self):
                D.finish(self,'numerical_failure')
            return None
        elapsed=(_time.perf_counter()-t0)*1000
        self.perf['solve_ms'].append(elapsed)
        self.perf['all_solve'].add(elapsed)
        if not res.converged:
            self.physics_valid=False
            self.perf['failures'] += 1
            self.log('numerical', 'Power flow did not converge; the last valid state is kept (numerical, not physical).', None)
            if D.active(self):
                D.finish(self,'numerical_failure')
        else:
            self.physics_valid=True
        return res

    def apply_solution(self, t, w, reqs, served, turb, st, res):
        grid = self.grid
        if res is None or not res.converged:
            if self.flows is None:
                self.flows = dict(t=t, link=0., losses=0., storage={}, loading={}, dev={}, turb={}, vm={})
            self.messages['PhysicalResult']=message(self,'PhysicalResult',t,t,
                dict(converged=False,quality='held_last_valid_solution',last_valid_time=self.flows['t']))
            return
        self.last_losses = res.losses_mw
        for did,(actual,q) in res.loads.items():
            requested=reqs.get(did,(0.,0.))[0]
            if requested>1e-9 and actual<requested*served[did]*(1-1e-6):
                served[did]=max(0.,min(served[did],actual/requested))
        for tid in turb:
            if tid in res.generators:
                turb[tid]=res.generators[tid][0]
                grid['turbines'][tid]['q']=res.generators[tid][1]
        for sid in st:
            if sid in res.generators and not grid['storage'][sid].get('forming_active'):
                st[sid]=res.generators[sid][0]
        for gid,g in grid.get('oil',{}).items():
            if gid in res.generators and not g.get('forming_active'):
                g['p'],g['q']=res.generators[gid]
                g['p']=min(g['p_mw'],max(0.,g['p']))
        storage = dict(st)
        oil={gid:(res.formers.get(gid+'_gf',(0.,0.))[0] if g.get('forming_active') else
                  g['p'] if g['state']=='running' and g['status']=='ok' and g['bus'] in self.network.energized else 0.)
             for gid,g in grid.get('oil',{}).items()}
        for gid,p in oil.items():
            grid['oil'][gid]['p']=p
            if grid['oil'][gid].get('forming_active'):
                grid['oil'][gid]['q']=res.formers.get(gid+'_gf',(0.,0.))[1]
        for sid, s in grid['storage'].items():
            if s.get('forming_active'):
                name = sid+'_gf'
                storage[sid] = res.formers.get(name, (0., 0.))[0]
                s['q']=res.formers.get(name,(0.,0.))[1]
        loading = {}
        for bid, (p1, q1, p2, q2, imax) in res.branches.items():
            br = grid['branches'].get(bid)
            if br is None:
                continue
            s1, s2 = sqrt(p1*p1+q1*q1), sqrt(p2*p2+q2*q2)
            if br['kind'] == 'line':
                loading[bid] = imax/br['amps'] if br['amps'] else 0.
            else:
                loading[bid] = max(s1, s2)/br['mva'] if br['mva'] else 0.
        dc = res.generators.get('hvdc_conv',(self.hvdc_setpoint,0.))[0] if self.grid['source_bus'] == 'mainland_ac' else res.source_p_mw
        ac = res.source_p_mw if self.grid['source_bus'] == 'mainland_ac' else 0.
        self.flows = dict(t=t, link=dc+ac, link_dc=dc, link_ac=ac, link_q=res.source_q_mvar, losses=res.losses_mw, storage=storage,
                          fault_loss_mw=res.fault_mw,
                          loading=loading, branches=res.branches, vm=res.bus_vm, va=res.bus_va,
                          dev={did: (reqs[did][0], served[did]) for did in reqs}, turb=dict(turb),oil=oil)
        self.messages['PhysicalResult']=message(self,'PhysicalResult',t,t,dict(converged=True,
            requested_mw=sum(p for p,q in reqs.values()),served_mw=sum(reqs[k][0]*v for k,v in served.items()),
            wind_mw=sum(turb.values()),oil_mw=sum(oil.values()),link_mw=dc+ac,loss_mw=res.losses_mw))
        for did, (p, q) in reqs.items():
            d = self.devices[did]
            d['p'], d['q'], d['served'] = p, q, served[did]
            if d['kind'] == 'equipment' and served[did] < .999 and d['state'] in ('running', 'starting', 'warmup', 'stopping'):
                L.trip(d, t)
                if d['bus'] in self.network.energized:
                    self.log('shedding', f"{d['name']} at {self.firms[d['owner'][1]]['name']} interrupted by load shedding",
                             self.firms[d['owner'][1]]['zone'], device=did)
        for tid, p in turb.items():
            grid['turbines'][tid]['p'] = p
        for asset in list(grid['turbines'].values())+G.forming_units(grid):
            asset['vm']=res.bus_vm.get(asset.get('bus_lv',asset.get('bus')),0.)
        self.tap_control(res)
        # Protection: thermal overloads and turbine voltage ride-through limits.
        for bid in N.overload_check(self, t, loading):
            br = grid['branches'][bid]
            self.trip_branch(bid, t, 'overload protection', permanent=False)
            self.events.push(t+30, 'restore', 'restore', id=bid, reason='operator recloses after overload')
        for tid, tb in grid['turbines'].items():
            if tb['status'] != 'ok' or tb['grid_wait'] > t:
                continue
            v = res.bus_vm.get(tb['bus_lv'], 1.)
            if tb['bus_lv'] in self.network.energized and (v < .85 or v > 1.12):
                if 'voltage_deadline' not in tb:
                    delay=.15 if v<.2 else 2. if v<.85 else .2
                    tb['voltage_deadline']=t+delay/60
                    self.events.push(tb['voltage_deadline'],'voltage_trip','protection',id=tid)
            else:
                if tb.pop('voltage_deadline',None) is not None:
                    self.events.cancel(lambda e:e['kind']=='voltage_trip' and e.get('id')==tid)
        D.record(self,t)

    def tap_control(self, res):
        """On-load tap changers of the 110/20 kV units keep each substation's 20 kV busbar within
        1.00-1.04 pu, one 1.25 % step per minute at most."""
        regulated = [(sub['mv_bus'], sub['transformers']) for sub in self.substations.values()]
        if 't_ind_kal_1' in self.grid['branches']:
            regulated.append(('ind_kal', ['t_ind_kal_1', 't_ind_kal_2']))
        ac = self.grid.get('hvac')
        if ac and not self.grid['branches'][ac['transformer']].get('planned'):
            regulated.append(('stk_110', [ac['transformer']]))
        for bus, units in regulated:
            v = res.bus_vm.get(bus)
            if v is None or bus not in self.network.energized:
                continue
            step = .0125 if v < 1.0 else -.0125 if v > 1.04 else 0.
            for bid in units:
                br = self.grid['branches'][bid]
                if br.get('tap_minute')==int(self.t_now):
                    continue
                br['tap_minute']=int(self.t_now)
                tap = br.get('tap', 1.0)
                new = round(min(1.1, max(.9, tap+step)), 4)
                if new != tap:
                    self.network.set_tap(bid, new)

    def integrate(self, t_to):
        """Book the interval [t_now, t_to) with the last solved flows (piecewise constant)."""
        t_from = self.t_now
        dt = t_to-t_from
        if dt <= 0 or self.flows is None:
            self.t_now = max(self.t_now, t_to)
            return
        h = dt/60
        if not self.physics_valid:
            self.archive.invalid(t_from,t_to)
        f = self.flows
        acc = self.acc
        w = self.weather_now
        load_req = load_srv = 0.
        unserved = acc['unserved_zone']
        for did, (p, srv) in f['dev'].items():
            d = self.devices.get(did)
            if d is None:
                continue
            d['e_req'] += p*h
            d['e_srv'] += p*srv*h
            load_req += p
            load_srv += p*srv
            if srv < .999:
                zone = d['owner'][1] if d['owner'][0] == 'zone' else self.firms[d['owner'][1]]['zone']
                unserved[zone] = unserved.get(zone, 0.)+p*(1-srv)*h
            if d['kind'] == 'equipment' and d['state'] == 'running' and srv >= .999:
                d['run_min'] += dt
            elif d['kind'] == 'residential':
                L.update_thermal(d, w, d['heat_thermal_kw'], srv, dt)
                if srv < .999:
                    zid = d['owner'][1]
                    d['outage_min'] = d.get('outage_min', 0.)+dt*(1-srv)
        wind = sum(f['turb'].values())
        for tid, p in f['turb'].items():
            tb = self.grid['turbines'].get(tid)
            if tb:
                tb['energy_mwh'] += p*h
        for sid, p in f['storage'].items():
            s = self.grid['storage'].get(sid)
            if not s or s['status'] != 'ok':
                continue
            if p >= 0:
                s['soc'] = max(0., s['soc']-p*h/s['e_mwh'])
                acc['battery_dis'] += p*h
            else:
                s['soc'] = min(1., s['soc']-p*h*s['eff']/s['e_mwh'])
                acc['battery_ch'] -= p*h
            s['p'] = p
            s['cycles_mwh'] += abs(p)*h
            O.age_storage(s,h)
        O.integrate(self,h,f.get('oil',{}))
        U.integrate(self,h)
        acc['oil']=acc.get('oil',0.)+sum(f.get('oil',{}).values())*h
        price = self.energy_price(t_from)
        if f['link'] >= 0:
            acc['link_import'] += f['link']*h
            acc['import_cost'] += f['link']*h*price*1000
        else:
            acc['link_export'] -= f['link']*h
            acc['export_revenue'] -= f['link']*h*(price-EXPORT_FEE)*1000
        acc['load_req'] += load_req*h
        acc['load_srv'] += load_srv*h
        acc['wind'] += wind*h
        acc['wind_avail'] += f.get('wind_avail', wind)*h
        acc['losses'] += f['losses']*h
        acc['minutes'] += dt
        acc['maxload'] = max(acc['maxload'], load_req)
        if f['vm']:
            valid=[v for b,v in f['vm'].items() if b in self.network.energized and v>.2]
            vmin=min(valid,default=0. if self.network.energized else 1.)
            acc['vmin'] = min(acc['vmin'], vmin)
        if dt >= .999 or t_to == int(t_to):
            self.minute_series.append((round(t_from, 3), round(load_req, 3), round(load_srv, 3), round(wind, 3),
                                       round(f['link'], 3), round(sum(f['storage'].values()), 3)))
            self.archive.minute(self,t_to)
        self.t_now = t_to

    # ------------------------------------------------------------ events
    def handle(self, ev):
        kind = ev['kind']
        t = ev['time']
        if kind == 'equipment':
            d = self.devices.get(ev['device'])
            if d:
                L.command(d, t, ev['on'])
        elif kind == 'fault':
            self.fault(ev)
        elif kind == 'relay_trip':
            self.clear_fault(ev)
        elif kind == 'relay_check':
            return self.relay_check(ev)
        elif kind == 'fault_guard':
            return self.fault_guard(ev)
        elif kind == 'rms_step':
            D.step(self,t)
        elif kind == 'voltage_trip':
            tb=self.grid['turbines'].get(ev['id'])
            if tb and tb.get('voltage_deadline')==t and tb['status']=='ok' and (tb.get('vm',1.)<.85 or tb.get('vm',1.)>1.12):
                tb['grid_wait']=t+10
                tb.pop('voltage_deadline',None)
                self.log('protection',f"{tb['id']} voltage ride-through timer expired",None,turbine=tb['id'])
            else:
                return False
        elif kind == 'load_recovery':
            connected=N.link_capacity(self)>0
            island_source=any(u.get('forming_active') and u['status']=='ok' and
                (u.get('soc',0.)>.05 or (u.get('state')=='running' and u.get('fuel_mwh',0.)>0))
                for u in G.forming_units(self.grid))
            if self.physics_valid and 49.7<=self.frequency_hz<=50.3 and (connected or island_source):
                self.settings['frequency_shed']=max(0.,self.settings.get('frequency_shed',0.)-.1)
                self.log('protection',f"Staged load restoration: {self.settings['frequency_shed']:.0%} remains shed",None)
                if island_source:
                    D.start(self,t,'staged island load restoration')
                if self.settings['frequency_shed']:
                    self.events.push(t+1,'load_recovery','restore')
        elif kind == 'restore':
            self.restore(ev)
        elif kind == 'commission':
            p = self.projects.get(ev['project'])
            if p and p['status'] == 'building':
                if p['kind'] == 'expansion':
                    self.finish_expansion(p)
                else:
                    C.commission(self, ev['project'])
        elif kind == 'interconnector':
            self.interconnector_stage(ev['stage'])
        elif kind == 'maintenance_end':
            tb = self.grid['turbines'].get(ev['id'])
            if tb and tb['status'] == 'maintenance':
                tb['status'], tb['maintained'] = 'ok', t
                self.log('maintenance', f"{ev['id'].upper()} back in service after maintenance", None, turbine=ev['id'])

    def fault(self, ev):
        t = ev['time']
        target = ev['target']
        if target == 'branch':
            br = self.grid['branches'].get(ev['id'])
            if not br or not G.in_service(br) or br['repair_until'] is not None:
                return
            D.start(self,t,'branch fault '+br['id'])
            try:
                study=P.study(self,br,ev.get('resistance_ohm',.5))
            except Exception as exc:
                self.perf['failures']+=1
                self.log('numerical',f'Fault event not applied: short-circuit study failed ({exc})',None,branch=br['id'])
                D.finish(self,'numerical_failure')
                return
            permanent = not (br['kind'] == 'line' and br['type'].startswith('OHL')
                             and self.streams['faults'].random() < N.TRANSIENT_SHARE.get(br['type'], 0))
            permanent=ev.get('permanent',permanent)
            selected=study['selected']
            br['protection_study']=study
            br['active_fault']=dict(bus=study['fault_bus'],r=study['resistance_ohm'],since=t)
            self.events.push(t+P.PERSISTENT_FAULT_BACKUP_S/60,'fault_guard','protection',id=br['id'],
                             permanent=permanent,cause=ev['cause'])
            if selected is None:
                self.log('protection',f"Fault current {study['current_a']:.0f} A is below all enabled pickups; automatic overcurrent clearing unavailable",None,branch=br['id'])
                return
            br['relay_progress']={c['branch']:0. for c in study['relays']}
            br['relay_sample_time']=t
            self.events.push(t+D.STEP_S/60,'relay_check','protection',id=br['id'],permanent=permanent,cause=ev['cause'])
            self.log('fault',f"{ev['cause']}: {study['current_a']/1000:.2f} kA; {selected['role']} {selected['branch']} clearing in {selected['seconds']:.3f} s",None,branch=br['id'])
        elif target == 'turbine':
            tb = self.grid['turbines'].get(ev['id'])
            if not tb or tb['status'] != 'ok':
                return
            tb['status'] = 'fault'
            until = t+N.repair_minutes(self, ev['severity'])
            tb['fault_until'] = until
            self.events.push(until, 'restore', 'restore', turbine=ev['id'], reason='repair completed')
            what = 'gearbox or generator failure' if ev['severity'] == 'turbine_major' else 'converter or pitch fault'
            self.log('fault', f"{ev['id'].upper()} stopped: {what}; repair crew booked ({(until-t)/60:.0f} h)", None, turbine=ev['id'])
        elif target == 'pole':
            pole = next(p for p in self.grid['link']['poles'] if p['id'] == ev['id'])
            if pole['status'] != 'ok':
                return
            D.start(self,t,'HVDC pole loss '+pole['id'])
            pole['status'] = 'fault'
            pole['until'] = t+N.repair_minutes(self, 'pole')
            self.events.push(pole['until'], 'restore', 'restore', pole=pole['id'], reason='converter repaired')
            left = N.link_capacity(self)
            self.log('fault', f"{pole.get('name', pole['id'])} tripped; mainland capacity now {left:.0f} MW", None)
            if all(p['status'] != 'ok' for p in self.grid['link']['poles']) and not G.hvac_active(self.grid):
                self.link_lost(t)
        elif target == 'storage':
            s = self.grid['storage'].get(ev['id'])
            if s and s['status'] == 'ok':
                s['status'] = 'fault'
                until = t+N.repair_minutes(self, 'storage')
                self.events.push(until, 'restore', 'restore', storage=s['id'], reason='repair completed')
                self.log('fault', f"{s['name']} out of service (converter fault)", None, storage=s['id'])
                if s.get('forming_active'):
                    self.network.set_forming(s['id'], False)

    def fault_current(self, br):
        """Three-phase fault current at the branch's first bus from a separate study model (kA-level estimate)."""
        try:
            from .solvers import create_solver
            solver = create_solver(G.model(self.grid, self.devices), self.backend)
            for b in self.grid['branches'].values():
                if not G.in_service(b) and b['kind'] == 'line':
                    solver.set_enabled('line', b['id'], False)
            current, _ = solver.short_circuit(br['a'], .5)
            return current
        except Exception:
            return 0.

    def clear_fault(self,ev):
        t=ev['time']
        br=self.grid['branches'][ev['id']]
        if not br.get('active_fault'):
            return
        br.pop('active_fault',None)
        mechanism=ev.get('mechanism','overcurrent relay')
        self.trip_branch(ev['relay'],t,ev['cause']+' · '+mechanism,permanent=ev['permanent'])
        if ev['relay']!=br['id']:
            self.trip_branch(br['id'],t,'faulted segment isolated following backup trip',permanent=ev['permanent'])
            self.events.push(t+10,'restore','restore',id=ev['relay'],reason='backup reset after fault isolation')
        if not ev['permanent']:
            self.events.push(t+1/60,'restore','restore',id=br['id'],reason='auto-reclose')
        else:
            kind=br['type'] if br['kind']=='line' else 'transformer'
            br['repair_until']=t+N.repair_minutes(self,kind)
            self.events.push(br['repair_until'],'restore','restore',id=br['id'],reason='repair completed')
            plan=N.sectionalise(self,br)
            if plan and plan[0]<br['repair_until']-t:
                self.events.push(t+plan[0],'restore','restore',id=br['id'],reason='sectionalised')

    def fault_guard(self,ev):
        """Isolate a severe persistent fault when converter limiting prevents overcurrent pickup."""
        br=self.grid['branches'].get(ev['id'])
        if not br or not br.get('active_fault'):
            return False
        bus=br['active_fault']['bus']
        vm=(self.flows or {}).get('vm',{}).get(bus)
        if not self.physics_valid or vm is None or vm>P.PERSISTENT_FAULT_V_PU:
            return False
        br['relay_result']=dict(relay=br['id'],pickup_time=ev['time'],voltage_pu=vm,
                                mechanism='sustained-undervoltage fault backup')
        self.clear_fault(dict(ev,relay=br['id'],mechanism='sustained-undervoltage fault backup'))
        return False

    def relay_check(self,ev):
        br=self.grid['branches'][ev['id']]
        if not br.get('active_fault'):
            return False
        t=ev['time']
        dt=max(0.,(t-br['relay_sample_time'])*60)
        br['relay_sample_time']=t
        remaining=60.
        for candidate in br['protection_study']['relays']:
            bid=candidate['branch']
            current=(self.flows or {}).get('branches',{}).get(bid,(0.,0.,0.,0.,0.))[4]
            delay=P.inverse_time(current,candidate['pickup_a'],self.grid['branches'][bid].get('relay',{}).get('tms',.08))
            if delay is None:
                br['relay_progress'][bid]=max(0.,br['relay_progress'][bid]-dt/5.)
                continue
            operate=max(.001,delay-.06+candidate['depth']*.30)
            br['relay_progress'][bid]+=dt/operate
            if br['relay_progress'][bid]>=1.:
                br['relay_result']=dict(relay=bid,pickup_time=t,current_a=current,progress=br['relay_progress'][bid])
                self.events.push(t+.06/60,'relay_trip','protection',id=br['id'],relay=bid,
                                 permanent=ev['permanent'],cause=ev['cause'])
                return False
            remaining=min(remaining,operate*(1-br['relay_progress'][bid]))
        wait=D.STEP_S if D.active(self,t) else max(.02,min(60.,remaining))
        self.events.push(t+wait/60,'relay_check','protection',id=br['id'],permanent=ev['permanent'],cause=ev['cause'])
        return False

    def trip_branch(self, bid, t, cause, permanent):
        br = self.grid['branches'][bid]
        was = set(self.network.energized)
        br['tripped'] = True
        br['stress'] = 0.
        br['fault'] = cause
        self.network.switch(bid)
        lost = was-self.network.energized
        name = br.get('name', bid)
        affected = sorted({self.grid['buses'][b].get('zone') for b in lost if self.grid['buses'][b].get('zone')})
        text = f"{name} tripped: {cause}" + ('' if permanent else ', reclosing')
        if lost:
            names = ', '.join(self.zone_by_id[z]['name'] for z in affected) or f'{len(lost)} buses'
            text += f"; outage in {names}"
        self.log('protection', text, affected[0] if affected else None, branch=bid, zones=affected)
        ac = self.grid.get('hvac') or {}
        if (bid in ac.get('cables', ()) or bid == ac.get('transformer')) and not G.hvac_active(self.grid) \
                and all(p['status'] != 'ok' for p in self.grid['link']['poles']) and not self.grid['branches']['hvdc']['tripped']:
            self.link_lost(t)
        self.grid_lost_turbines(t)

    def grid_lost_turbines(self, t):
        for tb in self.grid['turbines'].values():
            if tb['status'] == 'ok' and tb['bus_lv'] not in self.network.energized:
                tb['grid_wait'] = LOST

    def restore(self, ev):
        t = ev['time']
        if 'id' in ev:
            br = self.grid['branches'].get(ev['id'])
            if not br:
                return
            name = br.get('name', br['id'])
            if ev['reason'] == 'repair completed':
                br['repair_until'] = None
                tie=self.grid['branches'].get(br.get('transfer_tie'))
                if tie and tie['closed']:
                    tie['closed']=False
                    self.network.switch(tie['id'])
                if br.get('section_out') is not None:
                    br['section_out'] = None
                    if not br['tripped']:
                        br['fault'] = None
                        self.log('restore', f"{name}: faulted section repaired; every customer is back", None, branch=br['id'])
                        return
            elif ev['reason'] == 'sectionalised':
                if not br['tripped'] or not br['closed'] or br['repair_until'] is None:
                    return
                ok,reason=P.transfer(self,br,t)
                zone = self.grid['buses'][br['b']].get('zone')
                self.log('restore',f"{name}: {'alternative feeder closed' if ok else 'transfer rejected'}; {reason}. Faulted branch remains isolated.",zone,branch=br['id'],tie=br.get('transfer_tie'))
                return
            if (br['repair_until'] is not None and br.get('section_out') is None) or not br['tripped']:
                return
            br['tripped'] = False
            br['fault'] = None
            self.network.switch(br['id'])
            self.log('restore', f"{br.get('name', br['id'])} back in service ({ev['reason']})", None, branch=br['id'])
        elif 'turbine' in ev:
            tb = self.grid['turbines'].get(ev['turbine'])
            if tb and tb['status'] == 'fault':
                tb['status'] = 'ok'
                tb['maintained'] = max(tb['maintained'], t-200*1440)
                self.log('restore', f"{ev['turbine'].upper()} repaired", None, turbine=ev['turbine'])
        elif 'pole' in ev:
            pole = next(p for p in self.grid['link']['poles'] if p['id'] == ev['pole'])
            pole['status'], pole['until'] = 'ok', None
            hv = self.grid['branches']['hvdc']
            if hv['tripped']:
                self.reconnect_link(t)
            self.log('restore', f"Link {pole['id']} back; capacity {N.link_capacity(self):.0f} MW", None)
        elif 'storage' in ev:
            s = self.grid['storage'].get(ev['storage'])
            if s and s['status'] == 'fault':
                s['status'] = 'ok'
                self.log('restore', f"{s['name']} back in service", None, storage=s['id'])
        # Turbines waiting for the grid restart a few minutes after their bus is live again.
        for tb in self.grid['turbines'].values():
            if tb['grid_wait'] == LOST and tb['bus_lv'] in self.network.energized:
                tb['grid_wait'] = t+8

    def link_lost(self, t):
        hv = self.grid['branches']['hvdc']
        hv['tripped'] = True
        hv['fault'] = 'both link poles out'
        self.network.switch('hvdc')
        N.sync_formers(self,t)
        if not any(s.get('forming_active') for s in G.forming_units(self.grid)):
            self.log('protection', 'Mainland link lost: no grid-forming source, island blackout', None)
        self.grid_lost_turbines(t)

    def reconnect_link(self, t):
        D.start(self,t,'mainland reconnection')
        hv = self.grid['branches']['hvdc']
        hv['tripped'], hv['fault'] = False, None
        for s in G.forming_units(self.grid):
            if s.get('forming_active'):
                self.network.set_forming(s['id'], False)
        self.network.switch('hvdc')
        self.log('restore', 'Mainland link restored; island resynchronised', None)
        for tb in self.grid['turbines'].values():
            if tb['grid_wait'] == LOST and tb['bus_lv'] in self.network.energized:
                tb['grid_wait'] = t+8

    def interconnector_stage(self, i):
        """Legacy handler retained for old event payloads; loading cancels every such event."""
        ac = self.grid['hvac']
        stage = ac['stages'][i]
        for c in ac['cables'][:stage['cables']]:
            self.grid['branches'][c]['planned'] = False
        for b in [ac['transformer']]+ac['links']:
            self.grid['branches'][b]['planned'] = False
        first = ac['capacity'] == 0
        ac['capacity'] = stage['mw']
        self.grid['version'] = self.grid.get('version', 0)+1
        self.network.dirty = True
        p = self.projects.get('tso_hvac')
        if p and p['status'] == 'building':
            p['status'] = 'done'
        if first:
            self.log('construction', f"HVAC 220 kV link in service ({stage['cables']} cable, {stage['mw']:.0f} MW): the island is now synchronous "
                     f"with the mainland and the HVDC runs as a scheduled link", None)
        else:
            self.log('construction', f"HVAC link capacity raised to {stage['mw']:.0f} MW ({stage['cables']} cables)", None)

    def finish_expansion(self, p):
        p['status'] = 'done'
        due = p['cost']-p['paid']
        if due > 0:
            self.pay_construction(p['owner'], due, self.minute, 'firm investment')
            p['paid'] = p['cost']
        f = self.firms[p['firm']]
        if f['status'] == 'construction':
            f['status'] = 'operating'
            self.network.dirty = True
            self.log('economy', f"{f['name']} opens and connects to the grid", f['zone'], firm=f['id'])
            return
        f['capacity_factor'] *= 1.15
        f['desired_staff'] = round(f['desired_staff']*1.12)
        if f['kind'] == 'hospitality':
            f['beds'] = round(f['beds']*1.15)
            for did in f['devices']:
                self.devices[did]['beds'] = f['beds']
        for did in f['equipment']:
            self.devices[did]['p_rated'] *= 1.15
        self.log('economy', f"{f['name']} expansion completed", f['zone'], firm=f['id'])

    # ------------------------------------------------------------ periodic work
    def plan_hour(self, m, prime=False):
        if prime:
            # Opening state: loads start at their planned level instead of ramping up from zero.
            self._prime_scales(m)
            return
        S.refresh_stats(self)
        for z in self.zones:
            d = self.devices['res_'+z['id']]
            d['heated'] = S.heated_households(self, z)
            L.retarget(d, m, S.household_scale(self, z))
        for f in self.firms.values():
            if f['status'] != 'operating':
                continue
            for did in f['devices']:
                d = self.devices[did]
                if d['kind'] == 'services':
                    L.retarget(d, m, f['staff'])
                elif d['kind'] == 'public':
                    L.retarget(d, m, f['staff'])
                elif d['kind'] == 'lodging':
                    L.retarget(d, m, self.pops.get(f['zone']+'_tourist', {}).get('count', 0))
                elif d['kind'] == 'farm':
                    L.retarget(d, m, f['herd']*f['capacity_factor'])
        E.plan_hour(self, m)
        self.messages['ActivityPlan']=message(self,'ActivityPlan',m,m+60,
            dict(firms={fid:dict(status=f['status'],staff=f['staff'],equipment=f['equipment']) for fid,f in self.firms.items()},
                 equipment_events=[e for e in self.events.pending() if e['kind']=='equipment' and m<=e['time']<m+60]))
        projection=[]
        for dt in (0,30,60):
            predicted=self.forecast(m,m+dt)
            ctx=dict(rest=is_rest_day(m+dt))
            power=sum(L.request(d,m+dt,predicted,ctx) for d in self.devices.values()
                      if d['owner'][0]!='firm' or self.firms[d['owner'][1]]['status']=='operating')
            projection.append(dict(t=m+dt,p_mw=power))
        self.messages['DemandTrajectory']=message(self,'DemandTrajectory',m,m+60,
            dict(method='conditional device/activity projection',samples=projection))
        N.sample_faults(self, m)

    def _prime_scales(self, m):
        S.refresh_stats(self)
        S.tourism_day(self, m)
        S.refresh_stats(self)
        self.outage_today = {}
        self.plan_hour(m)
        for d in self.devices.values():
            if 's1' in d:
                d['s0'] = d['s1']

    def settle_hour(self, start, end):
        if end<=self.settled_until:
            return
        if start!=self.settled_until:
            raise ValueError('Hourly settlements must be contiguous and cannot overlap.')
        before=dict(self.ledger.totals)
        E.settle_hour(self, start, end)
        H.capture_hour(self,start)
        acc = self.acc
        led = self.ledger
        # Electricity bills for what was actually delivered (spec 5.5), and the link's energy at the mainland price.
        zone_persons = {}
        for p in self.pops.values():
            if p['kind'] in ('resident', 'holiday', 'seasonal'):
                zone_persons.setdefault(p['zone'], []).append(p)
        sales = 0.
        for d in self.devices.values():
            e = d['e_srv']
            if e > 0:
                billed = 0.
                if d['owner'][0] == 'zone':
                    price = self.tariff('household', start)*1000
                    people = zone_persons.get(d['owner'][1], [])
                    total = sum(p['count'] for p in people) or 1
                    for p in people:
                        if p['count']:
                            price = self.tariff('household', start, 'pop:'+p['id'])*1000
                            led.transfer('pop:'+p['id'], 'pb', e*price*p['count']/total, 'electricity', start)
                            billed += e*price*p['count']/total
                else:
                    f = self.firms[d['owner'][1]]
                    cls = 'industry' if f['kind'] in ('cement', 'quarry', 'dairy', 'feedmill', 'slaughter', 'brewery') else 'business'
                    price = self.tariff(cls, start, 'firm:'+f['id'])*1000
                    payer = 'region' if f['kind'] in ('public', 'hospital') else 'firm:'+f['id']
                    led.transfer(payer, 'pb', e*price, 'electricity', start)
                    f['today']['power_cost'] += e*price
                    billed = e*price
                sales += billed
            self.entity_point(d['id'], round(d['e_srv'], 4), round(d['e_req']-d['e_srv'], 4))
            d['e_req'] = d['e_srv'] = 0.
        led.transfer('pb', 'external', acc['import_cost'], 'power import', start)
        led.transfer('external', 'pb', acc['export_revenue'], 'power export', start)
        for z in self.zones:
            d = self.devices['res_'+z['id']]
            hours = d.pop('outage_min', 0.)/60
            self.outage.setdefault(z['id'], deque(maxlen=120))
            self.outage_today[z['id']] = self.outage_today.get(z['id'], 0.)+hours
        price = self.energy_price(start)
        self.price_observations['sum'] += price
        self.price_observations['hours'] += 1
        st = self.society_stats
        tb = self.grid['turbines']
        for tid, t in tb.items():
            self.entity_point(tid, round(t['energy_mwh'], 3))
            t['energy_mwh'] = 0.
        for bid, x in (self.flows or {}).get('loading', {}).items():
            self.entity_point(bid, round(x, 3))
        unserved = sum(acc['unserved_zone'].values())
        self.history_hour.append(dict(
            t=start, load=round(acc['load_req'], 3), served=round(acc['load_srv'], 3), unserved=round(unserved, 3),
            wind=round(acc['wind'], 3), wind_avail=round(acc['wind_avail'], 3),
            link_import=round(acc['link_import'], 3), link_export=round(acc['link_export'], 3),
            battery=round(acc['battery_dis']-acc['battery_ch'], 3), losses=round(acc['losses'], 3),
            oil=round(acc.get('oil',0.),3),
            price=round(price, 4), temp=round(self.weather_now['temperature_c'], 2), wind10=round(self.weather_now['wind_10m_ms'], 2),
            tourists=sum(st['zone_tourists'].values()), holiday=sum(st['zone_holiday'].values()),
            residents=sum(st['zone_residents'].values()), unemployed=sum(st['zone_unemployed'].values()),
            pb_cash=round(led.balance('pb')), vmin=round(acc['vmin'], 4), peak=round(acc['maxload'], 3),
            sales=round(sales)))
        self.messages['EconomicSettlement']=message(self,'EconomicSettlement',start,end,
            dict(served_mwh=acc['load_srv'],requested_mwh=acc['load_req'],
                 quality='estimated_during_numerical_failure' if any(a<end and b>start for a,b in self.archive.invalid_intervals) else 'validated',
                 payments_sek={k:v-before.get(k,0.) for k,v in led.totals.items() if v!=before.get(k,0.)}))
        self.settled_until=end
        self.acc = self._blank_acc()

    def entity_point(self, key, *values):
        d = self.entity_hist.get(key)
        if d is None:
            d = self.entity_hist[key] = deque(maxlen=168)
        d.append(values[0] if len(values) == 1 else values)

    def start_day(self, m):
        if m > 0:
            S.tourism_day(self, m)
        self.outage_today = {}

    def settle_day(self, m):
        """Close the day that just ended: purchases, wages, exports, O&M, statistics."""
        day_start = m-DAY
        led = self.ledger
        S.record_income(self)
        E.pay_wages(self, m)
        self.ferry_orders = []
        S.daily(self, m)
        for zid, orders in self.consumer_orders.items():
            f = self.firms.get('s_'+zid)
            if f and f['status'] == 'operating':
                E.sell_local(self, f, orders, m)
        for zid, orders in self.lodging_orders.items():
            f = self.firms.get('h_'+zid)
            if f and f['status'] == 'operating':
                E.sell_local(self, f, orders, m)
        if self.ferry_orders and 'f_port' in self.firms:
            E.sell_local(self, self.firms['f_port'], self.ferry_orders, m)
        cf = self.firms.get('f_construction')
        if cf and cf['status'] == 'operating':
            E.sell_local(self, cf, self.construction_orders, m)
        E.sell_island(self, 'food', self.food_orders, m)
        E.restock_inputs(self, m)
        E.export_surplus(self, m)
        # Visitors' unspent money goes home with them.
        for p in self.pops.values():
            if p['kind'] in ('tourist', 'holiday'):
                bal = led.balance('pop:'+p['id'])
                if bal:
                    led.transfer('pop:'+p['id'], 'external', bal, 'visitor spending returned', m)
        # Powerbolaget operation and maintenance, paid daily.
        wind_mw = sum(t['mw'] for t in self.grid['turbines'].values() if t['status'] not in ('construction','retired'))
        grid_km = sum(b['km'] for b in self.grid['branches'].values() if b['kind'] == 'line' and b['id'] != 'hvdc' and not b.get('retired'))
        storage_mw = sum(s['p_mw'] for s in self.grid['storage'].values() if s['status']!='retired')
        om = (wind_mw*WIND_OM_SEK_MW_YEAR+grid_km*GRID_OM_SEK_KM_YEAR+storage_mw*STORAGE_OM_SEK_MW_YEAR)/365
        self.pay_construction('pb', om, m, 'operation and maintenance')
        # The region balances its budget with a state grant; Powerbolaget borrows if cash runs out.
        if led.balance('region') < 50e6:
            led.transfer('external', 'region', 60e6-led.balance('region'), 'state grant', m)
        if led.balance('pb') < 0:
            led.transfer('financing', 'pb', -led.balance('pb')+20e6, 'external financing', m)
            self.log('finance', 'Cash shortfall covered by external financing (free-investment rule)', None)
        F.close_day(self, m)
        O.refuel(self,m)
        U.close_day(self)
        material_report=M.report(self)
        self.conservation_history.append(dict(t=m,goods=material_report,money=sum(led.accounts.values()),
            water={z:U.residual(w) for z,w in self.water.items()}))
        self.conservation_history=self.conservation_history[-120:]
        E.close_day(self, m)
        for z in self.zones:
            self.outage.setdefault(z['id'], deque(maxlen=120)).append(round(self.outage_today.get(z['id'], 0.), 3))
        day = led.close_day()
        h = list(self.history_hour)[-24:]
        st = self.society_stats
        self.history_day.append(dict(
            t=day_start, load_mwh=round(sum(x['load'] for x in h), 2), served_mwh=round(sum(x['served'] for x in h), 2),
            unserved_mwh=round(sum(x['unserved'] for x in h), 3), wind_mwh=round(sum(x['wind'] for x in h), 2),
            import_mwh=round(sum(x['link_import'] for x in h), 2), export_mwh=round(sum(x['link_export'] for x in h), 2),
            peak_mw=round(max([x['peak'] for x in h] or [0]), 2), price=round(sum(x['price'] for x in h)/max(1, len(h)), 4),
            residents=sum(st['zone_residents'].values()), tourists=sum(st['zone_tourists'].values()),
            unemployed=sum(st['zone_unemployed'].values()), pb_cash=round(led.balance('pb')),
            money={k: round(v) for k, v in day.items() if abs(v) >= 1}))

    def settle_month(self, m):
        R.close_month(self)
        C.pay_progress(self, m)
        for p in self.projects.values():
            if p['status'] == 'building' and p['kind'] == 'expansion':
                done = min(1., (m-p['start'])/max(1, p['finish']-p['start']))
                due = p['cost']*done-p['paid']
                if due > 0:
                    self.pay_construction(p['owner'], due, m, 'firm investment')
                    p['paid'] += due
        E.labour_month(self, m)
        S.monthly(self, m)
        E.invest_month(self, m)
        demo = self.demography['month']
        demo['end'] = S.residents(self)
        demo['month'] = month_index(m)-1
        self.demography['months'].append(demo)
        self.demography['months'] = self.demography['months'][-120:]
        self.demography['month'] = self._blank_demo()
        self.demography['month']['start'] = demo['end']
        for f in self.firms.values():
            f['last_month'], f['month'] = f['month'], {}
        prospects(self, m)


def prospects(world, m):
    """New firms consider coming to the island (autonomous development; spec 1.2)."""
    rng = world.streams['economy']
    has_dc = any(f['kind'] == 'datacenter' for f in world.firms.values())
    price_ok = world.price_avg < .75
    reliability = 1-min(1., sum(world.zone_outage_hours(z, 90) for z in ('z11', 'z01'))/40)
    if not has_dc and price_ok and reliability > .6 and rng.random() < .18:
        zone = 'z11' if rng.random() < .6 else 'z03'
        bus = 'ind_kal' if zone == 'z11' else 'z03'
        fid = 'f_datacenter'
        f = E.firm(fid, 'Nordljus datacenter', 'datacenter', 'industry', zone, bus, '', 'none', status='construction',
                   desired_staff=40)
        world.firms[fid] = f
        world.jobs[fid] = {}
        world.ledger.transfer('external', 'firm:'+fid, 480e6, 'investor equity', m)
        did = f'{fid}_servers'
        world.devices[did] = L.equipment(did, ('firm', fid), bus, 'Server halls', 8.0, .97, 'flexible', 10, 20, role='compute')
        f['equipment'].append(did)
        world.network.dirty = True
        world.start_firm_expansion(f, 420e6)
        world.projects[f"x{world.counters['expansion']}"]['title'] = 'Nordljus datacenter: new 8 MW facility'
        world.log('economy', 'An investor decides to build an 8 MW data centre; grid connection requested', zone, firm=fid)


# ---------------------------------------------------------------- player commands
class CommandError(ValueError):
    pass


def command(world, cmd):
    """Apply one player command at the current minute. Returns a short confirmation.
    The player directs Powerbolaget's own assets only; firms and residents decide for themselves."""
    request_id = cmd.get('request_id')
    fingerprint = hashlib.sha256(json.dumps({k: v for k, v in cmd.items() if k != 'request_id'},
                                            sort_keys=True, allow_nan=False).encode()).hexdigest()
    if request_id in world.command_receipts:
        receipt = world.command_receipts[request_id]
        if receipt['fingerprint'] != fingerprint:
            raise CommandError('This request ID was already used for a different command.')
        return receipt['result']
    kind = cmd['kind']
    t = float(world.minute)
    if kind == 'build':
        b = dict(cmd['build'])
        try:
            plan = plan_build(world, b)
        except C.BuildError as exc:
            raise CommandError(str(exc))
        project = C.start(world, plan)
        result = f"Construction started: {plan['title']}"
    elif kind == 'maintenance':
        tb = world.grid['turbines'].get(cmd['target'])
        if not tb:
            raise CommandError('Unknown turbine.')
        if tb['status'] == 'maintenance':
            world.events.cancel(lambda e: e['kind'] == 'maintenance_end' and e.get('id') == tb['id'])
            tb['status'], tb['maintained'] = 'ok', t
            result = f"{tb['id'].upper()} maintenance finished early"
        elif tb['status'] == 'ok':
            tb['status'] = 'maintenance'
            world.events.push(t+2*DAY, 'maintenance_end', 'restore', id=tb['id'])
            result = f"{tb['id'].upper()} stopped for two days of planned maintenance"
        else:
            raise CommandError(f"{tb['id'].upper()} is {tb['status']} and cannot start maintenance now.")
        world.log('maintenance', result, None, turbine=tb['id'])
    elif kind == 'switch':
        br = world.grid['branches'].get(cmd['target'])
        if not br or br['id'] == 'hvdc':
            raise CommandError('Unknown or non-switchable branch.')
        if br.get('retired') or any(p['status']=='building' and p.get('target')==br['id'] for p in world.projects.values()):
            raise CommandError('This branch is retired or locked out for work.')
        br['closed'] = bool(cmd['closed'])
        world.network.switch(br['id'])
        world.grid_lost_turbines(t)
        if br['closed']:
            for tb in world.grid['turbines'].values():
                if tb['grid_wait'] == LOST and tb['bus_lv'] in world.network.energized:
                    tb['grid_wait'] = t+8
        result = f"{br.get('name', br['id'])} {'closed' if br['closed'] else 'opened'} by the operator"
        world.log('operation', result, None, branch=br['id'])
    elif kind == 'storage_mode':
        s = world.grid['storage'].get(cmd['target'])
        if not s:
            raise CommandError('Unknown battery.')
        if cmd['mode'] not in ('auto', 'hold', 'charge', 'discharge'):
            raise CommandError('Mode must be auto, hold, charge or discharge.')
        s['mode'] = cmd['mode']
        s['setpoint'] = max(0., min(s['p_mw'], float(cmd.get('setpoint') or s['p_mw'])))
        result = f"{s['name']}: {s['mode']}"
        world.log('operation', result, None, storage=s['id'])
    elif kind == 'settings':
        margin = float(cmd['link_margin'])
        if not 0 <= margin <= .3:
            raise CommandError('Link margin must be 0-30 %.')
        world.settings['link_margin'] = margin
        result = f'Link operating margin set to {margin*100:.0f} %'
        world.log('operation', result, None)
    elif kind == 'retail_policy':
        try:
            R.change_policy(world, cmd['category'], cmd['policy'])
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError(str(exc))
        result = f"New {cmd['category']} contract offers updated; signed contracts keep their terms"
        world.log('finance', result, None)
    elif kind == 'asset_work':
        from . import engineering as X
        try:
            plan = X.plan_asset(world, cmd['target'], cmd['action'])
            C.start(world, plan)
        except C.BuildError as exc:
            raise CommandError(str(exc))
        result = plan['title']+' started'
    elif kind == 'generator_mode':
        g=world.grid.get('oil',{}).get(cmd['target'])
        if not g or cmd.get('mode') not in ('auto','off','on'):
            raise CommandError('Choose an oil generator and auto/off/on mode.')
        g['mode']=cmd['mode']
        g['setpoint']=min(g['p_mw'],max(.2*g['p_mw'],float(cmd.get('setpoint') or g['p_mw'])))
        result=g['name']+': '+g['mode']
    elif kind == 'record':
        try:
            world.archive.record(world,cmd['target'],bool(cmd.get('recording',True)))
        except ValueError as exc:
            raise CommandError(str(exc))
        result='Minute recording '+('enabled' if cmd.get('recording',True) else 'stopped')
    elif kind == 'reactive_control':
        asset=world.grid['turbines'].get(cmd['target']) or world.grid['storage'].get(cmd['target']) or world.grid.get('oil',{}).get(cmd['target'])
        if not asset or cmd.get('q_mode') not in ('voltage','fixed'):
            raise CommandError('Choose a generator/battery and fixed-Q or voltage control.')
        asset.update(q_mode=cmd['q_mode'],q_setpoint=float(cmd.get('q_setpoint') or 0.),v_setpoint=float(cmd.get('v_setpoint') or 1.02))
        result='Reactive control updated; capability and current limits apply'
    elif kind == 'cancel_project':
        from . import engineering as X
        try:
            p = X.cancel_project(world, cmd['target'])
        except C.BuildError as exc:
            raise CommandError(str(exc))
        result = 'Cancelled: '+p['title']+'; payments already made remain project costs'
        world.log('construction', result, p['zone'], project=p['id'])
    else:
        raise CommandError('Unknown command.')
    world.commands.append(dict(minute=world.minute, **cmd))
    world.commands = world.commands[-2000:]
    if request_id:
        world.command_receipts[request_id] = dict(fingerprint=fingerprint, result=result, minute=world.minute)
    return result


def plan_build(world, b):
    from . import engineering as X
    typ = b.pop('type')
    required = dict(turbine=('model','x','y'), storage=('p_mw','hours'), line=('a','b'),
                    transformer=('station',), station=('x','y'), interconnector=('technology','p_mw','station'),oil=('p_mw',))
    if any(b.get(k) is None for k in required.get(typ, ())):
        raise C.BuildError('Complete the required fields for this project.')
    if typ == 'turbine':
        return C.plan_turbine(world, b['model'], float(b['x']), float(b['y']), b.get('connect_bus'), b.get('route'))
    if typ == 'storage':
        return C.plan_storage(world, b.get('station'), float(b['p_mw']), float(b['hours']), bool(b.get('grid_forming')), b.get('connect_bus'))
    if typ == 'line':
        return X.plan_line(world, b['a'], b['b'], b.get('line_type', 'OHL110'), b.get('route'))
    if typ == 'transformer':
        return X.plan_transformer(world, b['station'], b.get('mva', 40.))
    if typ == 'station':
        return X.plan_station(world, b['x'], b['y'], b.get('mv_kv', 20.), b.get('mva', 40.), b.get('name'))
    if typ == 'interconnector':
        return X.plan_link(world, b['technology'], b['p_mw'], b['station'], b.get('route'))
    if typ == 'oil':
        return O.plan(world,b.get('station'),b['p_mw'],b.get('fuel_hours',48.),b.get('connect_bus'))
    raise C.BuildError('Unknown project type.')
