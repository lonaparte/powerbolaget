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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import __version__  # noqa: E402
from app.calendar import label  # noqa: E402
from app.world import World  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    t0 = time.perf_counter()
    w = World(seed=a.seed)
    days = []
    for d in range(a.days):
        c0 = time.process_time()
        w.advance(1441 if d == 0 else 1440)   # the day is settled at the next midnight
        cpu = time.process_time()-c0
        h = w.history_day[-1]
        st = w.society_stats
        days.append(dict(day=d+1, date=label(w.minute-1), cpu_s=round(cpu, 3), ms_per_sim_hour=round(cpu/24*1000, 1),
                         load_mwh=h['load_mwh'], unserved_mwh=h['unserved_mwh'], wind_mwh=h['wind_mwh'], import_mwh=h['import_mwh'],
                         export_mwh=h['export_mwh'], peak_mw=h['peak_mw'], residents=h['residents'], tourists=h['tourists'],
                         unemployed=h['unemployed'], pb_cash_msek=round(h['pb_cash']/1e6, 1), firms=len(w.firms),
                         pops=len(w.pops), money_sum=round(sum(w.ledger.accounts.values()), 3)))
        if (d+1) % 10 == 0:
            print(f"day {d+1}: {days[-1]['ms_per_sim_hour']} ms/sim-h, residents {h['residents']}, tourists {h['tourists']}, "
                  f"unserved {h['unserved_mwh']} MWh, pb {days[-1]['pb_cash_msek']} MSEK", flush=True)
    solves = sorted(w.perf['solve_ms'])
    q = lambda xs, f: round(xs[min(len(xs)-1, int(f*len(xs)))], 3) if xs else None
    report = dict(
        version=__version__, seed=a.seed, days=a.days, python=platform.python_version(), machine=platform.machine(),
        processor=platform.processor() or platform.machine(), wall_s=round(time.perf_counter()-t0, 1),
        ms_per_sim_hour=dict(mean=round(statistics.mean(x['ms_per_sim_hour'] for x in days), 1),
                             p95=q(sorted(x['ms_per_sim_hour'] for x in days), .95)),
        power_flow_ms=dict(p50=q(solves, .5), p95=q(solves, .95), samples=len(solves)), numerical_failures=w.perf['failures'],
        peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, 1),
        save_kb=round(len(json.dumps(w.state()))/1024, 1), log_tail=[e['label']+' '+e['text'] for e in list(w.logbook)[-25:]],
        demography=w.demography['months'], days_detail=days)
    print(json.dumps({k: v for k, v in report.items() if k not in ('days_detail', 'demography', 'log_tail')}, indent=1))
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
