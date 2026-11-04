"""Continuous island weather: seasonal climatology plus smooth, seeded anomalies.

The NASA POWER 2001-2025 monthly climatology at 57.5 N, 18.5 E (app/island-climatology.json) only
calibrates annual Fourier coefficients; no historical day is replayed. Every quantity is a continuous
function of simulation time in days, so minute sampling never shows an artificial step. Forecasts are
the same functions plus an error that grows with lead time: a forecast is not the future.
"""
import json
import random
from functools import lru_cache
from math import acos, cos, exp, floor, log, pi, sin, sqrt, tan
from pathlib import Path

CLIMATE = json.loads(Path(__file__).with_name('island-climatology.json').read_text(encoding='utf-8'))
MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
LAT, LON = CLIMATE['point']['latitude'], CLIMATE['point']['longitude']
SOURCE = f"NASA POWER climatology {CLIMATE['period'].split('(')[-1].rstrip(')')} at {LAT} N, {LON} E (calibration only)"
TIME_BASIS = 'fixed local time UTC+1, no daylight saving'


def _coefficients(key):
    values = [CLIMATE['parameter'][key][m] for m in MONTHS]
    if key == 'ALLSKY_SFC_SW_DWN':
        values = [log(v) for v in values]
    return (sum(values)/12, [(sum(v*cos(2*pi*k*(i+.5)/12) for i, v in enumerate(values))/6,
                              sum(v*sin(2*pi*k*(i+.5)/12) for i, v in enumerate(values))/6) for k in range(1, 4)])


COEFFICIENTS = {key: _coefficients(key) for key in ('WS10M', 'WS50M', 'T2M', 'ALLSKY_SFC_SW_DWN', 'RH2M')}


def normal(key, day):
    """Smooth seasonal function with three annual harmonics."""
    mean, terms = COEFFICIENTS[key]
    value = mean+sum(a*cos(2*pi*k*day/365)+b*sin(2*pi*k*day/365) for k, (a, b) in enumerate(terms, 1))
    return exp(value) if key == 'ALLSKY_SFC_SW_DWN' else value


def shear_exponent(day):
    """Power-law wind shear fitted to the 10 m and 50 m climatology of the season."""
    return log(normal('WS50M', day)/normal('WS10M', day))/log(5)


@lru_cache(maxsize=60000)
def _knot(seed, index, channel):
    weights = [.72**k for k in range(16)]
    total = sum(w*random.Random(seed*1000003+(index-k)*9176+channel*15485863).gauss(0, 1) for k, w in enumerate(weights))
    return total/sqrt(sum(w*w for w in weights))


def noise(seed, time, channel, scale=1.):
    """Correlated standard-normal noise; quintic blending keeps value and two derivatives continuous."""
    point = time/scale
    i = floor(point)
    f = point-i
    blend = f*f*f*(10+f*(-15+6*f))
    return _knot(seed, i, channel)*(1-blend)+_knot(seed, i+1, channel)*blend


def sun(time):
    declination = 23.44*pi/180*sin(2*pi*(time+1-81)/365)
    lat = LAT*pi/180
    a, b = sin(lat)*sin(declination), cos(lat)*cos(declination)
    angle = acos(max(-1, min(1, -tan(lat)*tan(declination))))
    e = 2*pi*(time+1-81)/365
    noon = 12+(15-LON)/15-(9.87*sin(2*e)-7.53*cos(e)-1.5*sin(e))/60
    area = 24/pi*(a*angle+b*sin(angle))
    elevation = max(0, a+b*cos(((time % 1)*24-noon)*pi/12))
    return dict(daylight_hours=24*angle/pi, sunrise_hour=noon-12*angle/pi, sunset_hour=noon+12*angle/pi,
                shape=elevation, area=area)


def instant(seed, time):
    """Island-average weather at `time` (days since the era began)."""
    hour = (time % 1)*24
    slow = noise(seed, time, 0)
    gust = noise(seed, time, 4, 1/12)
    turbulence = noise(seed, time, 6, 1/144)
    cloud_noise = .4*slow+.82*noise(seed, time, 1)+.18*noise(seed, time, 5, 1/6)
    wind10 = max(.2, normal('WS10M', time)*exp(.3*slow-.3**2/2)+.3*sin((hour-8)*pi/12)+.25*gust+.12*turbulence)
    s = sun(time)
    cloud = max(.05, min(.98, .65+.18*cloud_noise))
    temp = normal('T2M', time)+2.8*noise(seed, time, 2)+2*(1-.5*cloud)*sin((hour-9)*pi/12)
    rh = max(35, min(100, normal('RH2M', time)+6*noise(seed, time, 7)+8*(cloud-.65)))
    direction = (235+45*noise(seed, time, 8, 3)+20*slow) % 360
    irradiance = min(1000, normal('ALLSKY_SFC_SW_DWN', time)*exp(-.38*cloud_noise-.38**2/2)*1000*s['shape']/max(s['area'], 1e-6))
    # Convective storms: warm, humid, cloudy summer afternoons. Icing: near-freezing fog or drizzle.
    thunder = max(0., min(1., (temp-17)/8))*max(0., min(1., (cloud-.55)/.3))*max(0., sin((hour-11)*pi/10)) if 11 < hour < 21 else 0.
    icing = max(0., 1-abs(temp+1)/3)*max(0., (rh-88)/12)
    return dict(wind_10m_ms=wind10, direction_deg=direction, shear=shear_exponent(time), temperature_c=temp,
                humidity_pct=rh, cloud_fraction=cloud, irradiance_w_m2=irradiance, density=101325/(287.05*(temp+273.15)),
                thunder_risk=thunder, icing_risk=icing, daylight_hours=s['daylight_hours'],
                sunrise_hour=s['sunrise_hour'], sunset_hour=s['sunset_hour'])


def hub_speed(w, hub_m, x_km, y_km, time, exposure=1.):
    """Wind at hub height and site: shear, site exposure and a slowly travelling spatial pattern."""
    d = w['direction_deg']*pi/180
    along = x_km*sin(d)+y_km*cos(d)
    pattern = 1+.035*sin(2*pi*(along/23+time*24/5))+.02*sin(2*pi*((x_km-y_km)/31-time*24/9))
    return max(0., w['wind_10m_ms']*(hub_m/10)**w['shear']*exposure*pattern)


def forecast(seed, issued, time):
    """What a forecast issued at `issued` says about `time`; the error grows with lead time."""
    lead = max(0., time-issued)
    w = instant(seed, time)
    spread = min(1., sqrt(lead/3))
    w['wind_10m_ms'] = max(.2, w['wind_10m_ms']*(1+.18*spread*noise(seed+17, issued, 9, .5)))
    w['temperature_c'] += 1.8*spread*noise(seed+29, issued, 10, .5)
    return w


@lru_cache(maxsize=4000)
def outlook_day(seed, issued_day, day):
    hours = [forecast(seed, issued_day, day+h/24) for h in range(24)]
    return dict(day=day, wind_10m_ms=sum(w['wind_10m_ms'] for w in hours)/24,
                temperature_c=sum(w['temperature_c'] for w in hours)/24,
                min_c=min(w['temperature_c'] for w in hours), max_c=max(w['temperature_c'] for w in hours),
                solar_kwh_m2=sum(w['irradiance_w_m2'] for w in hours)/1000,
                storm_risk=max(0., min(1., (max(w['wind_10m_ms'] for w in hours)-12)/8)))
