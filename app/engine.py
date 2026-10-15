"""Chronological wind-first dispatch with AC constraints and explicit energy accounting."""
from copy import deepcopy
from math import sin, cos, pi
from datetime import datetime, timedelta
from .parameters import DT_H, DISTRICTS, PROJECTS, TURBINES, WEATHER, VERSION
from .wind import weather, farm
from .network import Network
from .protection import inject, repair, event
from .errors import RuleError
from .planning import fleet, default_plan, normalize, audit, commission
from .construction import schedule


def deenergized_power():
    return dict(voltages={a['id']:0. for a in DISTRICTS},lines={},
                transformer_pct={'grid':0.,'city':0.},losses_mw=0.,grid_mw=0.,
                battery_mvar=0.,balance_error_mw=0.,min_voltage=0.,max_voltage=0.,
                max_loading_pct=0.,energized=False)


def storage_rating(g):
    factor=2 if 'battery_phase2' in g['upgrades'] else 1
    return (6.*factor+sum(p['plan']['storage_power_mw'] for p in g.get('plants',[])),
            24.*factor+sum(p['plan']['storage_capacity_mwh'] for p in g.get('plants',[])))


def demands(g):
    h=(g['step']%96)/4
    from .climate import conditions
    met=conditions(g['seed'],g['step'])
    season=1+min(.15,.006*max(0,12-met['temperature_c']))
    return {a['id']:a['peak_mw']*season*(
        .5+.18*max(0,cos((h-7)*pi/6))+.32*max(0,cos((h-19)*pi/7)) if a['id']=='homes' else
        .48+.5*max(0,sin((h-6)*pi/16)) if a['id']=='center' else
        .8+.16*(7<=h<=22) if a['id']=='harbor' else .90+.08*(7<=h<=21)
    ) for a in DISTRICTS}


def battery_dispatch(g,wind,load,loss):
    if not g['breakers']['bess'] or not g['breakers']['pcc']: return 0.
    p,e=storage_rating(g); energy=g['battery']['energy_mwh']
    # 96% charge and discharge efficiency => 92.16% AC round trip, assumed.
    charge=min(p,max(0,(.90*e-energy)/(DT_H*.96)))
    regular=min(p,max(0,(energy-g['settings']['reserve_soc']*e)*.96/DT_H))
    emergency=min(p,max(0,(energy-.15*e)*.96/DT_H))
    deficit=load+.05+loss-wind
    if deficit<0: return -min(-deficit,charge)
    if g['settings']['dispatch']=='reserve':
        return min(emergency,max(0,deficit-g['settings']['import_limit_mw']))
    desired=min(deficit,regular)
    return min(emergency,max(desired,deficit-g['settings']['import_limit_mw']))


def shed(loads,original,amount):
    """Noncritical fractions first; critical loads only after noncritical exhausted."""
    for critical in (False,True):
        available={a['id']:max(0,loads[a['id']]-(0 if critical else original[a['id']]*a['critical'])) for a in DISTRICTS}
        total=sum(available.values())
        removed=min(amount,total)
        if total:
            for k,v in available.items(): loads[k]-=removed*v/total
        amount-=removed
        if amount<1e-8: break


