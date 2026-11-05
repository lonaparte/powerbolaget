"""Run the world without any player action and record performance and island indicators.

    python tools/benchmark.py --days 365 --seed 1 --output results/benchmark-365d.json

Spec 10.2: report CPU per simulated hour, power-flow p50/p95, failures, memory and how the island
develops on its own. Nothing here is a target; it records what the model does on this machine.
"""
import argparse
import json
import platform
import resource
import statistics
import sys
import time
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import __version__  # noqa: E402
from app.calendar import label  # noqa: E402
from app.saves import validate  # noqa: E402
from app.world import World  # noqa: E402


def write_checkpoint(path,w,days):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(w.state(),separators=(',',':')),encoding='utf-8')
    temporary.replace(path)
    progress=path.with_name(path.name+'.progress.json')
    temporary=progress.with_name(progress.name+'.tmp')
    temporary.write_text(json.dumps(days,separators=(',',':')),encoding='utf-8')
    temporary.replace(progress)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--checkpoint',type=Path,help='write the final resumable world for inspection')
    ap.add_argument('--resume',type=Path,help='continue from a benchmark checkpoint')
    ap.add_argument('--checkpoint-every',type=int,default=10)
    a = ap.parse_args()
    t0 = time.perf_counter()
    if a.resume:
        w=World(state=validate(json.loads(a.resume.read_text(encoding='utf-8'))))
        progress=a.resume.with_name(a.resume.name+'.progress.json')
        days=json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else []
        if len(days)!=len(w.history_day):
            raise ValueError('Benchmark progress does not match the world checkpoint.')
    else:
        w=World(seed=a.seed);days=[]
    for d in range(len(days),a.days):
        c0 = time.process_time()
        w.advance(1441 if w.minute == 0 else 1440)   # the day is settled at the next midnight
        cpu = time.process_time()-c0
        h = w.history_day[-1]
        st = w.society_stats
        days.append(dict(day=d+1, date=label(w.minute-1), cpu_s=round(cpu, 3), ms_per_sim_hour=round(cpu/24*1000, 1),
                         load_mwh=h['load_mwh'], unserved_mwh=h['unserved_mwh'], wind_mwh=h['wind_mwh'], import_mwh=h['import_mwh'],
                         export_mwh=h['export_mwh'], peak_mw=h['peak_mw'], residents=h['residents'], tourists=h['tourists'],
                         unemployed=h['unemployed'], pb_cash_msek=round(h['pb_cash']/1e6, 1), firms=len(w.firms),
                         pops=len(w.pops), money_sum=round(sum(w.ledger.accounts.values()), 3)))
        check=w.conservation_history[-1] if w.conservation_history else {}
        days[-1].update(active_firms=sum(f['status']=='operating' for f in w.firms.values()),
            exited_firms=sum(f['status']=='exited' for f in w.firms.values()),
            debt_sek=sum(f.get('credit',{}).get('debt',0.) for f in w.firms.values()),
            max_goods_residual=max((abs(v['residual']) for v in check.get('goods',{}).values()),default=0.),
            max_water_residual=max((abs(v) for v in check.get('water',{}).values()),default=0.))
        if (d+1) % 10 == 0:
            print(f"day {d+1}: {days[-1]['ms_per_sim_hour']} ms/sim-h, residents {h['residents']}, tourists {h['tourists']}, "
                  f"unserved {h['unserved_mwh']} MWh, pb {days[-1]['pb_cash_msek']} MSEK", flush=True)
        if a.checkpoint and a.checkpoint_every>0 and (d+1)%a.checkpoint_every==0:
            write_checkpoint(a.checkpoint,w,days)
    solves = sorted(w.perf['solve_ms'])
    q = lambda xs, f: round(xs[min(len(xs)-1, int(f*len(xs)))], 3) if xs else None
    report = dict(
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        processor_model=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),platform.machine()),
        version=__version__, seed=w.seed, days=a.days, python=platform.python_version(), machine=platform.machine(),
        processor=platform.processor() or platform.machine(), wall_s=round(time.perf_counter()-t0, 1),
        ms_per_sim_hour=dict(mean=round(statistics.mean(x['ms_per_sim_hour'] for x in days), 1),
                             p95=q(sorted(x['ms_per_sim_hour'] for x in days), .95)),
        power_flow_ms=w.perf['all_solve'].summary(),recent_power_flow_ms=dict(p50=q(solves,.5),p95=q(solves,.95),samples=len(solves),scope='last 2000 solves'),numerical_failures=w.perf['failures'],
        peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, 1),
        save_kb=round(len(json.dumps(w.state()))/1024, 1), log_tail=[e['label']+' '+e['text'] for e in list(w.logbook)[-25:]],
        demography=w.demography['months'], days_detail=days,energy_gwh=sum(d['load_mwh'] for d in days)/1000,
        final_firms=[dict(id=f['id'],kind=f['kind'],status=f['status'],staff=f['staff'],margin=f['ema_margin'],
                         cash=w.ledger.balance('firm:'+f['id']),credit=f.get('credit')) for f in w.firms.values()])
    print(json.dumps({k: v for k, v in report.items() if k not in ('days_detail', 'demography', 'log_tail','final_firms')}, indent=1))
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=1), encoding='utf-8')
    if a.checkpoint:
        a.checkpoint.parent.mkdir(parents=True,exist_ok=True)
        write_checkpoint(a.checkpoint,w,days)


if __name__ == '__main__':
    main()
