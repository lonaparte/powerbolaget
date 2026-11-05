"""Short-horizon one-at-a-time sensitivity checks for declared assumptions.

This is not an annual calibration. Every operational case uses the same seed, weather and no-player
policy, changing exactly one imported coefficient in an isolated Python process.
"""
import argparse
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


CASES={
    'demand_low':('app.loads','DEMAND_SCALE',.9),
    'demand_high':('app.loads','DEMAND_SCALE',1.1),
    'thermal_low':('app.loads','UA_HOUSEHOLD',.8),
    'thermal_high':('app.loads','UA_HOUSEHOLD',1.2),
    'wake_low':('app.energy','WAKE_K',.8),
    'wake_high':('app.energy','WAKE_K',1.2),
    'price_low':('app.world','PRICE_BASE',.8),
    'price_high':('app.world','PRICE_BASE',1.2),
}


def simulate(name,days):
    from importlib import import_module
    from app.world import World
    if name!='baseline':
        module,attribute,factor=CASES[name]
        target=import_module(module)
        setattr(target,attribute,getattr(target,attribute)*factor)
    w=World(seed=1)
    for _ in range(days):w.advance(1441 if w.minute==0 else 1440)
    rows=w.history_day[-days:]
    return dict(name=name,days=days,load_mwh=sum(x['load_mwh'] for x in rows),served_mwh=sum(x['served_mwh'] for x in rows),
        unserved_mwh=sum(x['unserved_mwh'] for x in rows),wind_mwh=sum(x['wind_mwh'] for x in rows),
        import_mwh=sum(x['import_mwh'] for x in rows),export_mwh=sum(x['export_mwh'] for x in rows),
        losses_mwh=sum(x[5] for x in w.archive.hours.get('global',[])),peak_mw=max(x['peak_mw'] for x in rows),
        pb_cash_msek=w.ledger.balance('pb')/1e6,residents=sum(w.society_stats['zone_residents'].values()),
        numerical_failures=w.perf['failures'],money_residual=sum(w.ledger.accounts.values()),
        max_goods_residual=max(abs(x['residual']) for x in w.conservation_history[-1]['goods'].values()),
        max_water_residual=max(abs(x) for x in w.conservation_history[-1]['water'].values()))


def isolated(name,days):
    with tempfile.NamedTemporaryFile(suffix='.json',delete=False) as tmp:path=Path(tmp.name)
    try:
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--case',name,'--days',str(days),'--case-output',str(path)],
                       cwd=ROOT,check=True)
        return json.loads(path.read_text(encoding='utf-8'))
    finally:path.unlink(missing_ok=True)


def finance_stress():
    from app.world import World
    from app import finance as F
    rows=[]
    original=F.APR
    for apr in (.04,.08,.12):
        w=World(seed=1);f=w.firms['f_brewery'];account='firm:'+f['id'];cash=w.ledger.balance(account)
        if cash:w.ledger.transfer(account,'external',cash,'stress opening balance')
        c=F.account(w,f);c['limit']=3e6;c['debt']=2e6
        w.ledger.transfer('bank',account,2e6,'stress loan')
        F.APR=apr
        for day in range(1,31):F.close_day(w,day*1440)
        rows.append(dict(apr=apr,ending_debt_sek=c['debt'],interest_sek=c['interest'],repaid_sek=c['repaid'],status=f['status']))
    F.APR=original
    return rows


def construction_ranges():
    from app.world import World,plan_build
    from app.params import COST,DAYS
    w=World(seed=1)
    plan=plan_build(w,dict(type='storage',station='vhn',p_mw=20.,hours=4.,grid_forming=True))
    return dict(example=plan['title'],baseline_cost_sek=plan['cost'],baseline_days=plan['days'],
                cost_range_sek=[plan['cost']*.8,plan['cost']*1.2],duration_range_days=[plan['days']*.8,plan['days']*1.2],
                varied_inputs='All storage MW/MWh capex terms or construction duration together by ±20%',
                declared_cost_assumptions={k:COST[k] for k in ('storage_mw','storage_mwh','grid_forming_extra')},
                declared_duration_days=DAYS['storage'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);p.add_argument('--days',type=int,default=3)
    p.add_argument('--case',choices=['baseline',*CASES]);p.add_argument('--case-output',type=Path)
    a=p.parse_args()
    if a.case:
        a.case_output.write_text(json.dumps(simulate(a.case,a.days),indent=2),encoding='utf-8');return
    if not a.output:p.error('--output is required')
    cases=[isolated(name,a.days) for name in ['baseline',*CASES]]
    baseline=cases[0]
    for row in cases[1:]:
        row['change_from_baseline_pct']={key:100*(row[key]/baseline[key]-1) if baseline[key] else None
            for key in ('load_mwh','wind_mwh','import_mwh','losses_mwh','peak_mw','pb_cash_msek')}
    processor=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),platform.machine())
    report=dict(git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),python=platform.python_version(),processor=processor,
        method='One-at-a-time isolated subprocesses; seed 1; identical first three winter days; no player actions',
        scope='Short-run local sensitivity, not annual macro calibration or uncertainty probabilities',cases=cases,
        private_credit_30_day_stress=finance_stress(),construction_example=construction_ranges())
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
