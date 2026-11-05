"""Per-good stock identity, separate from the zero-sum money ledger.

Each good keeps its own declared unit. Recipes transform goods; the check never adds
tonnes, fuel MWh and service baskets into a meaningless scalar mass total.
"""
from collections import defaultdict


def stocks(world):
    out=defaultdict(float)
    for f in world.firms.values():
        for g,q in f['inventory'].items():
            out[g]+=q
    return dict(out)


def net_flows(world):
    out=defaultdict(float,world.ledger.quantities)
    for f in world.firms.values():
        for g,q in f.get('materials',{}).get('produced',{}).items():out[g]+=q
        for g,q in f.get('materials',{}).get('consumed',{}).items():out[g]-=q
    return dict(out)


def baseline(world):
    return dict(minute=world.minute,stocks=stocks(world),flows=net_flows(world))


def report(world):
    actual,flow=stocks(world),net_flows(world)
    base=world.material_baseline
    out={}
    for g in set(actual)|set(base['stocks']):
        expected=base['stocks'].get(g,0.)+flow.get(g,0.)-base['flows'].get(g,0.)
        out[g]=dict(unit=world.markets.get(g,{}).get('unit','product unit'),stock=actual.get(g,0.),
                    expected=expected,residual=actual.get(g,0.)-expected)
    return out
