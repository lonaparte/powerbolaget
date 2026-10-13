"""Continuous Baltic coastal climate function with smooth, seeded weather anomalies.

The monthly NASA POWER 2001-2020 climatology only calibrates annual Fourier
coefficients. No historical day is replayed. All meteorology is evaluated at
continuous simulation time (days); fixed CET avoids daylight-saving jumps.
"""
import json
import random
from pathlib import Path
from math import sin, cos, tan, acos, pi, sqrt, exp, floor, log
from datetime import datetime, timedelta
from functools import lru_cache

DATA=json.loads(Path(__file__).with_name('baltic-coastal-climatology.json').read_text(encoding='utf-8-sig'))
MONTHS='JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
LAT=55.6761; LON=12.5683


def coefficients(key):
    values=[DATA['properties']['parameter'][key][m] for m in MONTHS]
    if key=='ALLSKY_SFC_SW_DWN': values=[log(v) for v in values]
    return (sum(values)/12,[(sum(v*cos(2*pi*k*(i+.5)/12) for i,v in enumerate(values))/6,
                            sum(v*sin(2*pi*k*(i+.5)/12) for i,v in enumerate(values))/6) for k in range(1,4)])

COEFFICIENTS={key:coefficients(key) for key in ('WS10M','T2M','ALLSKY_SFC_SW_DWN')}


def normal(key,day):
    """Smooth periodic seasonal function; three annual harmonics, not a lookup."""
    mean,terms=COEFFICIENTS[key]
    value=mean+sum(a*cos(2*pi*k*day/365)+b*sin(2*pi*k*day/365) for k,(a,b) in enumerate(terms,1))
    return exp(value) if key=='ALLSKY_SFC_SW_DWN' else value


@lru_cache(maxsize=30000)
def day_noise(seed,day,channel=0):
    # Correlated knots; a seed is fixed per scenario, never drawn on page refresh.
    weights=[.72**k for k in range(16)]
    return sum(w*random.Random(seed*1000003+(day-k)*9176+channel*15485863).gauss(0,1) for k,w in enumerate(weights))/sqrt(sum(w*w for w in weights))


def smooth_noise(seed,time,channel=0,scale=1.):
    point=time/scale;i=floor(point);f=point-i
    blend=f*f*f*(10+f*(-15+6*f)) # Quintic interpolation: value and first two derivatives match at knots.
    return day_noise(seed,i,channel)*(1-blend)+day_noise(seed,i+1,channel)*blend


def geometry(time):
    declination=23.44*pi/180*sin(2*pi*(time+1-81)/365)
    lat=LAT*pi/180; a=sin(lat)*sin(declination); b=cos(lat)*cos(declination)
    angle=acos(max(-1,min(1,-tan(lat)*tan(declination))))
    e=2*pi*(time+1-81)/365
    equation=9.87*sin(2*e)-7.53*cos(e)-1.5*sin(e)
    noon=12+(15-LON)/15-equation/60
    # Exact daily integral of the positive solar-elevation shape, in hours.
    area=24/pi*(a*angle+b*sin(angle))
    elevation=max(0,a+b*cos(((time%1)*24-noon)*pi/12))
    return dict(daylight_hours=24*angle/pi,sunrise_hour=noon-12*angle/pi,
                sunset_hour=noon+12*angle/pi,shape=elevation,area=area)


def instant(seed,time,mode='normal'):
    hour=(time%1)*24
    slow=smooth_noise(seed,time,0)
    gust=smooth_noise(seed,time,4,1/12)
    cloud_noise=.4*slow+.82*smooth_noise(seed,time,1)+.18*smooth_noise(seed,time,5,1/6)
    # A positive wind distribution around the seasonal function, with smooth weather and gusts.
    wind10=max(.2,normal('WS10M',time)*exp(.26*slow-.26**2/2)+.3*sin((hour-8)*pi/12)+.22*gust)
    # These are explicit operator-selected stress tests, separate from normal climate.
    if mode=='calm':wind10*=.24
    if mode=='storm':wind10+=17.
    if mode=='variable':wind10=max(.2,wind10+2.5*sin(2*pi*time*6))
    solar=geometry(time)
    cloud=max(.05,min(.98,.65+.18*cloud_noise))
    temp=normal('T2M',time)+2.5*smooth_noise(seed,time,2)+2*(1-.5*cloud)*sin((hour-9)*pi/12)
    direction=(240+40*sin(time*2*pi/8+seed*.1)+25*slow+5*sin(hour*pi/12))%360
    wave=max(.25,.35+.025*wind10**2+.15*smooth_noise(seed,time,3))
    irradiance=min(1100,normal('ALLSKY_SFC_SW_DWN',time)*exp(-.38*cloud_noise-.38**2/2)*1000*solar['shape']/solar['area'])
    return dict(speed_ms=wind10*9**.11,wind_10m_ms=wind10,direction_deg=direction,temperature_c=temp,
                density=101325/(287.05*(temp+273.15)),cloud_fraction=cloud,wave_height_m=wave,
                irradiance_w_m2=irradiance,daylight_hours=solar['daylight_hours'],
                sunrise_hour=solar['sunrise_hour'],sunset_hour=solar['sunset_hour'])


@lru_cache(maxsize=3000)
def solar_day(seed,day):
    # A daily aggregate, never an input to instantaneous weather. 15-minute quadrature.
    return sum(instant(seed,day+i/96)['irradiance_w_m2'] for i in range(96))*.25/1000


def conditions(seed,step,mode='normal'):
    time=step/96
    return dict(**instant(seed,time,mode),daily_solar_kwh_m2=solar_day(seed,floor(time)),
                location='A Baltic coastal city',latitude=LAT,longitude=LON,time_basis='CET / UTC+1',
                source='Baltic coastal seasonal function + smooth random disturbances; NASA POWER 2001–2020 calibration',
                baseline_period='2001–2020',test_override=mode!='normal')


def reference():
    """Constants the browser needs to evaluate the outlook itself (web/climate.js)."""
    return dict(latitude=LAT,longitude=LON,coefficients={k:[mean,[list(t) for t in terms]] for k,(mean,terms) in COEFFICIENTS.items()})


def outlook(seed,step):
    """Seven-day outlook in normal climate. The browser computes the same values; this is the reference."""
    days=[]
    for day in range(step//96,step//96+7):
        hours=[conditions(seed,day*96+h*4) for h in range(24)]
        days.append(dict(date=(datetime(2030,1,1)+timedelta(days=day)).strftime('%m-%d'),
            wind_ms=sum(w['wind_10m_ms'] for w in hours)/24,temperature_c=sum(w['temperature_c'] for w in hours)/24,
            solar_kwh_m2=hours[0]['daily_solar_kwh_m2'],daylight_hours=hours[0]['daylight_hours']))
    return days
