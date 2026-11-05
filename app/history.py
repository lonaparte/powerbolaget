"""Bounded, persisted teaching archive. Rows are compact arrays with explicit field/unit metadata.

Hourly device energy is integrated actual energy; other object values are end-of-hour snapshots.
Daily energy fields sum and state fields average snapshots. Minute recording is opt-in (8 objects).
Retention is explicit in every export; it is not an unlimited telemetry database.
"""
import csv
import io
from collections import deque

FIELDS={
 'global': [('requested_mwh','MWh'),('served_mwh','MWh'),('wind_mwh','MWh'),('oil_mwh','MWh'),('loss_mwh','MWh')],
 'device': [('requested_mwh','MWh'),('served_mwh','MWh')],
 'bus': [('voltage_pu','pu'),('angle_deg','degree')],
 'branch': [('p_mw','MW'),('q_mvar','Mvar'),('loss_mw','MW'),('loading','pu')],
 'turbine': [('energy_mwh','MWh'),('q_mvar','Mvar')],
 'storage': [('p_mw','MW'),('q_mvar','Mvar'),('soc','pu'),('soh','pu')],
 'oil': [('p_mw','MW'),('q_mvar','Mvar'),('fuel_mwh','MWh thermal')],
 'firm': [('cash_sek','SEK'),('debt_sek','SEK'),('staff','person'),('production_day','product unit')],
 'zone': [('residents','person'),('visitors','person'),('unemployed','person')],
}
MINUTE_FIELDS=[('p_mw','MW'),('q_mvar','Mvar'),('voltage_pu','pu'),('loading','pu'),('soc','pu')]


class Archive:
    def __init__(self,state=None):
        s=state or {}
        self.kinds=s.get('kinds',{})
        self.hours={k:deque(v,maxlen=168) for k,v in s.get('hours',{}).items()}
        self.days={k:deque(v,maxlen=30) for k,v in s.get('days',{}).items()}
        self.minutes={k:deque(v,maxlen=1440) for k,v in s.get('minutes',{}).items()}
        self.selected=s.get('selected',[])
        self.waveforms=deque(s.get('waveforms',[]),maxlen=8)
        self.day_acc=s.get('day_acc',{})

    def state(self):
        return dict(kinds=self.kinds,hours={k:list(v) for k,v in self.hours.items()},
                    days={k:list(v) for k,v in self.days.items()},minutes={k:list(v) for k,v in self.minutes.items()},
                    selected=self.selected,waveforms=list(self.waveforms),day_acc=self.day_acc)

    def hour(self,key,kind,t,values):
        self.kinds[key]=kind
        rows=self.hours.setdefault(key,deque(maxlen=168))
        if rows and rows[-1][0]>=t:
            return
        rows.append([t]+[round(float(v),6) for v in values])
        accum=self.day_acc.setdefault(key,dict(t=t-t%1440,n=0,values=[0.]*len(values)))
        accum['n']+=1
        accum['values']=[a+b for a,b in zip(accum['values'],values)]
        if (t+60)%1440==0:
            energy=[unit.startswith('MWh') and kind not in ('oil',) for name,unit in FIELDS[kind]]
            day=[value if integral else value/accum['n'] for value,integral in zip(accum['values'],energy)]
            self.days.setdefault(key,deque(maxlen=30)).append([accum['t']]+day)
            del self.day_acc[key]

    def record(self,world,key,on):
        if key not in objects(world):
            raise ValueError('Choose an electrical device, branch, bus, storage unit or turbine.')
        if on and key not in self.selected:
            if len(self.selected)>=8:
                raise ValueError('Up to 8 objects can record minute data at once.')
            self.selected.append(key)
        elif not on and key in self.selected:
            self.selected.remove(key)

    def minute(self,world,t):
        f=world.flows or {}
        for key in self.selected:
            p=q=loading=soc=0.
            bid=key
            g=world.grid
            if key in world.devices:
                d=world.devices[key];p=d['p']*d['served'];q=d['q']*d['served'];bid=d['bus']
            elif key in g['branches']:
                x=f.get('branches',{}).get(key,(0.,0.,0.,0.,0.));p,q=x[:2]
                loading=f.get('loading',{}).get(key,0.);bid=g['branches'][key]['b']
            elif key in g['turbines']:
                x=g['turbines'][key];p=x['p'];q=x.get('q',0.);bid=x['bus_lv']
            elif key in g['storage'] or key in g.get('oil',{}):
                x=g['storage'].get(key) or g['oil'][key]
                p=x['p'];q=x.get('q',0.);soc=x.get('soc',0.);bid=x['bus']
            rows=self.minutes.setdefault(key,deque(maxlen=1440))
            if not rows or t>rows[-1][0]:
                rows.append([t]+[round(v,6) for v in (p,q,f.get('vm',{}).get(bid,0.),loading,soc)])


