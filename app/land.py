"""Land: the island as 0.5 km parcels with land use, zone membership and people (spec 9.2).

Land use is world data, not decoration: the map draws it, turbine siting obeys it (no turbines in
towns, villages, quarries, nature reserves or on the shore) and the wind shear above it depends on it. It is
derived deterministically from the island outline, the zones' towns and fixed site lists, so every
server and every save sees the same land.
"""
from functools import lru_cache
from math import floor, hypot, sqrt
from .island import ISLET, OUTLINE, ZONES, coast_distance, inside

CELL = .5
X0, Y0, NX, NY = -4.0, -2.0, 176, 252
CLASSES = {
    '~': ('sea', 0.), 'b': ('shore', .1), 'T': ('town', 40.), 'v': ('village and houses', 6.), 'f': ('farmland', .5),
    'F': ('forest', .15), 'a': ('limestone heath (alvar)', .1), 'w': ('wetland', .05), 'q': ('limestone quarry', 0.),
    'r': ('nature reserve', .05),
}
NO_TURBINES = {'~': 'at sea', 'b': 'on the shore', 'T': 'in a town', 'v': 'among homes', 'q': 'in an active quarry',
               'r': 'in a nature reserve'}
QUARRIES = [(46.2, 90.6, .9), (17.4, 17.2, .6), (34.0, 80.0, .4)]
RESERVES = [(74.0, 117.0, 2.8), (8.6, 4.2, 1.4), (31.5, 50.0, 2.2), (36.5, 100.0, 1.8), (57.5, 60.5, .9)]


def _hash(ix, iy):
    h = (ix*374761393+iy*668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13))*1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFFFF)/4294967296


def _noise(x, y):
    ix, iy = floor(x), floor(y)
    fx, fy = x-ix, y-iy
    sx, sy = fx*fx*(3-2*fx), fy*fy*(3-2*fy)
    a, b, c, d = _hash(ix, iy), _hash(ix+1, iy), _hash(ix, iy+1), _hash(ix+1, iy+1)
    top = a+(b-a)*sx
    return top+((c+(d-c)*sx)-top)*sy


def cell_of(x, y):
    i, j = int((x-X0)//CELL), int((y-Y0)//CELL)
    return (i, j) if 0 <= i < NX and 0 <= j < NY else None


def center(i, j):
    return X0+(i+.5)*CELL, Y0+(j+.5)*CELL


@lru_cache(maxsize=1)
def grid():
    """(classes as a string, zone index per cell as a list), row by row from the south-west corner."""
    zones = [(z[0], z[2], z[3], z[10], z[4]) for z in ZONES]
    islet = [inside(x, y, ISLET) for _, x, y, _, _ in zones]
    land = []
    for j in range(NY):
        y = Y0+(j+.5)*CELL
        for i in range(NX):
            x = X0+(i+.5)*CELL
            land.append(2 if inside(x, y, ISLET) else 1 if inside(x, y, OUTLINE) else 0)
    classes, zone_of = [], []
    for j in range(NY):
        for i in range(NX):
            k = j*NX+i
            if not land[k]:
                classes.append('~')
                zone_of.append(-1)
                continue
            x, y = center(i, j)
            best, bd = -1, 1e18
            for n, (_, zx, zy, _, _) in enumerate(zones):
                if (land[k] == 2) != islet[n]:
                    continue
                dd = (zx-x)**2+(zy-y)**2
                if dd < bd:
                    best, bd = n, dd
            zone_of.append(best)
            shore = any(not land[(j+dj)*NX+i+di] for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if 0 <= i+di < NX and 0 <= j+dj < NY)
            classes.append(_classify(x, y, shore, zones[best], zones))
    return ''.join(classes), zone_of


def _classify(x, y, shore, zone, zones):
    fine = _noise(x*1.7, y*1.7)
    for _, zx, zy, town, _ in zones:
        r = .42*sqrt(town/1000)
        d = hypot(zx-x, zy-y)
        if d < r*(.8+.4*fine):
            return 'T'
        if d < r*2.1*(.8+.4*fine) and _hash(int(x*7), int(y*7)) < .55:
            return 'v'
    if shore:
        return 'b'
    for qx, qy, r in QUARRIES:
        if hypot(qx-x, qy-y) < r:
            return 'q'
    for rx, ry, r in RESERVES:
        if hypot(rx-x, ry-y) < r*(.85+.3*fine):
            return 'r'
    big = _noise(x/5.5+11, y/5.5+3)
    bias = {'rural': .08, 'agri': -.08, 'tourism': .02, 'industrial': 0., 'urban': -.2, 'suburban': -.1}[zone[4]]
    if big+bias > .66:
        return 'F'
    if big+bias < .27 or (zone[4] == 'industrial' and big < .4):
        return 'a'
    if fine < .06:
        return 'w'
    if _hash(int(x*3), int(y*3)) < .035:
        return 'v'
    return 'f'


def land_class(x, y):
    c = cell_of(x, y)
    if c is None:
        return '~'
    return grid()[0][c[1]*NX+c[0]]


def homes_within(x, y, km):
    """Whether a town or village parcel lies within `km` of a point."""
    classes = grid()[0]
    c = cell_of(x, y)
    if c is None:
        return False
    reach = int(km/CELL)+1
    for dj in range(-reach, reach+1):
        for di in range(-reach, reach+1):
            i, j = c[0]+di, c[1]+dj
            if 0 <= i < NX and 0 <= j < NY and classes[j*NX+i] in 'Tv':
                cx, cy = center(i, j)
                if hypot(cx-x, cy-y) < km+CELL*.5:
                    return True
    return False


@lru_cache(maxsize=1)
def zone_weights():
    """Sum of settlement weights per zone, to spread a zone's residents over its parcels."""
    classes, zone_of = grid()
    w = {}
    for k, c in enumerate(classes):
        if zone_of[k] >= 0:
            w[zone_of[k]] = w.get(zone_of[k], 0.)+CLASSES[c][1]
    return w


def parcel_people(x, y, residents_by_zone):
    classes, zone_of = grid()
    c = cell_of(x, y)
    if c is None:
        return 0.
    k = c[1]*NX+c[0]
    z = zone_of[k]
    if z < 0:
        return 0.
    zid = ZONES[z][0]
    return residents_by_zone.get(zid, 0)*CLASSES[classes[k]][1]/max(1e-9, zone_weights()[z])


def encoded():
    """For the client: the class string and zone indices as characters ('A' + index, '.' for sea)."""
    classes, zone_of = grid()
    return dict(cell=CELL, x0=X0, y0=Y0, nx=NX, ny=NY, classes=classes,
                zones=''.join('.' if z < 0 else chr(65+z) for z in zone_of), zone_ids=[z[0] for z in ZONES],
                legend={k: v[0] for k, v in CLASSES.items()})
