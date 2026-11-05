"""Gutnö: a fictional island modelled on the scale, climate and economic geography of Gotland.

Coordinates are kilometres (x east, y north) on a synthetic grid. The outline, settlements, firms,
substations, wiring and settings are invented: this is not a digital twin of any real grid. Zone sizes
follow public orders of magnitude (about 57,000 residents, cement and limestone in the north-east,
farming in the centre and south, summer tourism along the coasts). Numbers marked as assumptions
below are game parameters, not measurements.
"""
from math import exp, hypot

NAME = 'Gutnö'
MAINLAND = (-38.0, 74.0)      # where the link cable leaves the map, toward the mainland in the west

# Coastline traced from Gotland's shape (lon/lat converted at 57.5 N: x = (lon-18.0)*59.6 km,
# y = (lat-56.9)*111.2 km). Anchors: Hoburgen (7, 2), Burgsvik bay (13, 15), Näsudden (6, 20),
# Ronehamn (29, 30), Ljugarn (42, 48), Östergarn (56, 59), Slite (48, 89), Fårösund (62, 107),
# Hallshuk (44, 114), Visby (17, 82), Klintehamn (12, 54). Simplified, and the island is fictional.
OUTLINE = [(7, 2.3), (10, 4), (14, 8), (18.5, 12.5), (21.5, 15.5), (24, 21), (29, 27), (34, 33), (38, 38), (42, 42),
           (45, 46), (47, 50), (51, 53), (55, 56), (56, 60), (53, 64), (50, 67), (51, 71), (53, 75), (51, 79), (49, 83),
           (48.5, 87), (50, 91), (54, 95), (58, 99), (62, 103), (60, 107), (55, 110), (50, 112), (45, 115), (40, 113),
           (35, 110), (30, 106), (26, 101), (23, 96), (20, 90), (17, 84), (15, 79), (13, 74), (11, 68), (10, 62), (11, 57),
           (9, 51), (7, 46), (5.5, 41), (5.5, 35), (6, 29), (5, 24), (6, 20.5), (9.5, 18.5), (12.5, 15), (11, 11), (8.8, 6.5)]
ISLET = [(63, 106), (68, 105), (74, 107), (79, 111), (80, 116), (76, 120), (70, 121), (65, 118), (62, 113), (62, 109)]
POLYGONS = (OUTLINE, ISLET)

# Economic zones. Like Gotland, about half the people live in and around the main town on the west
# coast and most of the rest in small coastal towns; the inland is farmland and forest with service
# villages. Zones are dense where people are dense (seven in and around Västerhamn) and large where
# few people live. Each zone's area is the land nearest its centre, so dense centres make small zones.
# kind: urban | suburban | industrial | agri | tourism | rural. town: people in the zone's main
# settlement (drawn at real scale). heat: share of households heated electrically (direct, heat
# pump); the rest use district heating, biomass or oil. Counterparts are for orientation only.
ZONES = [
    # id, name, x, y, kind, residents, holiday homes, tourist beds, amenity 0-1, (direct, heat pump), town
    ('z01', 'Västerhamn Innerstad', 17.6, 82.6, 'urban', 4200, 60, 2600, .98, (.04, .10), 4200),    # Visby old town
    ('z02', 'Västerhamn Hamnen', 17.1, 80.9, 'urban', 3200, 40, 600, .90, (.05, .12), 3200),        # harbour
    ('z03', 'Västerhamn Öster', 19.7, 81.8, 'urban', 5200, 40, 200, .85, (.06, .16), 5200),         # Östercentrum
    ('z04', 'Västerhamn Gråbo', 20.1, 84.1, 'suburban', 4000, 60, 100, .80, (.08, .24), 4000),      # Gråbo, Terra Nova
    ('z05', 'Västerhamn Söder', 16.4, 78.3, 'suburban', 4600, 200, 400, .82, (.10, .28), 4200),     # Vibble, Västerhejde
    ('z06', 'Västerhamn Norr', 19.7, 87.4, 'suburban', 3000, 300, 600, .78, (.10, .28), 2600),      # Snäck, Brissund
    ('z07', 'Västerhamn Land', 23.6, 79.6, 'rural', 2800, 150, 100, .65, (.16, .40), 600),          # Follingbo, Väskinde
    ('z08', 'Toftaby', 11.8, 69.5, 'tourism', 1700, 800, 1400, .72, (.18, .40), 600),               # Tofta
    ('z09', 'Strandvik', 12.6, 54.8, 'tourism', 3800, 800, 1100, .62, (.20, .40), 1500),            # Klintehamn, west coast
    ('z10', 'Romsta', 29.0, 68.5, 'agri', 3500, 150, 200, .55, (.20, .42), 900),                    # Roma, Dalhem
    ('z11', 'Kalkudden', 47.0, 88.6, 'industrial', 3300, 350, 300, .50, (.18, .40), 1500),          # Slite
    ('z12', 'Norrby', 39.5, 105.5, 'rural', 2700, 900, 1100, .55, (.22, .42), 500),                 # Lärbro, Kappelshamn
    ('z13', 'Sundby', 60.6, 104.6, 'tourism', 1600, 500, 800, .58, (.22, .40), 800),                # Fårösund
    ('z14', 'Fårholm', 71.0, 114.0, 'tourism', 500, 1100, 2200, .72, (.25, .35), 150),              # Fårö
    ('z15', 'Östernäs', 51.0, 64.0, 'rural', 1900, 800, 1200, .58, (.22, .42), 300),                # Östergarn, Gothem
    ('z16', 'Ljunghavn', 43.6, 47.2, 'tourism', 1700, 900, 2400, .70, (.22, .38), 300),             # Ljugarn
    ('z17', 'Hemby', 23.0, 38.0, 'suburban', 5000, 200, 300, .62, (.16, .38), 1900),                # Hemse, inland south
    ('z18', 'Sudret', 13.0, 12.0, 'tourism', 2600, 1000, 1600, .60, (.24, .42), 400),               # Burgsvik, Sundre
]