def objects(world):
    return set(world.devices)|set(world.grid['buses'])|set(world.grid['branches'])|set(world.grid['turbines'])|set(world.grid['storage'])|set(world.grid.get('oil',{}))


def capture_hour(world,start):
    a,g,f=world.archive,world.grid,world.flows or {}
    acc=world.acc
    a.hour('global','global',start,[acc['load_req'],acc['load_srv'],acc['wind'],acc.get('oil',0.),acc['losses']])
    for key,d in world.devices.items():
        a.hour(key,'device',start,[d['e_req'],d['e_srv']])
    for key in g['buses']:
        a.hour(key,'bus',start,[f.get('vm',{}).get(key,0.),f.get('va',{}).get(key,0.)])
    for key in g['branches']:
        x=f.get('branches',{}).get(key,(0.,0.,0.,0.,0.))
        a.hour(key,'branch',start,[x[0],x[1],x[0]+x[2],f.get('loading',{}).get(key,0.)])
    for key,tb in g['turbines'].items():
        a.hour(key,'turbine',start,[tb['energy_mwh'],tb.get('q',0.)])
    for key,s in g['storage'].items():
        a.hour(key,'storage',start,[s['p'],s.get('q',0.),s['soc'],s.get('soh',1.)])
    for key,s in g.get('oil',{}).items():
        a.hour(key,'oil',start,[s['p'],s.get('q',0.),s['fuel_mwh']])
    for key,firm in world.firms.items():
        a.hour(key,'firm',start,[world.ledger.balance('firm:'+key),firm.get('credit',{}).get('debt',0.),firm['staff'],firm['today']['produced']])
    st=world.society_stats
    for z in world.zones:
        key=z['id']
        # Zone IDs are also electrical bus IDs: namespace social summaries explicitly.
        a.hour('zone:'+key,'zone',start,[st['zone_residents'].get(key,0),st['zone_tourists'].get(key,0),st['zone_unemployed'].get(key,0)])


def export(world,key='global',resolution='hour',start=0,end=None,event_id=None):
    a=world.archive
    if resolution=='event':
        data=[e for e in a.waveforms if (not event_id or e['id']==event_id) and start<=e['t'] and (end is None or e['t']<=end)]
        if key!='global':
            data=[dict(e,fields=e.get('object_fields',[]),samples=e['object_samples'][key],object=key)
                  for e in data if key in e.get('object_samples',{})]
        return dict(schema='powerbolaget.history/1',resolution='event',events=data,clock_unit='minute',waveform_time_unit='second')
    if resolution not in ('hour','day','minute'):
        raise ValueError('Resolution must be hour, day, minute or event.')
    source={'hour':a.hours,'day':a.days,'minute':a.minutes}[resolution]
    rows=[r for r in source.get(key,[]) if r[0]>=start and (end is None or r[0]<=end)]
    fields=MINUTE_FIELDS if resolution=='minute' else FIELDS.get(a.kinds.get(key),[])
    return dict(schema='powerbolaget.history/1',object=key,resolution=resolution,clock_unit='minute',
                fields=[['t','minute']]+fields,rows=rows,
                statistic='integrated energy; end-of-hour states' if resolution=='hour' else 'daily energy sums; mean hourly states' if resolution=='day' else 'end-of-minute snapshot',
                retention=dict(hours=168,days=30,minutes=1440,events=8),recording=key in a.selected)


def as_csv(data):
    out=io.StringIO(newline='')
    writer=csv.writer(out)
    if data['resolution']=='event':
        fields=data['events'][0].get('fields',[]) if data['events'] else []
        writer.writerow(['event','t [minute]']+[f'{name} [{unit}]' for name,unit in fields])
        for e in data['events']:
            for sample in e.get('samples',[]):
                writer.writerow([e['id'],e['t']]+sample)
    else:
        writer.writerow([f'{name} [{unit}]' for name,unit in data['fields']])
        writer.writerows(data['rows'])
    return out.getvalue()