def evaluate(g,net=None,commit=False):
    met=weather(g,evolve=commit)
    units=farm(g,met,evolve=commit)
    demand=demands(g)
    available=[t['available_mw'] for t in units]
    original_available=sum(available)
    loads={k:v if g['breakers']['pcc'] and g['breakers']['transformer'] and g['breakers'][k] else 0. for k,v in demand.items()}
    pcap,ecap=storage_rating(g)
    if not g['breakers']['pcc']:
        wind=[0.]*len(units); battery=0.
        power=deenergized_power()
        reasons=['Grid outage: anti-islanding trip. Grid-following storage cannot form an island.']
    else:
        net=net or Network('collector_upgrade' in g['upgrades'],g)
        net.configure(g)
        wind=available[:]; loss=.12; reasons=[]
        # Bound the first nonlinear solve for large newly commissioned projects.
        safe_export=sum(loads.values())+g['settings']['export_limit_mw']+pcap+2
        if sum(wind)>safe_export:
            wind=[v*safe_export/sum(available) for v in available]
            reasons.append('Available wind exceeds absorption capacity: initial curtailment')
        for iteration in range(50):
            battery=battery_dispatch(g,sum(wind),sum(loads.values()),loss)
            power=net.solve(wind,loads,battery,pcap*1.1 if g['breakers']['bess'] else 0.,g['settings']['volt_var'])
            power['energized']=True
            loss=power['losses_mw']
            changed=False
            # Constrain actual AC source interchange, including transformer/cable losses.
            excess=-power['grid_mw']-g['settings']['export_limit_mw']
            if excess>.002 and sum(wind)>0:
                factor=max(0,1-(excess+.002)/sum(wind)); wind=[v*factor for v in wind]
                reasons.append('Grid export limit: curtailing wind power'); changed=True
            short=power['grid_mw']-g['settings']['import_limit_mw']
            if short>.002:
                if sum(loads.values())<.001 and battery_dispatch(g,sum(wind),0.,loss)-battery<.002:
                    # A zero-import policy can make even auxiliary/no-load supply infeasible.
                    # Disconnect the whole station instead of inventing unmetered grid energy.
                    loads={k:0. for k in loads}; wind=[0.]*len(units); battery=0.
                    power=deenergized_power()
                    reasons.append('Supply cannot cover auxiliaries and no-load losses; station shut down, reevaluated next interval')
                    break
                # First let dispatch recompute with measured losses, then shed if power/SOC constrained.
                new_battery=battery_dispatch(g,sum(wind),sum(loads.values()),loss)
                residual=short-max(0,new_battery-battery)
                if residual>.002:
                    shed(loads,demand,residual+.003); reasons.append('Grid / storage power limited: noncritical load shed first')
                changed=True
            for start in (0,4):
                worst=max(power['lines'][TURBINES[i]['id'].lower()]['loading_pct'] for i in range(start,start+4))
                if worst>100.01:
                    factor=min(.95,98/worst)
                    for i in range(start,start+4): wind[i]*=factor
                    reasons.append('Collector thermal limit: curtailing wind'); changed=True
            for plant in g.get('plants',[]):
                prefix=plant['id'].lower()
                ratings=[power['lines'][prefix+'_'+e['id'].lower()]['loading_pct'] for e in plant['plan']['edges']]
                ratings.extend(v for k,v in power['transformer_pct'].items() if k.startswith(prefix+'_'))
                worst=max(ratings,default=0)
                if worst>100.01:
                    for i,t in enumerate(units):
                        if t['farm_id']==plant['id']:wind[i]*=min(.93,97/worst)
                    reasons.append(plant['name']+': Collector / unit / site transformer limit: curtailing power');changed=True
            if power['transformer_pct']['grid']>100.01:
                if power['grid_mw']<0:wind=[v*.9 for v in wind]
                else:shed(loads,demand,sum(loads.values())*.1)
                reasons.append('Grid transformer capacity limit');changed=True
            for a in DISTRICTS:
                name=a['id']; loading=power['lines'][name]['loading_pct']
                if loading>100.01:
                    loads[name]*=98/loading; reasons.append(a['name']+' feeder thermal limit'); changed=True
            if power['transformer_pct']['city']>100.01:
                shed(loads,demand,sum(loads.values())*(1-98/power['transformer_pct']['city']))
                reasons.append('City transformer thermal limit'); changed=True
            if power['max_voltage']>1.06 and sum(wind)>0:
                wind=[v*.9 for v in wind]; reasons.append('High voltage: active curtailment after reactive control'); changed=True
            if power['min_voltage']<.94 and sum(loads.values())>0:
                shed(loads,demand,sum(loads.values())*.06); reasons.append('Low voltage: staged load shedding'); changed=True
            # Refine loss estimate even when no constraint is binding.
            desired=battery_dispatch(g,sum(wind),sum(loads.values()),loss)
            if not changed and abs(desired-battery)<.002: break
        else:
            raise RuntimeError('Dispatch iteration did not satisfy constraints. Save the scenario for diagnosis; action was not committed.')
        if abs(power['balance_error_mw'])>.005:
            raise RuntimeError('Power balance residual exceeds 5 kW.')
    energy_before=g['battery']['energy_mwh']
    delta=(-battery/.96 if battery>0 else -battery*.96)*DT_H
    if commit:
        g['battery']['energy_mwh']+=delta
        g['battery']['throughput_mwh']+=abs(battery)*DT_H
        if not .15*ecap-1e-6<=g['battery']['energy_mwh']<=.90*ecap+1e-6:
            raise RuntimeError('Battery SOC is outside physical limits.')
    rows=[]
    for i,t in enumerate(units): rows.append(dict(**t,output_mw=wind[i],curtailment_mw=max(0,t['available_mw']-wind[i])))
    served=sum(loads.values()); requested=sum(demand.values())
    critical_requested=sum(demand[a['id']]*a['critical'] for a in DISTRICTS)
    critical_served=sum(min(loads[a['id']],demand[a['id']]*a['critical']) for a in DISTRICTS)
    local_direct=min(sum(wind),served)
    metrics=dict(step=g['step'],wind_mw=sum(wind),available_wind_mw=original_available,
                 demand_mw=requested,served_mw=served,unserved_mw=max(0,requested-served),
                 critical_served_mw=critical_served,critical_demand_mw=critical_requested,
                 battery_mw=battery,soc=g['battery']['energy_mwh']/ecap,
                 grid_mw=power['grid_mw'],losses_mw=power['losses_mw'],
                 curtailment_mw=max(0,original_available-sum(wind)),
                 wind_direct_mw=local_direct,wind_direct_pct=100*local_direct/max(.001,served),
                 supply_pct=100*served/max(.001,requested),min_voltage=power['min_voltage'],
                 max_loading_pct=power['max_loading_pct'],wind_ms=met['speed_ms'],
                 balance_error_mw=power['balance_error_mw'],battery_delta_mwh=delta,
                 auxiliary_mw=.05 if power['energized'] else 0.,
                 battery_conversion_loss_mwh=abs(delta+battery*DT_H))
    if commit:
        for key, value in dict(wind_mwh=sum(wind),demand_mwh=requested,served_mwh=served,
                               import_mwh=max(0,power['grid_mw']),export_mwh=max(0,-power['grid_mw']),
                               loss_mwh=power['losses_mw'],curtailment_mwh=metrics['curtailment_mw'],
                               unserved_mwh=metrics['unserved_mw'],wind_direct_mwh=local_direct).items():
            g['totals'][key]+=value*DT_H
        g['totals']['auxiliary_mwh']+=metrics['auxiliary_mw']*DT_H
        g['totals']['battery_loss_mwh']+=metrics['battery_conversion_loss_mwh']
        g['totals']['battery_charge_mwh']+=max(0,-battery)*DT_H
        g['totals']['battery_discharge_mwh']+=max(0,battery)*DT_H
        # Economics are declared scenario assumptions; settlement does not buy unlimited backup.
        operating=served*.62-max(0,power['grid_mw'])*.65+max(0,-power['grid_mw'])*.28-sum(wind)*.07-metrics['unserved_mw']*8
        g['cash']+=operating*1000*DT_H-3000*DT_H/24
        g['history'].append(metrics)
        if len(g['history'])>672: g['history']=g['history'][-672:]
    g['metrics']=metrics
    g['snapshot']=dict(weather=met,turbines=rows,network=power,districts=[dict(**a,demand_mw=demand[a['id']],served_mw=loads[a['id']],voltage=power['voltages'].get(a['id'],0)) for a in DISTRICTS],
                       constraints=list(dict.fromkeys(reasons)),storage=dict(power_mw=pcap,capacity_mwh=ecap,energy_mwh=g['battery']['energy_mwh'],
                       soc_min=.15,soc_max=.9,efficiency_charge=.96,efficiency_discharge=.96,initial_energy_origin='Initial commissioned energy; excluded from wind generation'))


