"""Reproducible scale/profile/worker checks; synthetic scale fixtures are not calibrated islands.

Run: python tools/acceptance.py --output results/acceptance-scale.json
"""
import argparse
import cProfile
import copy
import heapq
import json
import resource
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.world import World
from app import construction as C,society as S,materials as M,energy as N,history as H,dynamics as D
from app.saves import validate
from app.runtime import Worker


def cohorts(w,target):
    heap=[(-p['count'],p['id']) for p in w.pops.values() if p['kind']=='resident' and p['count']>1]
    heapq.heapify(heap)
    while len(w.pops)<target and heap:
        _,pid=heapq.heappop(heap);p=w.pops[pid]
        if p['count']<=1:continue
        n=p['count']//2;share=n/p['count'];key=f"cohort{w.next_id('cohort')}"
        new=copy.deepcopy(p);new.update(id=key,count=n)
        take=int(p['employed']*share);new['employed']=take
        inactive=p.get('inactive',0);moved=min(inactive,n-take,round(inactive*share))
        moved+=max(0.,p['employed']-take+inactive-moved-(p['count']-n));moved=int(moved)
        if 'inactive' in p:new['inactive']=moved;p['inactive']-=moved
        left=take
        for staff in w.jobs.values():
            have=staff.get(pid,0)
            if have and left:
                k=min(have,left);staff[pid]-=k;staff[key]=k;left-=k
                if not staff[pid]:del staff[pid]
        assert left==0
        p['employed']-=take;p['count']-=n
        new['income_ema']=p['income_ema']*share;p['income_ema']-=new['income_ema']
        w.pops[key]=new
        w.ledger.transfer('pop:'+pid,'pop:'+key,w.ledger.balance('pop:'+pid)*share,'cohort split')
        if 'pop:'+pid in w.contracts:w.contracts['pop:'+key]=copy.deepcopy(w.contracts['pop:'+pid])
        for obj in (p,new):
            if obj['count']>1:heapq.heappush(heap,(-obj['count'],obj['id']))
    S.refresh_stats(w)