# Substations: 110/20 kV, number of 40 MVA transformer units.
SUBSTATIONS = [
    ('VHN', 'Västerhamn', 19.5, 80.6, 2), ('KAL', 'Kalkudden', 45.0, 86.6, 2), ('ROM', 'Romsta', 27.6, 66.4, 1),
    ('HEM', 'Hemby', 22.5, 39.5, 1), ('LJU', 'Ljunghavn', 40.0, 48.5, 1), ('NOR', 'Norrby', 38.0, 104.0, 1),
    ('SUD', 'Sudret', 16.2, 18.0, 1), ('STR', 'Strandvik', 14.5, 56.0, 1),
]
LINK_STATION = ('LNK', 'Länkstation', 16.2, 74.0)
# Existing HVDC: two links of 130 MW, the scale of Gotland's two HVDC links (fictional equipment).
LINK_POLES = 2
LINK_POLE_MW = 130.0
# Planned HVAC interconnector, after Svenska kraftnät's Gotlandsförbindelsen: two 220 kV AC subsea
# cables from the mainland (Misterhult, Oskarshamn) to a new station south of the main town (Stenkumla),
# in service from 2031 = FE 6 (FE 1 = 2026). A 2022 planning document gives 440 MW of transfer capacity
# and mentions 200 MW steps; the staging below is an assumption: the first cable at a limited rating,
# the second cable a few months later, full capacity once the mainland grid is reinforced.
HVAC = dict(station=('STK', 'Stenkumla', 21.5, 75.5), mainland=(-38.0, 62.0), cables=2, km=160.0,
            stages=[(5, 243, 1, 150.0), (6, 59, 2, 300.0), (8, 0, 2, 440.0)])   # (year-1, day of year, cables, MW)

# 110 kV lines between stations: (from, to, type)
LINES_110 = [('LNK', 'VHN', 'OHL110'), ('LNK', 'ROM', 'OHL110'), ('VHN', 'NOR', 'OHL110'), ('NOR', 'KAL', 'OHL110'),
             ('KAL', 'ROM', 'OHL110'), ('ROM', 'STR', 'OHL110'), ('STR', 'HEM', 'OHL110'), ('ROM', 'HEM', 'OHL110'),
             ('HEM', 'LJU', 'OHL110'), ('HEM', 'SUD', 'OHL110')]

# Zone feeders at 20 kV: zone -> (feeding bus, line type, parallel circuits). Fårholm is fed across
# the sound from Sundby.
FEEDERS = {'z01': ('VHN', 'CAB20', 2), 'z02': ('VHN', 'CAB20', 2), 'z03': ('VHN', 'CAB20', 2), 'z04': ('VHN', 'CAB20', 2),
           'z05': ('VHN', 'CAB20', 2), 'z06': ('VHN', 'CAB20', 1), 'z07': ('VHN', 'OHL20', 1), 'z08': ('VHN', 'OHL20', 1),
           'z09': ('STR', 'OHL20', 2), 'z10': ('ROM', 'OHL20', 2), 'z11': ('KAL', 'OHL20', 2), 'z12': ('NOR', 'OHL20', 2),
           'z13': ('NOR', 'OHL20', 2), 'z14': ('z13', 'CAB20', 1), 'z15': ('LJU', 'OHL20', 1), 'z16': ('LJU', 'OHL20', 1),
           'z17': ('HEM', 'OHL20', 2), 'z18': ('SUD', 'OHL20', 2)}

