"""Versioned semantic module boundary: plans, trajectories, physical results and settlements.

Times are simulation minutes, P/Q are MW/Mvar and energy MWh. Every message states
whether values are intentions or actuals and identifies the topology/forecast used.
"""
import hashlib
import json

SCHEMA='powerbolaget.exchange/1'
KINDS={'ActivityPlan':'intent','DemandTrajectory':'forecast','PhysicalResult':'actual','EconomicSettlement':'actual'}


def message(world,kind,start,end,payload,issued=None):
    if kind not in KINDS or end<start:
        raise ValueError('Invalid semantic exchange interval.')
    body=dict(schema=SCHEMA,kind=kind,meaning=KINDS[kind],seed=world.seed,
              issued=world.minute if issued is None else issued,valid_from=start,valid_to=end,
              clock_unit='minute',units=dict(power='MW',reactive_power='Mvar',energy='MWh',money='SEK'),
              mapping_version=world.grid['version'],forecast_version=1,payload=payload)
    body['id']=hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()[:24]
    return body