def scale(w,turbines):
    baseline_rating=sum(t['mw'] for t in w.grid['turbines'].values())
    bases=list(w.grid['farms'].values())
    for i in range(len(w.grid['turbines']),turbines):
        host=bases[i%len(bases)];bus=host['hub'];node=w.grid['buses'][bus]
        C.add_turbine(w,dict(model='PB-3.6',x=node['x']+.7*((i//len(bases))%5),
                            y=node['y']+.7*((i//len(bases))//5),farm='bench_'+host['id'],connect_bus=bus,cable_km=.3))
    for b in w.grid['branches'].values():
        if b['kind']=='transformer' and b['type']=='110/33':b['mva']=max(b['mva'],turbines*3.6/len(bases)*1.2)
    for tb in w.grid['turbines'].values():
        tb.update(q_mode='fixed',q_setpoint=0.)
    w.network.dirty=True
    total_rating=sum(t['mw'] for t in w.grid['turbines'].values())
    return baseline_rating/total_rating,baseline_rating,total_rating


def profile_modules(w,minutes=10):
    profile=cProfile.Profile(timer=time.process_time)
    profile.enable();w.advance(minutes);profile.disable()
    import pstats
    totals={}
    for (filename,line,name),values in pstats.Stats(profile).stats.items():
        if '/app/' in filename:
            module=filename.split('/app/',1)[1].split('/')[0]
        elif any(k in filename for k in ('opendssdirect','/dss/','numpy')):module='native_backend_wrappers'
        else:module='stdlib_and_runtime'
        totals[module]=totals.get(module,0.)+values[2]
    return totals


def retained_save_size(w):
    """Fill every bounded history tier with current numeric samples to test browser-save transport."""
    objects=list(w.devices)+list(w.grid['branches'])
    w.archive.selected=objects[:8]
    for minute in range(1,1441):
        w.archive.minute(w,w.minute+minute)
    start=w.minute-w.minute%60+60
    for hour in range(30*24):
        H.capture_hour(w,start+hour*60)
    event_objects=objects[:12]
    samples=[[round(i*.02,7),50.,1.,40.,20.,0.,0.,20.,1.] for i in range(501)]
    object_rows=[[round(i*.02,7),1.,0.,1.,.2,0.] for i in range(501)]
    w.archive.waveforms.clear()
    for event in range(8):
        w.archive.waveforms.append(dict(id=f'fixture{event}',t=start+event,cause='bounded retention capacity fixture',
            model='storage-size fixture; not a simulated event',step_seconds=.02,fields=D.FIELDS,samples=samples,
            actions=[dict(seconds=i*.02,text='retention fixture action') for i in range(200)],status='fixture',
            object_fields=D.OBJECT_FIELDS,object_samples={key:object_rows for key in event_objects}))
    compressed=w.state();packed=compressed['archive'];plain=H.unpack(packed)
    compressed_bytes=len(json.dumps(compressed,separators=(',',':')).encode())
    compressed['archive']=plain
    raw_bytes=len(json.dumps(compressed,separators=(',',':')).encode())
    compressed['archive']=packed
    validate(compressed)
    return dict(method='All 168 hourly, 30 daily, 1440-minute selected-object and 8 event slots filled with current/synthetic numeric storage samples',
                simulated_claim=False,raw_save_bytes=raw_bytes,compressed_save_bytes=compressed_bytes,
                compression_ratio=compressed_bytes/raw_bytes,api_body_limit_bytes=12_000_000,
                fits_api_body=compressed_bytes+9<12_000_000)


def scenario(name,pops,turbines,minutes,save_path=None):
    w=World(seed=1);cohorts(w,pops);wind_factor,baseline_rating,total_rating=scale(w,turbines)
    # The fixture scales graph/object count, not island generation. Give every turbine a non-zero,
    # weather-driven injection while holding aggregate available wind near the calibrated base fleet.
    # Otherwise a 600-turbine synthetic fleet tests an impossible export case rather than UI/core scale.
    available=N.available_wind
    N.available_wind=lambda world,t,weather:{k:v*wind_factor for k,v in available(world,t,weather).items()}
    start=time.perf_counter();cpu=time.process_time();w.advance(minutes)
    cpu=time.process_time()-cpu;wall=time.perf_counter()-start
    state=w.state();validate(state)
    encoded=json.dumps(state,separators=(',',':'))
    if save_path:Path(save_path).write_text(encoded,encoding='utf-8')
    report=dict(name=name,pop_objects=len(w.pops),residents=S.residents(w),turbines=len(w.grid['turbines']),
        buses=len(w.grid['buses']),branches=len(w.grid['branches']),minutes=minutes,wall_s=wall,cpu_s=cpu,
        cpu_ms_per_simulated_hour=cpu*60000/minutes,solve=w.perf['all_solve'].summary(),
        numerical_failures=w.perf['failures'],peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        save_bytes=len(encoded.encode()),max_goods_residual=max(abs(x['residual']) for x in M.report(w).values()),
        jobs_consistent=all(p['employed']==sum(j.get(p['id'],0) for j in w.jobs.values()) for p in w.pops.values()),
        people_preserved=S.residents(w)==55300,requested_mwh=w.acc['load_req'],served_mwh=w.acc['load_srv'],
        service_fraction=w.acc['load_srv']/max(1e-12,w.acc['load_req']),energized_buses=len(w.network.energized),
        normally_open_branches=sum(not b['closed'] for b in w.grid['branches'].values()),
        tripped_or_repair_branches=sum(b['tripped'] or b['repair_until'] is not None for b in w.grid['branches'].values()),
        wind_availability_factor=wind_factor,baseline_wind_rating_mw=baseline_rating,synthetic_wind_rating_mw=total_rating,
        profile_minutes=10,profile_cpu_seconds=profile_modules(w,10),
        note=('Synthetic object-count fixture: every turbine retains its electrical branch and weather response; '
              'per-turbine availability is scaled uniformly so aggregate available wind matches the calibrated base fleet; '
              'turbines use compact 0.3 km synthetic collectors at unity power factor, collector transformers are reinforced, and 10-minute profiling '
              'follows the timed interval'))
    if name=='full':report['retention_capacity']=retained_save_size(w)
    print(json.dumps({k:v for k,v in report.items() if k not in ('profile_cpu_seconds','solve')},ensure_ascii=False),flush=True)
    return report


def isolated_case(args):
    """Run one OpenDSS context in a child so native allocations cannot accumulate between cases."""
    name,pops,turbines,minutes,save_path=args
    with tempfile.NamedTemporaryFile(suffix='.json',delete=False) as tmp:
        result=Path(tmp.name)
    try:
        cmd=[sys.executable,str(Path(__file__).resolve()),'--case',name,str(pops),str(turbines),str(minutes),'--case-output',str(result)]
        if save_path:cmd.extend(['--full-save',str(save_path)])
        run=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=True)
        if run.stdout:print(run.stdout.strip(),flush=True)
        return json.loads(result.read_text(encoding='utf-8'))
    finally:
        result.unlink(missing_ok=True)


def concurrency():
    workers=[Worker(),Worker()]
    try:
        for i,w in enumerate(workers):w.call('new',f's{i}',dict(seed=i+1))
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(w.call,'tick',f's{i}',dict(minutes=240,budget=120.,since_log=0,grid_version=-1,firm_count=-1)) for i,w in enumerate(workers)]
            results=[job.result() for job in jobs]
        return dict(workers=2,sessions=2,wall_s=time.perf_counter()-start,
                    simulated_minutes=[r['snapshot']['minute'] for r in results],
                    failures=[r['snapshot']['perf']['failures'] for r in results])
    finally:
        for w in workers:w.stop()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path)
    p.add_argument('--full-save',default='/workspace/powerbolaget-scale-full-save.json')
    p.add_argument('--case',nargs=4,metavar=('NAME','POPS','TURBINES','MINUTES'))
    p.add_argument('--case-output',type=Path)
    a=p.parse_args()
    if a.case:
        name,pops,turbines,minutes=a.case
        report=scenario(name,int(pops),int(turbines),int(minutes),a.full_save if name=='full' else None)
        a.case_output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        return
    if a.output is None:
        p.error('--output is required unless --case is used')
    cases=[('small',190,54,120,None),('medium',2000,180,120,None),('large',6000,360,120,None),
           ('full',10000,600,120,a.full_save)]
    data=dict(method='Timed single-world intervals + separate profile interval + two worker processes',
        cases=[isolated_case(x) for x in cases],concurrency=concurrency())
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(data,indent=2),encoding='utf-8')


if __name__=='__main__':main()
