"""Run every 15-minute interval in a year, including all construction events."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engine import create, apply

started=time.perf_counter(); g=create();actions=[];max_residual=0.;max_loading=0.;min_soc=1.;max_soc=0.
for p in ('wind_phase2','battery_phase2','collector_upgrade'):
    a=dict(kind='build',target=p);g=apply(g,a);actions.append(a)
while g['step']<35040:
    a=dict(kind='advance',steps=min(672,35040-g['step']))
    g=apply(g,a);actions.append(a)
    for m in g['history'][-a['steps']:]:
        max_residual=max(max_residual,abs(m['balance_error_mw']))
        max_loading=max(max_loading,m['max_loading_pct'])
        min_soc=min(min_soc,m['soc']);max_soc=max(max_soc,m['soc'])
        assert -.005-5<=m['grid_mw']<=12.005, m
        assert .15-1e-8<=m['soc']<=.90+1e-8, m
        assert m['max_loading_pct']<=100.01, m
    if g['step']%(672*5)==0:print(f"Simulated day {g['step']/96:.0f}",flush=True)
t=g['totals']
balance=t['wind_mwh']+t['import_mwh']-t['served_mwh']-t['export_mwh']-t['loss_mwh']-t['auxiliary_mwh']-t['battery_loss_mwh']-(g['battery']['energy_mwh']-14.4)
assert abs(balance)<.2
assert max_residual<.005
assert len(g['upgrades'])==3
report=dict(steps=g['step'],days=g['step']/96,seconds=time.perf_counter()-started,
            max_residual_kw=max_residual*1000,max_loading_pct=max_loading,soc_range=[min_soc,max_soc],
            annual_energy_error_mwh=balance,totals=t,upgrades=g['upgrades'],cash=g['cash'],
            direct_wind_share_pct=100*t['wind_direct_mwh']/t['served_mwh'])
out=Path(__file__).resolve().parents[1]/'results';out.mkdir(exist_ok=True)
(out/'annual-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(out/'annual-replay.json').write_text(json.dumps(dict(format='powergame.coastal.v2',seed=42,commands=actions)),encoding='utf-8')
print(json.dumps(report,indent=2),flush=True)
