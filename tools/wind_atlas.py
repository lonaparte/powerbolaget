"""Derive the island's long-term mean wind field from the Global Wind Atlas.

    python tools/wind_atlas.py SWE_wind-speed_100m.tif

Input: the Global Wind Atlas country GeoTIFF of mean wind speed at 100 m for Sweden
(https://globalwindatlas.info/api/gis/country/SWE/wind-speed/100, EPSG:4326, 0.0025 degree pixels).
Output: app/island-wind.json, the mean over each 1 km game cell, using the same lon/lat mapping as the
island outline (x = (lon-18.0)*59.6 km, y = (lat-56.9)*111.2 km).

Reading the ZSTD-compressed GeoTIFF needs tifffile and imagecodecs. They are only needed to regenerate
the file, so they are not part of requirements.lock: install them in a separate environment.

Global Wind Atlas data: CC BY 4.0. Developed by DTU Wind Energy in partnership with the World Bank Group,
with funding from ESMAP (https://globalwindatlas.info).
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
X0, Y0, CELL, NX, NY = -6.0, -2.0, 1.0, 88, 125      # covers the island, the islet and the near sea


def main(path):
    import numpy as np
    import tifffile
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        atlas = page.asarray()
        sx, sy, _ = page.tags['ModelPixelScaleTag'].value
        _, _, _, lon0, lat0, _ = page.tags['ModelTiepointTag'].value
    values = []
    for j in range(NY):
        for i in range(NX):
            xa, xb = X0+i*CELL, X0+(i+1)*CELL
            ya, yb = Y0+j*CELL, Y0+(j+1)*CELL
            lon_a, lon_b = 18.0+xa/59.6, 18.0+xb/59.6
            lat_a, lat_b = 56.9+ya/111.2, 56.9+yb/111.2
            r0, r1 = int((lat0-lat_b)/sy), int((lat0-lat_a)/sy)+1
            c0, c1 = int((lon_a-lon0)/sx), int((lon_b-lon0)/sx)+1
            block = atlas[r0:r1, c0:c1]
            values.append(round(float(np.nanmean(block)), 2))
    out = dict(
        source='Global Wind Atlas, mean wind speed at 100 m (country GeoTIFF for Sweden, v4 set)',
        url='https://globalwindatlas.info/api/gis/country/SWE/wind-speed/100',
        license='CC BY 4.0. Global Wind Atlas: DTU Wind Energy in partnership with the World Bank Group, funded by ESMAP.',
        derived=f'Mean over 1 km game cells, lon/lat mapping x=(lon-18.0)*59.6 km, y=(lat-56.9)*111.2 km; {date.today()}',
        height_m=100, unit='m/s', x0=X0, y0=Y0, cell_km=CELL, nx=NX, ny=NY, values=values)
    target = ROOT/'app'/'island-wind.json'
    target.write_text(json.dumps(out, separators=(',', ':')), encoding='utf-8')
    print(f'{target}: {len(values)} cells, {min(values):.2f}-{max(values):.2f} m/s')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