def create(seed=42):
    g=dict(schema=2,version=VERSION,revision=0,seed=seed,step=0,weather='normal',wind_noise=0.,
           cash=220_000_000.,upgrades=[],projects=[],plants=[],draft=default_plan(),faults={},events=[],history=[],protection_records=[],
           battery=dict(energy_mwh=14.4,throughput_mwh=0.),
           turbines=[dict(maintenance=False,storm_lock=False,restart_count=0) for _ in TURBINES],
           breakers={key:True for key in ['pcc','farm','collector_a','collector_b','transformer','bess']+[a['id'] for a in DISTRICTS]},
           settings=dict(reserve_soc=.30,dispatch='self_use',import_limit_mw=12.,export_limit_mw=5.,
                         volt_var=True,pickup_multiplier=1.2,tms=.12),
           totals={key:0. for key in ['wind_mwh','demand_mwh','served_mwh','import_mwh','export_mwh','loss_mwh','curtailment_mwh','unserved_mwh','wind_direct_mwh','auxiliary_mwh','battery_loss_mwh','battery_charge_mwh','battery_discharge_mwh']})
    evaluate(g)
    event(g,'The initial 20 MW wind farm and 6 MW / 24 MWh battery are online. Wind serves the city first; the external grid provides backup.')
    return g


