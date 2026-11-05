"""Aggregated RMS source dynamics coupled to the AC algebraic solver.

Classical swing/virtual-swing equation, first-order droop governor and voltage regulator.
Power uses the unit's MVA base, frequency deviations Hz, angles radians and time seconds.
RK4 integrates differential states; each event step obtains electrical P/Q/V from OpenDSS.
This is a positive-sequence, averaged teaching model, with no electromagnetic transients.
"""
from math import pi


def derivative(y,pe,qe,voltage,pref,c):
    angle,df,pm,e=y
    damping=c.get('damping',1.)
    target=max(c.get('pmin',-1.),min(1.,pref-df/(50*c.get('droop',.05))))
    vref=c.get('voltage_ref',1.02)
    return [2*pi*df,50/(2*c['inertia'])*(pm-pe-damping*df/50),
            (target-pm)/c['governor_s'],
            (vref+c.get('voltage_gain',.5)*(vref-voltage)-.03*qe-e)/c.get('voltage_s',.10)]


def advance(y,pe,qe,voltage,pref,config,dt):
    k1=derivative(y,pe,qe,voltage,pref,config)
    k2=derivative([a+dt*b/2 for a,b in zip(y,k1)],pe,qe,voltage,pref,config)
    k3=derivative([a+dt*b/2 for a,b in zip(y,k2)],pe,qe,voltage,pref,config)
    k4=derivative([a+dt*b for a,b in zip(y,k3)],pe,qe,voltage,pref,config)
    result=[a+dt*(b+2*c+2*d+e)/6 for a,b,c,d,e in zip(y,k1,k2,k3,k4)]
    result[3]=max(.05,min(1.15,result[3]))
    return result