def _rows(x0, y0, dx, dy, per_row, rows, row_dx, row_dy):
    return [(round(x0+i*dx+r*row_dx, 2), round(y0+i*dy+r*row_dy, 2)) for r in range(rows) for i in range(per_row)]


# Wind farms in service at the start: id, name, host substation, farm substation (x, y), model, turbine rows,
# turbine age in years.
WIND_FARMS = [
    ('WF1', 'Uddens vindpark', 'SUD', (10.4, 21.2), 'PB-2.3', [_rows(6.9, 21.3, .5, .55, 5, 1, 0, 0), _rows(7.7, 20.3, .5, .55, 5, 1, 0, 0)], 14),
    ('WF2', 'Östergarns vindpark', 'LJU', (49.6, 59.2), 'PB-3.6', [_rows(51.2, 56.6, .1, .82, 4, 1, 0, 0), _rows(52.6, 56.7, .1, .82, 4, 1, 0, 0)], 6),
    ('WF3', 'Nordheds vindpark', 'NOR', (37.4, 105.4), 'PB-2.3', [_rows(35.6, 107.1, 1.05, .1, 4, 1, 0, 0), _rows(35.8, 108.1, 1.05, .1, 4, 1, 0, 0)], 11),
    # Like Gotland, most capacity stands on the windy south-western headland (Näsudden), with more in the
    # north-east and south-east: about 160 MW in all (Gotland: about 180 MW producing about 450 GWh a year).
    ('WF4', 'Näsuddens vindpark II', 'SUD', (9.6, 23.0), 'PB-3.6', [_rows(6.6, 22.4, .5, .05, 5, 1, 0, 0), _rows(7.0, 23.4, .5, .05, 5, 1, 0, 0)], 9),
    ('WF5', 'Ruteparken', 'NOR', (50.2, 98.2), 'PB-2.3', [_rows(48.0, 99.5, .65, .1, 5, 1, 0, 0), _rows(50.5, 98.5, .65, .1, 5, 1, 0, 0)], 12),
    ('WF6', 'Havdhems vindpark', 'HEM', (20.4, 29.8), 'PB-3.6', [_rows(18.4, 29.0, .65, .1, 4, 1, 0, 0), _rows(19.2, 31.0, .65, .1, 4, 1, 0, 0)], 4),
]

TURBINE_MODELS = {
    # rated MW, rotor m, hub m, cut-in, rated speed, cut-out, capex MSEK, build days (assumptions, generic models)
    'PB-2.3': dict(mw=2.3, rotor=93, hub=80, cut_in=3.0, rated_speed=12.5, cut_out=25.0, capex=34.0, days=150),
    'PB-3.6': dict(mw=3.6, rotor=126, hub=100, cut_in=3.0, rated_speed=12.0, cut_out=25.0, capex=48.0, days=170),
    'PB-5.6': dict(mw=5.6, rotor=162, hub=125, cut_in=3.0, rated_speed=11.5, cut_out=25.0, capex=70.0, days=200),
}


def inside(x, y, polygon=None):
    """Point in the island (or in one polygon), by ray casting."""
    for poly in ([polygon] if polygon else POLYGONS):
        hit = False
        for (x1, y1), (x2, y2) in zip(poly, poly[1:]+poly[:1]):
            if (y1 > y) != (y2 > y) and x < x1+(y-y1)*(x2-x1)/(y2-y1):
                hit = not hit
        if hit:
            return True
    return False


def coast_distance(x, y):
    best = float('inf')
    for poly in POLYGONS:
        for (x1, y1), (x2, y2) in zip(poly, poly[1:]+poly[:1]):
            dx, dy = x2-x1, y2-y1
            t = max(0., min(1., ((x-x1)*dx+(y-y1)*dy)/(dx*dx+dy*dy)))
            best = min(best, hypot(x-x1-t*dx, y-y1-t*dy))
    return best


def zone_at(x, y, zones):
    """Economic zone of a point: the nearest zone centre on the same landmass."""
    islet = inside(x, y, ISLET)
    same = [z for z in zones if inside(z['x'], z['y'], ISLET) == islet] or zones
    return min(same, key=lambda z: hypot(z['x']-x, z['y']-y))
