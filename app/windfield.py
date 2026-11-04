"""The island's wind field: an observed long-term mean at every place, varied smoothly in space and time.

- mean100(x, y): the Global Wind Atlas mean wind speed at 100 m (app/island-wind.json, derived by
  tools/wind_atlas.py), bilinear between 1 km cells. It carries the real pattern: about 7.3 m/s inland,
  8.5-9.2 m/s on exposed coasts and 9.2 m/s at sea.
- at_height(x, y, hub): that mean at hub height, by a power law whose exponent follows the land cover.
- variation(seed, x, y, t): a smooth random factor, about 5 % (one standard deviation), correlated over
  roughly 12 km and 3 hours, so neighbouring sites differ a little and the pattern changes slowly.

At a given moment the wind at a place is mean x the island's anomaly (weather.instant's wind_ratio,
whose long-term mean is 1) x variation. The client draws the same field with the same functions.
"""
import json
from functools import lru_cache
from math import floor
from pathlib import Path

from . import land

FIELD = json.loads(Path(__file__).with_name('island-wind.json').read_text(encoding='utf-8'))
# Wind shear exponent by land cover (smooth sea to rough forest and town; typical textbook values).
SHEAR = {'~': .10, 'b': .12, 'a': .14, 'w': .15, 'f': .16, 'q': .16, 'r': .18, 'v': .20, 'F': .24, 'T': .26}
SPACE_KM, TIME_H, AMPLITUDE = 12., 3., .09


def mean100(x, y):
    f = FIELD
    nx, ny, v = f['nx'], f['ny'], f['values']
    gx = min(max((x-f['x0'])/f['cell_km']-.5, 0.), nx-1.0001)
    gy = min(max((y-f['y0'])/f['cell_km']-.5, 0.), ny-1.0001)
    i, j = int(gx), int(gy)
    fx, fy = gx-i, gy-j
    k = j*nx+i
    return (v[k]*(1-fx)+v[k+1]*fx)*(1-fy)+(v[k+nx]*(1-fx)+v[k+nx+1]*fx)*fy


@lru_cache(maxsize=8192)
def at_height(x, y, hub_m):
    return mean100(x, y)*(hub_m/100)**SHEAR.get(land.land_class(x, y), .16)


def _hash(ix, iy, iz, seed):
    h = (ix*374761393+iy*668265263+iz*1274126177+seed*2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13))*1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h/4294967296*2-1


def _smooth(f):
    return f*f*f*(10+f*(-15+6*f))


def value_noise(seed, x, y, z):
    """Smooth 3-D value noise in [-1, 1] (same algorithm as PB.windNoise in the client)."""
    ix, iy, iz = floor(x), floor(y), floor(z)
    fx, fy, fz = _smooth(x-ix), _smooth(y-iy), _smooth(z-iz)
    total = 0.
    for dz, wz in ((0, 1-fz), (1, fz)):
        for dy, wy in ((0, 1-fy), (1, fy)):
            for dx, wx in ((0, 1-fx), (1, fx)):
                total += wx*wy*wz*_hash(ix+dx, iy+dy, iz+dz, seed)
    return total


def variation(seed, x, y, time_days):
    return 1+AMPLITUDE*value_noise(seed, x/SPACE_KM, y/SPACE_KM, time_days*24/TIME_H)


def hub_speed(w, hub_m, x, y, time_days, seed):
    """Wind speed at hub height at a place and moment (before wakes)."""
    return max(0., at_height(x, y, hub_m)*w['wind_ratio']*variation(seed, x, y, time_days))