def apply(game,command):
    g=deepcopy(game); kind=command['kind'];g.setdefault('plants',[])
    if kind=='new': g=create(command.get('seed',42))
    elif kind=='advance':
        steps=command.get('steps',1)
        if not 1<=steps<=672: raise RuleError('Advance 1–672 fifteen-minute intervals per action.')
        if g['step']+steps>35040: raise RuleError('The one-year scenario has ended. Export results and create a new scenario.')
        net=Network('collector_upgrade' in g['upgrades'],g)
        for _ in range(steps):
            g['step']+=1
            for p in list(g['projects']):
                if g['step']>=p['finish']:
                    g['upgrades'].append(p['id']); g['projects'].remove(p)
                    if 'plan' in p:commission(g,p)
                    if p['id']=='battery_phase2':
                        # New cells arrive at minimum permitted SOC; energy is purchased/accounted.
                        commissioned_energy=24*.15
                        g['battery']['energy_mwh']+=commissioned_energy
                        g['totals']['import_mwh']+=commissioned_energy/.96
                        g['totals']['battery_loss_mwh']+=commissioned_energy/.96-commissioned_energy
                        g['cash']-=commissioned_energy/.96*1000*.65
                    event(g,p['name']+' commissioned.','complete')
                    net=Network('collector_upgrade' in g['upgrades'],g)
            evaluate(g,net,commit=True)
    elif kind=='build':
        p=next((p for p in catalog(g) if p['id']==command.get('target')),None)
        if not p: raise RuleError('Unknown construction project.')
        if p['id'] in g['upgrades'] or any(x['id']==p['id'] for x in g['projects']): raise RuleError('Project is already built or under construction.')
        if g['cash']<p['cost']: raise RuleError('Insufficient construction funds.')
        if p['schedule']['finish_step']>35040:raise RuleError('Commissioning exceeds the one-year scenario horizon. Resize, add resources or start a new scenario.')
        g['cash']-=p['cost'];g['projects'].append(dict(**p,start=g['step'],finish=p['schedule']['finish_step']))
        event(g,p['name']+f" construction started; Duration {p['days']} days.",'construction')
    elif kind=='plan_save':
        g['draft']=normalize(command.get('plan'))
    elif kind=='plan_build':
        check=check_plan(g,command.get('plan'))
        if check['errors']:raise RuleError('; '.join(check['errors']))
        if not check['affordable']:raise RuleError('Investment exceeds available funds. Reduce the size or earn more funds.')
        p=check['plan'];pid=next_plant_id(g)
        project=dict(id=pid,name=p['name'],cost=check['cost'],days=check['schedule']['days'],schedule=check['schedule'],
                     start=g['step'],finish=check['schedule']['finish_step'],plan=p)
        g['cash']-=check['cost'];g['projects'].append(project);g['draft']=deepcopy(p)
        event(g,f"{p['name']} approved for construction: {check['turbine_count']} turbines / {check['capacity_mw']:g} MW; Calculated duration {check['schedule']['days']:g} days.",'construction')
    elif kind=='settings':
        values=command.get('settings',{})
        ranges={'reserve_soc':(.15,.85),'import_limit_mw':(0.,20.),'export_limit_mw':(0.,20.),'pickup_multiplier':(1.05,3.),'tms':(.05,1.)}
        for k,v in values.items():
            if k in ranges:
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not ranges[k][0]<=v<=ranges[k][1]: raise RuleError('Relay / dispatch value outside allowed range.')
            elif k=='dispatch':
                if v not in ('self_use','reserve'): raise RuleError('Unknown dispatch strategy.')
            elif k=='volt_var':
                if type(v) is not bool: raise RuleError('Reactive control must be a Boolean.')
            else: raise RuleError('Unknown setting.')
            g['settings'][k]=v
        event(g,'Dispatch / protection settings updated.')
    elif kind=='weather':
        if command.get('target') not in WEATHER: raise RuleError('Unknown weather mode.')
        g['weather']=command['target'];event(g,'Weather test selected: '+WEATHER[g['weather']])
    elif kind=='fault': inject(g,command.get('target',''),command.get('breaker_failure',False))
    elif kind=='repair': repair(g,command.get('target',''))
    elif kind=='maintenance':
        ids=[t['id'] for t in fleet(g)]
        if command.get('target') not in ids: raise RuleError('Unknown turbine.')
        i=ids.index(command['target']);g['turbines'][i]['maintenance']=not g['turbines'][i]['maintenance']
        event(g,command['target']+('Start maintenance.' if g['turbines'][i]['maintenance'] else ' maintenance complete; reconnected.'))
    else: raise RuleError('Unknown command.')
    if kind!='advance': evaluate(g)
    g['revision']=game['revision']+1
    g['version']=VERSION
    return g


