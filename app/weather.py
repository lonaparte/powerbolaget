"""Continuous island weather: seasonal climatology plus smooth, seeded anomalies.

The NASA POWER 2001-2025 monthly climatology at 57.5 N, 18.5 E (app/island-climatology.json) sets the
seasonal means; no historical day is replayed. The spread and persistence of the anomalies were fitted
to NASA POWER hourly data at the same point (2020-2024): wind speeds follow a Weibull distribution with
the observed seasonal shape, wind directions follow the observed wind rose, and both persist as long as
observed. Daily temperature ranges follow the Visby station averages. Every quantity is a continuous
function of simulation time in days, so minute sampling never shows an artificial step. Forecasts are
the same functions plus an error that grows with lead time: a forecast is not the future.
"""
import json
import random
from functools import lru_cache
from math import acos, asin, atan2, cos, degrees, erf, exp, floor, gamma, log, pi, radians, sin, sqrt, tan
from pathlib import Path

CLIMATE = json.loads(Path(__file__).with_name('island-climatology.json').read_text(encoding='utf-8'))
MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
LAT, LON = CLIMATE['point']['latitude'], CLIMATE['point']['longitude']
SOURCE = f"NASA POWER climatology {CLIMATE['period'].split('(')[-1].rstrip(')')} at {LAT} N, {LON} E (calibration only)"
TIME_BASIS = 'fixed local time UTC+1, no daylight saving'


# Visby, mean daily maximum minus mean daily minimum by month, deg C (https://www.weatherandclimate.eu/climate/02590).
# The NASA grid cell is mostly sea and its daily range (2-4.5 C) understates the island's.
VISBY_DAILY_RANGE = [3.9, 4.3, 6.1, 8.6, 9.5, 8.7, 8.2, 7.8, 6.9, 5.3, 3.8, 3.7]
# Fitted to NASA POWER hourly WS10M/WD10M at 57.5 N, 18.5 E, 2020-2024 (assumption-free summary statistics):
# Weibull shape about 2.9 in winter and 2.3 in summer (calms below 2 m/s 8 % of hours); wind rose as a
# projected normal blowing from 230 degrees (SW 25 %, W 17 %, S 15 %, other directions 8-10 %).
WEIBULL_K = (2.62, .30)
ROSE_FROM, ROSE_MEAN, ROSE_ALONG = 230., .55, 1.2


def _fit(values):
    return (sum(values)/12, [(sum(v*cos(2*pi*k*(i+.5)/12) for i, v in enumerate(values))/6,
                              sum(v*sin(2*pi*k*(i+.5)/12) for i, v in enumerate(values))/6) for k in range(1, 4)])


def _coefficients(key):
    values = [CLIMATE['parameter'][key][m] for m in MONTHS]
    return _fit([log(v) for v in values] if key == 'ALLSKY_SFC_SW_DWN' else values)


COEFFICIENTS = {key: _coefficients(key) for key in ('WS10M', 'WS50M', 'T2M', 'ALLSKY_SFC_SW_DWN', 'RH2M')}
COEFFICIENTS['DAILY_RANGE'] = _fit(VISBY_DAILY_RANGE)


def normal(key, day):
    """Smooth seasonal function with three annual harmonics."""
    mean, terms = COEFFICIENTS[key]
    value = mean+sum(a*cos(2*pi*k*day/365)+b*sin(2*pi*k*day/365) for k, (a, b) in enumerate(terms, 1))
    return exp(value) if key == 'ALLSKY_SFC_SW_DWN' else value


def weibull_speed(mean, z, k):
    """Map a standard-normal anomaly to a Weibull-distributed speed with the given mean and shape."""
    u = min(1-1e-12, .5*(1+erf(z/sqrt(2))))
    return mean/gamma(1+1/k)*(-log(1-u))**(1/k)


def shear_exponent(day):
    """Power-law wind shear fitted to the 10 m and 50 m climatology of the season."""
    return log(normal('WS50M', day)/normal('WS10M', day))/log(5)


@lru_cache(maxsize=60000)
def _knot(seed, index, channel):
    weights = [.72**k for k in range(16)]
    total = sum(w*random.Random(seed*1000003+(index-k)*9176+channel*15485863).gauss(0, 1) for k, w in enumerate(weights))
    return total/sqrt(sum(w*w for w in weights))


def noise(seed, time, channel, scale=1.):
    """Correlated standard-normal noise; quintic blending keeps value and two derivatives continuous.
    Adjacent knots correlate at 0.72, so the correlation time is about three knot spacings."""
    point = time/scale
    i = floor(point)
    f = point-i
    blend = f*f*f*(10+f*(-15+6*f))
    spread = sqrt((1-blend)**2+blend**2+2*blend*(1-blend)*.72)   # keep unit variance between knots
    return (_knot(seed, i, channel)*(1-blend)+_knot(seed, i+1, channel)*blend)/spread


