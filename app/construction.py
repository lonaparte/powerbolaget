"""Quantity-based critical-path scheduling with hourly synthetic marine windows.

Production rates are explicit scenario assumptions, not an ORBIT implementation
or site-calibrated contractor schedule. Dedicated crews are rented per project.
"""
from math import ceil, sin, cos, pi
from functools import lru_cache
from datetime import datetime, timedelta
from .climate import conditions


@lru_cache(maxsize=60000)
def marine_weather(seed,hour):
    # Reproducible seasonal and synoptic sea-state series, independent of UI test modes.
    met=conditions(seed,hour*4)
    return met['wind_10m_ms'],met['wave_height_m']


def schedule(plan,start_step,seed=42,mode='plant'):
    r=plan['resources'];units=[n for n in plan['nodes'] if n['kind']=='turbine']
    n=len(units);mw=sum(t['rated_mw'] for t in units);max_mw=max((t['rated_mw'] for t in units),default=5)
    km=sum(e['length_km'] for e in plan['edges']);start=ceil(start_step/4)
    phases=[];day=start//24
    def land_finish(at,hours,crews=1):
        # Eight-hour site shifts; day boundaries preserve chronology and resource capacity.
        return at+ceil(hours/(8*crews))*24
    def phase(key,name,at,end,work,wait=0,deps=(),resource=''):
        phases.append(dict(id=key,name=name,start_hour=at-start,end_hour=end-start,work_hours=round(work,1),
                           weather_wait_hours=wait,dependencies=list(deps),resource=resource,duration_days=round((end-at)/24,2)))
        return end
    design_work=80+n*8+km*2+r['water_depth_m']*2
    if mode=='battery':design_work=40+plan['storage_capacity_mwh']
    design=phase('design','Survey & engineering',start,land_finish(start,design_work,r['engineering_teams']),design_work,
                 resource=f"{r['engineering_teams']} engineering teams · 8 h/day")
    # Manufacturing lead scales with the largest unit, quantity, transformer and BESS.
    lead=ceil(max(45+6*max_mw+2*n/r['supply_lines'] if mode in ('plant','wind') else 0,
                  25+.8*plan['transformer_mva'] if mode=='plant' else 0,
                  30+.7*plan['storage_capacity_mwh'] if plan['storage_capacity_mwh'] else 0,
                  14+.6*km))
    procurement=phase('supply','Manufacture & delivery',design,design+lead*24,lead*24,deps=['design'],resource=f"{r['supply_lines']} turbine supply lines")
    transit=2*r['port_distance_km']/18.52 # 10 knot transport equivalent, per lift/cable job.
    def marine_jobs(at,jobs,vessels,limits):
        clocks=[at]*vessels;weather_wait=0
        for work in jobs:
            k=min(range(vessels),key=lambda i:clocks[i]);h=clocks[k];left=ceil(work)
            while left:
                block=min(6,left) # Uninterrupted six-hour work windows; pause between blocks.
                if all(marine_weather(seed,h+j)[0]<=limits[0] and marine_weather(seed,h+j)[1]<=limits[1] for j in range(block)):
                    h+=block;left-=block
                else:h+=1;weather_wait+=1
                if h-at>24*730:raise ValueError('Insufficient offshore weather windows within the two-year scheduling horizon')
            clocks[k]=h
        return max(clocks),weather_wait
    foundations=[(20*(t['rated_mw']/5)**.65*(1+r['water_depth_m']/80)+transit) for t in units] if mode in ('plant','wind') else []
    end,wait=marine_jobs(procurement,foundations,r['foundation_vessels'],(14,2.2))
    foundation=phase('foundation','Foundation installation',procurement,end,sum(foundations),wait,['supply'],f"{r['foundation_vessels']} foundation vessels · 14 m/s / 2.2 m")
    lifts=[(12+t['hub_m']/8+t['rotor_m']/12+3*t['rated_mw']+transit) for t in units] if mode in ('plant','wind') else []
    end,wait=marine_jobs(foundation,lifts,r['installation_vessels'],(12,1.8))
    turbines=phase('turbines','Turbine installation',foundation,end,sum(lifts),wait,['foundation'],f"{r['installation_vessels']} installation vessels · 12 m/s / 1.8 m")
    cables=[8+e['length_km']/.25+transit for e in plan['edges']] if mode!='battery' else []
    end,wait=marine_jobs(foundation,cables,r['cable_vessels'],(15,2.0))
    cable=phase('cables','Cable installation',foundation,end,sum(cables),wait,['foundation'],f"{r['cable_vessels']} cable vessels · 15 m/s / 2.0 m")
    shore_work=(72+3*plan['transformer_mva'] if mode=='plant' else 0)+2*plan['storage_capacity_mwh']+8*plan['storage_power_mw']
    shore=phase('shore','Onshore electrical & BESS',procurement,land_finish(procurement,shore_work,r['electrical_teams']),shore_work,
                deps=['supply'],resource=f"{r['electrical_teams']} electrical teams · 8 h/day")
    gate=max(turbines,cable,shore);test_work=24+6*n+2*len(plan['edges'])+plan['storage_power_mw']*2
    finish=phase('commission','Integration & commissioning',gate,land_finish(gate,test_work,r['electrical_teams']),test_work,
                 deps=['turbines','cables','shore'],resource=f"{r['electrical_teams']} electrical teams · 8 h/day")
    byid={p['id']:p for p in phases};critical=[];key='commission'
    while key:
        critical.append(key);deps=byid[key]['dependencies']
        key=max(deps,key=lambda d:byid[d]['end_hour']) if deps else None
    finish_step=finish*4
    days=(finish_step-start_step)/96
    return dict(days=round(days,2),finish_step=finish_step,finish_date=(datetime(2030,1,1)+timedelta(minutes=15*finish_step)).strftime('%Y-%m-%d %H:%M'),
                phases=phases,critical_path=list(reversed(critical)),weather_wait_vessel_hours=sum(p['weather_wait_hours'] for p in phases),
                basis='Work quantities + dependencies + dedicated resources + hourly weather windows; productivity is assumed, not a contractor commitment',
                resource_cost=round(sum((p['end_hour']-p['start_hour'])/24*({'foundation':r['foundation_vessels']*180000,'turbines':r['installation_vessels']*240000,'cables':r['cable_vessels']*130000}.get(p['id'],0)) for p in phases)))