def public(g):
    out=deepcopy(g)
    if out.get('version')!=VERSION or 'snapshot' not in out:evaluate(out)
    out['catalog']=catalog(g)
    out['timestamp']=(datetime(2030,1,1)+timedelta(minutes=15*g['step'])).strftime('%Y-%m-%d %H:%M')
    out['installed_mw']=(40 if 'wind_phase2' in g['upgrades'] else 20)+sum(n['rated_mw'] for p in g.get('plants',[]) for n in p['plan']['nodes'] if n['kind']=='turbine')
    out['plants']=g.get('plants',[]);out['draft']=g.get('draft',default_plan());out['version']=VERSION
    return out


def next_plant_id(g):
    return 'P'+str(len(g.get('plants',[]))+sum('plan' in p for p in g['projects'])+1).zfill(2)


def check_plan(game,plan):
    report=audit(plan);p=report['plan'];report['schedule']=schedule(p,game['step'],game['seed'])
    report['cost']+=report['schedule']['resource_cost'];report['affordable']=game['cash']>=report['cost']
    report['finish_step']=report['schedule']['finish_step']
    if report['finish_step']>35040:report['errors'].append('Commissioning exceeds the one-year scenario horizon. Resize, add resources or start a new scenario.')
    if len(game.get('plants',[]))+sum('plan' in x for x in game['projects'])>=4:report['errors'].append('Up to four custom plants are supported per scenario.')
    # Include already-approved projects in the commissioning study. Never mutate live state.
    if not report['errors']:
        sample=deepcopy(game);sample.setdefault('plants',[])
        for project in sample['projects']:
            if 'plan' in project:commission(sample,project)
        project=dict(id=next_plant_id(game),name=p['name'],plan=p)
        commission(sample,project)
        try:
            evaluate(sample)
            report['preview']=dict(metrics=sample['metrics'],network=sample['snapshot']['network'],
                                   turbines=[t for t in sample['snapshot']['turbines'] if t['farm_id']==project['id']],
                                   constraints=sample['snapshot']['constraints'])
            if sample['metrics']['curtailment_mw']>.1:report['warnings'].append('Commissioning preview requires curtailment. Check export, storage and cable limits.')
        except Exception as exc:
            report['errors'].append('AC power flow preview failed. Check cable impedance, transformer ratings and topology.')
    return report


def catalog(game):
    result=[]
    for base in PROJECTS:
        p=default_plan();mode={'wind_phase2':'wind','battery_phase2':'battery','collector_upgrade':'collector'}[base['id']]
        if mode=='battery':p['storage_power_mw']=6;p['storage_capacity_mwh']=24
        timing=schedule(p,game['step'],game['seed'],mode)
        result.append(dict(base,days=timing['days'],schedule=timing))
    return result