def sun(time):
    """Solar position at the island in local time UTC+1: day length changes from about 6.5 h at midwinter
    to 18 h at midsummer, and in June the sun stays less than 10 degrees below the horizon all night."""
    declination = 23.44*pi/180*sin(2*pi*(time+1-81)/365)
    lat = LAT*pi/180
    a, b = sin(lat)*sin(declination), cos(lat)*cos(declination)
    e = 2*pi*(time+1-81)/365
    noon = 12+(15-LON)/15-(9.87*sin(2*e)-7.53*cos(e)-1.5*sin(e))/60
    geometric = acos(max(-1, min(1, -a/b)))
    visible = acos(max(-1, min(1, (sin(radians(-.833))-a)/b)))   # upper limb on the horizon, with refraction
    area = 24/pi*(a*geometric+b*sin(geometric))
    height = a+b*cos(((time % 1)*24-noon)*pi/12)
    return dict(daylight_hours=24*visible/pi, sunrise_hour=noon-12*visible/pi, sunset_hour=noon+12*visible/pi,
                noon_hour=noon, elevation_deg=degrees(asin(max(-1, min(1, height)))), shape=max(0, height), area=area)


def daily_cycle(hour, sunrise, peak):
    """-1 at sunrise, +1 at the afternoon peak, smooth in between and through the night."""
    if sunrise <= hour <= peak:
        return -cos(pi*(hour-sunrise)/(peak-sunrise))
    since = hour-peak if hour > peak else hour+24-peak
    return cos(pi*since/(sunrise+24-peak))


def instant(seed, time):
    """Island-average weather at `time` (days since the era began)."""
    hour = (time % 1)*24
    # Wind anomaly with 6-hour knots: correlation about 0.7 after 6 h and 0.25 after a day, as observed.
    synoptic = noise(seed, time, 11, .25)
    gust = noise(seed, time, 4, 1/12)
    turbulence = noise(seed, time, 6, 1/144)
    cloud_noise = .4*synoptic+.82*noise(seed, time, 1)+.18*noise(seed, time, 5, 1/6)
    summer = .5-.5*cos(2*pi*(time-15)/365)
    k = WEIBULL_K[0]+WEIBULL_K[1]*cos(2*pi*(time-15)/365)
    calm10 = weibull_speed(normal('WS10M', time), synoptic, k)
    wind10 = max(.2, calm10+.25*(.4+.6*summer)*sin((hour-8)*pi/12)+.15*gust+.12*turbulence)
    # The island's anomaly at turbine height, with a long-term mean of 1: the 50 m seasonal cycle times the
    # same synoptic and gust variation (no 10 m afternoon maximum, which fades aloft). windfield.py
    # multiplies it with each place's observed mean.
    ratio = normal('WS50M', time)/COEFFICIENTS['WS50M'][0]*max(.03, calm10+.15*gust+.12*turbulence)/normal('WS10M', time)
    s = sun(time)
    cloud = max(.05, min(.98, .65+.18*cloud_noise))
    # Daily cycle: coldest at sunrise, warmest about 2.5 h after solar noon; clear days swing more.
    swing = normal('DAILY_RANGE', time)*(1.35-.7*cloud)/.895
    temp = normal('T2M', time)+2.8*noise(seed, time, 2)+swing/2*daily_cycle(hour, s['sunrise_hour'], s['noon_hour']+2.5)
    rh = max(35, min(100, normal('RH2M', time)+6*noise(seed, time, 7)+8*(cloud-.65)))
    # Direction from a slowly turning wind vector: the mean points from the prevailing south-west.
    along, across = noise(seed, time, 12, .5), noise(seed, time, 13, .5)
    t0 = radians(ROSE_FROM)
    vx = (ROSE_MEAN+ROSE_ALONG*along)*sin(t0)+across*cos(t0)
    vy = (ROSE_MEAN+ROSE_ALONG*along)*cos(t0)-across*sin(t0)
    direction = degrees(atan2(vx, vy)) % 360
    irradiance = min(1000, normal('ALLSKY_SFC_SW_DWN', time)*exp(-.38*cloud_noise-.38**2/2)*1000*s['shape']/max(s['area'], 1e-6))
    # Convective storms: warm, humid, cloudy summer afternoons. Icing: near-freezing fog or drizzle.
    thunder = max(0., min(1., (temp-17)/8))*max(0., min(1., (cloud-.55)/.3))*max(0., sin((hour-11)*pi/10)) if 11 < hour < 21 else 0.
    icing = max(0., 1-abs(temp+1)/3)*max(0., (rh-88)/12)
    return dict(wind_10m_ms=wind10, wind_ratio=ratio, direction_deg=direction, shear=shear_exponent(time), temperature_c=temp,
                humidity_pct=rh, cloud_fraction=cloud, irradiance_w_m2=irradiance, density=101325/(287.05*(temp+273.15)),
                thunder_risk=thunder, icing_risk=icing, daylight_hours=s['daylight_hours'],
                sunrise_hour=s['sunrise_hour'], sunset_hour=s['sunset_hour'], sun_elevation_deg=s['elevation_deg'])


def snow_cover(seed, time):
    """Share of the island under snow, from the mean temperature of the past three days: snow builds up in
    a cold spell and survives a mild afternoon, instead of following each hour's temperature."""
    mean = sum(instant(seed, time-k/4)['temperature_c'] for k in range(12))/12
    return max(0., min(1., (.5-mean)/2))


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
