'use strict';
// Island map and grid view: one pixel-art map engine with two modes. Coordinates are kilometres
// (x east, y north); the canvas works in art pixels of P x P screen pixels.
PB.map = (() => {
  const P = 2;
  const canvas = PB.$('map'), ctx = canvas.getContext('2d'), wrap = PB.$('mapWrap'), labelsEl = PB.$('labels');
  let W = 0, H = 0, view = null, mode = 'island', frame = 0, drag = null, hover = null;
  let terrain = null, terrainKey = '', zoneIndex = null, zoneFill = null, zoneFillKey = '';
  const angle = {};
  const layers = {
    island: {zones: true, wind: false, wake: false, population: false, tourism: false, industry: true, load: false, outages: true, grid: true},
    grid: {voltage: true, loading: true, flow: true, islands: true, labels: true},
  };
  const LAYER_NAMES = {zones: 'Zone borders', wind: 'Wind field', wake: 'Turbine wakes', population: 'Population', tourism: 'Tourism',
    industry: 'Industry', load: 'Load density', outages: 'Outages', grid: 'Power lines', voltage: 'Bus voltage', loading: 'Line loading',
    flow: 'Power flow', islands: 'Energised areas', labels: 'Names'};
  const FILL_LAYERS = ['population', 'tourism', 'load', 'outages'];

  // ------------------------------------------------------------ geometry
  const toPx = (x, y) => [(x - view.cx) * view.z + W / 2, (view.cy - y) * view.z + H / 2];
  const toKm = (px, py) => [(px - W / 2) / view.z + view.cx, view.cy - (py - H / 2) / view.z];
  function resize() {
    const r = wrap.getBoundingClientRect();
    const w = Math.max(80, Math.floor(r.width / P)), h = Math.max(80, Math.floor(r.height / P));
    if (w === W && h === H) return;
    W = w; H = h; canvas.width = W; canvas.height = H;
    if (!view) fit();
    terrainKey = '';
  }
  function fit() {
    const xs = [-6, 82], ys = [-2, 123];
    const z = Math.min(W / (xs[1] - xs[0]), H / (ys[1] - ys[0]));
    view = {cx: (xs[0] + xs[1]) / 2, cy: (ys[0] + ys[1]) / 2, z: Math.max(1.2, z)};
    terrainKey = '';
  }
  function spans(poly, y) {
    const xs = [];
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
      if ((y1 > y) !== (y2 > y)) xs.push(x1 + (y - y1) * (x2 - x1) / (y2 - y1));
    }
    return xs.sort((a, b) => a - b);
  }
  function hash(ix, iy) { let h = Math.imul(ix | 0, 374761393) + Math.imul(iy | 0, 668265263); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
  function noise(x, y) {
    const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const a = hash(ix, iy), b = hash(ix + 1, iy), c = hash(ix, iy + 1), d = hash(ix + 1, iy + 1);
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy;
  }
  const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v + .5) / 16);
  const dither = (px, py) => BAYER[(py & 3) * 4 + (px & 3)];
  const rgb = h => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

  // ------------------------------------------------------------ palettes
  function palette(light, season, snow) {
    const day = {
      deep: '#26507e', sea: '#336a9c', shallow: '#5793bd', foam: '#cfe5ec', beach: '#e2d3a2',
      forest: '#3b6a3c', forest2: '#30593a', alvar: '#a3aa86', alvar2: '#b6b896', town: '#b3a08a', town2: '#8d7b68', road: '#d6ccb2',
      fields: {winter: ['#9a9168', '#8c8962', '#a39a70', '#7f7d5b'], spring: ['#86ad58', '#9bbd62', '#7aa452', '#a7b866'],
        summer: ['#8fb258', '#c9bf6e', '#d5c477', '#7ea54f'], autumn: ['#b79c5c', '#a98b4f', '#8f9a58', '#c2a865']}[season],
      snow: '#eef2f4', snow2: '#d9e2e9'};
    const night = {
      deep: '#071026', sea: '#0b1934', shallow: '#13284c', foam: '#2a4a72', beach: '#4a4a52',
      forest: '#1d3a28', forest2: '#183223', alvar: '#3d4638', alvar2: '#454f3f', town: '#3b3946', town2: '#302e3a', road: '#4c4858',
      fields: {winter: ['#3e4034', '#383b30', '#444536', '#33362d'], spring: ['#2e4529', '#34502e', '#2a4026', '#3a4a30'],
        summer: ['#2f4829', '#47472b', '#4e4b2e', '#2b4326'], autumn: ['#47422b', '#403c27', '#374029', '#4a452b']}[season],
      snow: '#5a6680', snow2: '#4e5a72'};
    const out = {};
    for (const k of Object.keys(day)) {
      if (k === 'fields') out.fields = day.fields.map((c, i) => mix(rgb(night.fields[i]), rgb(c), light));
      else out[k] = mix(rgb(night[k]), rgb(day[k]), light);
    }
    out.snowy = snow;
    return out;
  }
  function seasonOf(s) { const m = ['Dec', 'Jan', 'Feb'].includes(s.month) ? 'winter' : ['Mar', 'Apr', 'May'].includes(s.month) ? 'spring' : ['Jun', 'Jul', 'Aug'].includes(s.month) ? 'summer' : 'autumn'; return m; }

  // ------------------------------------------------------------ terrain raster (from the server's land parcels)
  let lights = [];
  function cellAt(x, y) {
    const L = PB.land; const i = Math.floor((x - L.x0) / L.cell), j = Math.floor((y - L.y0) / L.cell);
    return i >= 0 && j >= 0 && i < L.nx && j < L.ny ? j * L.nx + i : -1;
  }
  function buildTerrain() {
    const st = PB.static, s = PB.snap, Ld = PB.land;
    const light = Math.round(PB.light() * 4) / 4, season = seasonOf(s), snow = s.weather.temp < .5 && season === 'winter';
    const key = [view.cx.toFixed(3), view.cy.toFixed(3), view.z.toFixed(3), W, H, light, season, snow, layers.island.zones, mode].join();
    if (key === terrainKey) return;
    terrainKey = key;
    const pal = palette(light, season, snow);
    const img = ctx.createImageData(W, H), d = img.data;
    const cls = Ld.classes, zch = Ld.zones, nx = Ld.nx;
    zoneIndex = new Int8Array(W * H).fill(-1);
    const cellIdx = new Int32Array(W * H);
    lights = [];
    const seaNear = k => { const c = k % nx; for (const o of [1, -1, nx, -nx, 2, -2, 2 * nx, -2 * nx]) { const q = k + o; if (q >= 0 && q < cls.length && Math.abs((q % nx) - c) <= 2 && cls[q] !== '~') return true; } return false; };
    for (let py = 0; py < H; py++) for (let px = 0; px < W; px++) {
      const i = py * W + px, o = i * 4;
      const [x, y] = toKm(px + .5, py + .5), k = cellAt(x, y), cl = k < 0 ? '~' : cls[k];
      cellIdx[i] = k;
      const n = noise(x * 2.5, y * 2.5), fine = noise(x * 1.7, y * 1.7), dt = dither(px, py);
      let c;
      if (cl === '~') {
        const near = k >= 0 && seaNear(k);
        c = near ? (n + dt * .4 > .78 ? pal.sea : pal.shallow) : (n * .6 + dt * .5 > .62 ? pal.sea : pal.deep);
      } else {
        zoneIndex[i] = zch.charCodeAt(k) - 65;
        if (cl === 'b') c = dt < .2 ? pal.foam : pal.beach;
        else if (cl === 'T') {
          const road = (Math.floor(x * 6 + .5) % 4 === 0) || (Math.floor(y * 6 + .5) % 5 === 0);
          c = road ? pal.road : hash(Math.floor(x * 6), Math.floor(y * 6)) > .45 ? pal.town : pal.town2;
          if (!road && hash(Math.floor(x * 12), Math.floor(y * 12)) > .7) lights.push([px, py, zoneIndex[i]]);
        } else if (cl === 'v') {
          const house = hash(Math.floor(x * 10), Math.floor(y * 10)) > .72;
          c = house ? (hash(Math.floor(x * 10) + 3, Math.floor(y * 10)) > .5 ? pal.town : pal.town2) : pal.fields[Math.floor(hash(Math.floor(x / .9), Math.floor(y / .65)) * 4)];
          if (house && hash(Math.floor(x * 10) + 7, Math.floor(y * 10)) > .6) lights.push([px, py, zoneIndex[i]]);
        } else if (cl === 'F') c = fine > .5 ? pal.forest : pal.forest2;
        else if (cl === 'a') c = fine + dt * .3 > .6 ? pal.alvar2 : pal.alvar;
        else if (cl === 'w') c = dt < .5 ? pal.shallow : pal.forest2;
        else if (cl === 'q') c = (Math.floor(y * 8) % 2) ? pal.alvar2 : pal.road;
        else if (cl === 'r') { c = noise(x / 3, y / 3) > .5 ? pal.forest : pal.alvar; if (((px + py) % 6) === 0) c = mix(c, rgb(PB.css('--teal')), .6); }
        else c = pal.fields[Math.floor(hash(Math.floor(x / .9), Math.floor(y / .65)) * 4)];
        if (pal.snowy && cl !== 'T' && cl !== 'q') c = mix(c, (fine + dt * .5 > .7) ? pal.snow2 : pal.snow, cl === 'F' ? .55 : .85);
      }
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 255;
    }
    if (layers.island.zones || mode === 'grid') {
      const line = mix(pal.town2, [20, 20, 30], .4);
      for (let py = 1; py < H; py++) for (let px = 1; px < W; px++) {
        const i = py * W + px, a = zoneIndex[i];
        if (a >= 0 && ((zoneIndex[i - 1] >= 0 && zoneIndex[i - 1] !== a) || (zoneIndex[i - W] >= 0 && zoneIndex[i - W] !== a)) && ((px + py) & 1)) {
          const o = i * 4; d[o] = line[0]; d[o + 1] = line[1]; d[o + 2] = line[2];
        }
      }
    }
    terrain = document.createElement('canvas'); terrain.width = W; terrain.height = H;
    terrain.getContext('2d').putImageData(img, 0, 0);
    PB.map.cellIdx = cellIdx;
    zoneFillKey = '';
  }

  // Zone metric fill (population, tourism, load, outages), recomputed when the values change.
  function buildZoneFill() {
    const s = PB.snap, st = PB.static;
    const active = FILL_LAYERS.filter(k => layers.island[k] && mode === 'island');
    const metric = active.find(k => k !== 'outages');
    const key = terrainKey + active.join() + JSON.stringify(st.zones.map(z => s.zones[z.id] && [s.zones[z.id][0], s.zones[z.id][1], Math.round(s.zones[z.id][5] * 10), Math.round(s.zones[z.id][6] * 10)]));
    if (key === zoneFillKey) return;
    zoneFillKey = key;
    if (!active.length) { zoneFill = null; return; }
    const val = st.zones.map(z => { const v = s.zones[z.id]; return {population: v[0], tourism: v[1] + v[2], load: v[5]}[metric] ?? 0; });
    const max = Math.max(1e-9, ...val);
    const out = st.zones.map(z => s.zones[z.id][6] > .001 || !s.zones[z.id][9]);
    const img = ctx.createImageData(W, H), d = img.data;
    const col = metric === 'tourism' ? [240, 166, 86] : metric === 'load' ? [255, 111, 94] : [108, 182, 238];
    for (let i = 0; i < W * H; i++) {
      const k = zoneIndex[i]; if (k < 0) continue;
      const px = i % W, py = (i / W) | 0, o = i * 4;
      if (layers.island.outages && out[k] && ((px + py + (frame >> 3)) & 3) === 0) { d[o] = 255; d[o + 1] = 60; d[o + 2] = 50; d[o + 3] = 200; continue; }
      if (!metric) continue;
      const t = Math.sqrt(val[k] / max);
      if (dither(px, py) < t * .55) { d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = 150; }
    }
    zoneFill = document.createElement('canvas'); zoneFill.width = W; zoneFill.height = H;
    zoneFill.getContext('2d').putImageData(img, 0, 0);
  }

  // ------------------------------------------------------------ drawing helpers
  const R = (x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), w, h); };
  function L(x0, y0, x1, y1, c, width = 1, dash = 0) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy, n = 0; ctx.fillStyle = c;
    for (let guard = 0; guard < 4000; guard++) {
      if (!dash || ((n++ / dash) | 0) % 2 === 0) ctx.fillRect(x0, y0, width, width);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err; if (e2 >= dy) { err += dy; x0 += sx; } if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }
  const css = PB.css;
  function loadingColor(x) { return x > 1 ? css('--red') : x > .9 ? css('--orange') : x > .6 ? css('--accent') : css('--green'); }
  function voltageColor(v) { return v < .2 ? '#555' : v < .9 ? css('--red') : v < .95 ? css('--orange') : v > 1.08 ? css('--violet') : v > 1.05 ? css('--blue') : css('--green'); }
  const kvColor = kv => kv >= 100 ? css('--accent') : kv >= 30 ? css('--teal') : kv >= 10 ? css('--gray') : css('--faint');

  // ------------------------------------------------------------ frame
  function draw() {
    if (!PB.static || !PB.snap || wrap.offsetParent === null) return;
    resize(); buildTerrain(); buildZoneFill();
    frame++;
    ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha = 1; ctx.drawImage(terrain, 0, 0);
    if (mode === 'grid') { ctx.fillStyle = document.documentElement.dataset.theme === 'day' ? 'rgba(248,240,220,.55)' : 'rgba(9,13,27,.55)'; ctx.fillRect(0, 0, W, H); }
    if (zoneFill) ctx.drawImage(zoneFill, 0, 0);
    const s = PB.snap, st = PB.static, night = 1 - PB.light();
    if (mode === 'island') { if (layers.island.wind) drawWind(s); if (layers.island.wake) drawWakes(s); }
    if (mode === 'island' && night > .2) drawLights(s, night);
    if (mode === 'grid' || layers.island.grid) drawBranches(s, st);
    if (mode === 'grid') drawBuses(s, st);
    drawStations(s, st);
    drawTurbines(s, st);
    drawStorage(s, st);
    if (mode === 'island' && layers.island.industry) drawFirms(s, st);
    drawSelection(st);
    drawBuild();
    if (frame % 15 === 1) placeLabels();
  }
  function drawLights(s, night) {
    const st = PB.static;
    const served = st.zones.map(z => { const v = s.zones[z.id]; return !v || !v[9] ? 0 : v[5] > 0 ? 1 - v[6] / v[5] : 1; });
    for (let k = 0; k < lights.length; k++) {
      const [px, py, z] = lights[k];
      if (z < 0 || hash(k, 17) > night * served[z] * 1.1) continue;
      if (hash(k, frame >> 5) < .04) continue;
      R(px, py, 1, 1, k % 5 ? '#ffd27a' : '#fff1c2');
    }
  }
  // Surface wind for display: open sea and shore are windier, forest and towns slow it down.
  const WIND_SURFACE = {'~': 1.15, b: 1.1, a: 1, f: 1, w: 1, q: .95, r: .95, v: .88, F: .82, T: .75};
  function drawWind(s) {
    // Arrows sit on a grid fixed in km, so they pan and zoom with the map; the grid coarsens as you zoom out.
    let km = .5; while (km * view.z < 16) km *= 2;
    const dir = (s.weather.dir + 180) * Math.PI / 180, ux = Math.sin(dir), uy = Math.cos(dir);   // blowing towards, km axes (north up)
    const drift = ((frame * s.weather.wind * .0025) % 1) * km;
    const [xa, ya] = toKm(0, H), [xb, yb] = toKm(W, 0), bright = PB.light() > .5;
    for (let gy = Math.floor(ya / km - 1) * km; gy <= yb + km; gy += km) for (let gx = Math.floor(xa / km - 1) * km; gx <= xb + km; gx += km) {
      const x = gx + ux * drift, y = gy + uy * drift, k = cellAt(x, y), cls = k < 0 ? '~' : PB.land.classes[k], surface = WIND_SURFACE[cls] ?? 1;
      const gust = .85 + .3 * noise(x * .15 + frame * .004, y * .15);
      const len = Math.min(km * view.z * .8, (2 + s.weather.wind * .9) * surface * gust);
      const [px, py] = toPx(x, y), ex = px + ux * len, ey = py - uy * len;
      if (bright && cls !== '~') {   // light land (and snow) in daylight: dark arrows
        L(px, py, ex, ey, 'rgba(30,44,70,.6)');
        R(ex, ey, 1, 1, '#1e2c46');
      } else {
        L(px, py, ex, ey, 'rgba(255,255,255,.6)');
        R(ex, ey, 1, 1, '#ffffff');
      }
    }
  }
  function drawWakes(s) {
    const st = PB.static, dir = (s.weather.dir + 180) * Math.PI / 180, ux = Math.sin(dir), uy = Math.cos(dir);
    ctx.globalAlpha = .35;
    for (const [id, t] of Object.entries(st.turbines)) {
      if ((s.turbines[id] || [0])[0] <= .05) continue;
      for (let k = 1; k < 18; k++) {
        const dkm = k * .12, spread = (t[5] / 2000) + .075 * dkm;
        const [px, py] = toPx(t[1] + ux * dkm, t[2] + uy * dkm), w = Math.max(1, Math.round(spread * view.z * 2));
        R(px - w / 2, py, w, 1, '#d6ecff');
      }
    }
    ctx.globalAlpha = 1;
  }
  function branchEnds(st, b) { const A = st.buses[b[0]], B = st.buses[b[1]]; return [toPx(A[2], A[3]), toPx(B[2], B[3])]; }
  function drawBranches(s, st) {
    // The mainland link leaves the map toward the west.
    const lk = st.link, [lx, ly] = toPx(lk.x, lk.y), [mx, my] = toPx(st.island.mainland[0], st.island.mainland[1]);
    const linkState = s.branches.hvdc || [0, 0, 0, 'ok'];
    L(lx, ly, mx, my, linkState[3] === 'ok' ? css('--violet') : css('--red'), 2, 4);
    if (mode === 'grid' && layers.grid.flow) flowDots(lx, ly, mx, my, -(s.totals.link || 0));
    for (const [id, b] of Object.entries(st.branches)) {
      if (id === 'hvdc') continue;
      const [[x0, y0], [x1, y1]] = branchEnds(st, b);
      if (Math.abs(x0 - x1) + Math.abs(y0 - y1) < 1) continue;
      const v = s.branches[id] || [0, 0, 0, 'ok'], kv = st.buses[b[0]][1], status = v[3];
      let col = kvColor(kv), width = kv >= 100 ? 2 : 1;
      if (mode === 'grid') {
        width = kv >= 100 ? 2 : 1;
        col = layers.grid.loading ? loadingColor(v[2]) : kvColor(kv);
        if (layers.grid.islands && status === 'dead') col = '#555a6e';
      } else if (b[2] === 'line' && kv < 30 && view.z < 2.5) continue;
      if (status === 'planned') { if (b[3] === 'CAB220' || mode === 'grid' || view.z >= 3) L(x0, y0, x1, y1, '#8a90a8', width, 3); continue; }
      if (b[3] === 'CAB220' && mode === 'island') col = css('--teal');
      if (status === 'tripped' || status === 'repair' || status === 'open') { L(x0, y0, x1, y1, css('--red'), width, 2); continue; }
      L(x0, y0, x1, y1, col, width);
      if (mode === 'grid' && layers.grid.flow && status === 'ok') flowDots(x0, y0, x1, y1, v[0]);
      if (mode === 'island' && v[2] > .95 && (frame >> 3) & 1) L(x0, y0, x1, y1, css('--red'), width);
    }
  }
  function flowDots(x0, y0, x1, y1, p) {
    if (Math.abs(p) < .05) return;
    const len = Math.hypot(x1 - x0, y1 - y0); if (len < 6) return;
    const dir = p > 0 ? 1 : -1, speed = Math.min(1.2, .15 + Math.abs(p) / 20), gap = 9;
    const off = ((frame * speed) % gap) * dir;
    for (let d = ((off % gap) + gap) % gap; d < len; d += gap) {
      const t = d / len; R(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 1, 1, '#ffffff');
    }
  }
  function drawBuses(s, st) {
    for (const [id, b] of Object.entries(st.buses)) {
      if (b[4] === 'turbine' && view.z < 6) continue;
      const [px, py] = toPx(b[2], b[3]), v = s.buses[id] || [1, 0, true];
      const size = b[1] >= 100 ? 4 : b[1] >= 20 ? 3 : 2;
      const col = layers.grid.voltage ? voltageColor(v[0]) : kvColor(b[1]);
      R(px - size / 2 - 1, py - size / 2 - 1, size + 2, size + 2, css('--edge'));
      R(px - size / 2, py - size / 2, size, size, v[2] ? col : '#555a6e');
    }
  }
  function drawStations(s, st) {
    for (const [id, x] of Object.entries(st.substations)) {
      const [px, py] = toPx(x[1], x[2]);
      R(px - 3, py - 3, 7, 7, css('--edge')); R(px - 2, py - 2, 5, 5, css('--accent'));
      R(px - 1, py - 1, 3, 3, s.buses[x[3]] && s.buses[x[3]][2] ? css('--edge') : css('--red'));
    }
    const [sx, sy] = toPx(st.hvac.station[0], st.hvac.station[1]), acOn = s.totals.cap_ac > 0;
    R(sx - 4, sy - 4, 9, 9, css('--edge')); R(sx - 3, sy - 3, 7, 7, acOn ? css('--teal') : '#8a90a8'); R(sx - 1, sy - 1, 3, 3, css('--edge'));
    const [lx, ly] = toPx(st.link.x, st.link.y);
    R(lx - 4, ly - 4, 9, 9, css('--edge')); R(lx - 3, ly - 3, 7, 7, css('--violet'));
    const ok = s.link.filter(p => p[2] === 'ok').length;
    for (let k = 0; k < s.link.length; k++) R(lx - 2 + k * 3, ly - 1, 2, 3, k < ok ? '#ffffff' : css('--red'));
    for (const [id, f] of Object.entries(st.farms)) {
      const b = st.buses[f[1]]; if (!b) continue;
      const [px, py] = toPx(b[2], b[3]); R(px - 2, py - 2, 5, 5, css('--edge')); R(px - 1, py - 1, 3, 3, css('--teal'));
    }
  }
  function drawTurbines(s, st) {
    const big = view.z >= 3.2, cols = {ok: '#f4f1e6', fault: css('--red'), maintenance: css('--orange'), construction: '#9aa0c0', waiting: css('--violet'), 'high wind': '#c9d2e0'};
    for (const [id, t] of Object.entries(st.turbines)) {
      const v = s.turbines[id] || [0, 'construction', 0];
      const [px, py] = toPx(t[1], t[2]), status = v[1], mw = t[4];
      const c = cols[status] || '#f4f1e6';
      if (!big) { R(px - 1, py - 1, 2, 2, css('--edge')); R(px, py, 1, 1, c); continue; }
      if (status === 'construction') {
        R(px - 1, py - 5, 3, 7, css('--edge')); for (let k = 0; k < 6; k += 2) R(px, py - 4 + k, 1, 1, '#c9a35c');
        continue;
      }
      angle[id] = ((angle[id] || hash(t[1] * 10, t[2] * 10) * 6.28) + (v[0] / mw) * .35 + (status === 'ok' && v[0] > 0 ? .02 : 0)) % 6.283;
      R(px, py - 6, 1, 7, css('--edge')); R(px - 1, py, 3, 1, css('--edge'));
      R(px, py - 5, 1, 5, c);
      const hx = px, hy = py - 6, lenB = 4;
      for (let k = 0; k < 3; k++) {
        const a = angle[id] + k * 2.094;
        for (let r = 1; r <= lenB; r++) R(hx + Math.round(Math.cos(a) * r), hy + Math.round(Math.sin(a) * r), 1, 1, c);
      }
      R(hx, hy, 1, 1, status === 'ok' ? css('--accent') : c);
    }
  }
  function drawStorage(s, st) {
    for (const [id, b] of Object.entries(st.storage)) {
      const [px, py] = toPx(b[2], b[3]), v = s.storage[id] || [0, 0, 'construction'];
      R(px - 3, py - 2, 8, 5, css('--edge'));
      const fill = Math.round(6 * (v[1] || 0));
      R(px - 2, py - 1, 6, 3, '#3a3f58'); R(px - 2, py - 1, fill, 3, v[0] < -.05 ? css('--green') : v[0] > .05 ? css('--orange') : css('--teal'));
      if (v[4] && (frame >> 3) & 1) R(px - 3, py - 3, 8, 1, css('--violet'));
    }
  }
  function drawFirms(s, st) {
    for (const [id, f] of Object.entries(st.firms)) {
      if (!['cement', 'quarry', 'dairy', 'feedmill', 'slaughter', 'brewery', 'port', 'hospital', 'datacenter'].includes(f[1])) continue;
      const b = st.buses[f[4]]; if (!b) continue;
      const off = hash(id.length, id.charCodeAt(2)) * 1.6 - .8;
      const [px, py] = toPx(b[2] + off, b[3] - .9 + off * .4), v = s.firms[id] || ['operating', 0, 0, 0];
      const on = v[3] > .05, col = f[1] === 'hospital' ? css('--red') : f[1] === 'datacenter' ? css('--blue') : css('--gray');
      R(px - 2, py - 2, 6, 4, css('--edge')); R(px - 1, py - 1, 4, 2, v[0] === 'construction' ? '#c9a35c' : col);
      if (f[1] === 'cement' || f[1] === 'dairy') { R(px + 2, py - 5, 1, 3, css('--edge')); if (on && (frame >> 2) % 3) R(px + 2 + ((frame >> 4) & 1), py - 6 - ((frame >> 3) & 1), 1, 1, '#d9d9d9'); }
    }
  }
  function drawSelection(st) {
    const id = PB.selected; if (!id || !((frame >> 3) & 1)) return;
    const pos = positionOf(id); if (!pos) return;
    const [px, py] = toPx(pos[0], pos[1]), r = pos[2] || 6;
    const c = css('--accent');
    for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { R(px + dx * r - (dx > 0 ? 2 : 0), py + dy * r - (dy > 0 ? 0 : 0), 3, 1, c); R(px + dx * r, py + dy * r - (dy > 0 ? 2 : 0), 1, 3, c); }
  }
  function positionOf(id) {
    const st = PB.static;
    if (id.startsWith('parcel_')) { const [, i, j] = id.split('_').map(Number), L = PB.land; return [L.x0 + (i + .5) * L.cell, L.y0 + (j + .5) * L.cell, Math.max(3, L.cell * view.z / 2 + 1)]; }
    if (st.turbines[id]) return [st.turbines[id][1], st.turbines[id][2], 8];
    if (st.substations[id]) return [st.substations[id][1], st.substations[id][2], 6];
    if (st.storage[id]) return [st.storage[id][2], st.storage[id][3], 6];
    if (st.buses[id]) return [st.buses[id][2], st.buses[id][3], 5];
    if (st.branches[id]) { const b = st.branches[id], A = st.buses[b[0]], B = st.buses[b[1]]; return [(A[2] + B[2]) / 2, (A[3] + B[3]) / 2, 5]; }
    const z = st.zones.find(z => z.id === id); if (z) return [z.x, z.y, 10];
    if (st.firms[id]) { const b = st.buses[st.firms[id][4]]; return b && [b[2], b[3] - .9, 6]; }
    if (id === 'link') return [st.link.x, st.link.y, 7];
    return null;
  }
  // ------------------------------------------------------------ labels (HTML, crisp pixel font)
  function placeLabels() {
    const st = PB.static, s = PB.snap; if (!st || !s) return;
    const out = [], boxes = [];
    // Collision-free labels: bigger places first; a label that would overlap another is left out.
    const add = (x, y, text, cls = '', force = false) => {
      const [px, py] = toPx(x, y); if (px < 0 || py < 0 || px > W || py > H) return false;
      const w = (text.length * (cls.includes('big') ? 7 : cls.includes('small') ? 5.5 : 6.3)) / P + 2, h = 7;
      const box = [px - w / 2, py - h / 2, px + w / 2, py + h / 2];
      if (!force && boxes.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return false;
      boxes.push(box); out.push(`<span class="${cls}" style="left:${px * P}px;top:${py * P}px">${PB.esc(text)}</span>`); return true;
    };
    if (mode === 'island') {
      // Places whose zones share a first word form one town (Västerhamn): one name when zoomed out.
      const groups = {};
      for (const z of st.zones) { const head = z.name.split(' ')[0]; (groups[head] ||= []).push(z); }
      const zones = [...st.zones].sort((a, b) => (s.zones[b.id] ? s.zones[b.id][0] : 0) - (s.zones[a.id] ? s.zones[a.id][0] : 0));
      for (const [head, list] of Object.entries(groups)) {
        if (list.length < 3) continue;
        const cx = list.reduce((a, z) => a + z.x, 0) / list.length, cy = list.reduce((a, z) => a + z.y, 0) / list.length;
        if (view.z < 9) add(cx - 1.5, cy + 2.2, head.toUpperCase(), 'big', true);
      }
      for (const z of zones) {
        const head = z.name.split(' ')[0], city = groups[head].length >= 3, v = s.zones[z.id];
        if (city && view.z < 9) continue;
        const name = city ? z.name.slice(head.length + 1) : z.name;
        if (view.z < 2.6 && !['urban', 'industrial'].includes(z.kind) && z.town < 1400) continue;
        const ok = add(z.x, z.y + (city ? .45 : 1.4), name.toUpperCase(), z.kind === 'urban' || z.town >= 1500 ? 'big' : '');
        if (ok && view.z >= 6 && v) add(z.x, z.y + (city ? -.25 : -1.1), `${PB.int(v[0])} res · ${PB.int(v[1] + v[2])} visitors`, 'small');
      }
      const t = s.totals, first = st.hvac.stages[0];
      add(st.island.mainland[0] + 30, st.island.mainland[1] + 2.5, `← HVDC ${st.link.poles.length}×${PB.int(st.link.poles[0][2])} MW`, 'small', true);
      add(st.hvac.mainland[0] + 30, st.hvac.mainland[1] + 6.5, t.cap_ac > 0 ? `← HVAC 220 kV · ${PB.int(t.cap_ac)} MW` : `← HVAC 220 kV · planned ${first.date}`, 'small', true);
      if (view.z >= 4) add(st.hvac.station[0] + 1.5, st.hvac.station[1] - 1.2, st.hvac.name.toUpperCase(), 'small');
    } else if (layers.grid.labels) {
      for (const [id, x] of Object.entries(st.substations)) { const v = s.buses[x[3]]; add(x[1], x[2] + 2.2, `${x[0].toUpperCase()} ${v ? PB.fmt(v[0], 3) : ''}`); }
      add(st.link.x - 3, st.link.y + 2.4, `HVDC ${PB.fmt(s.totals.link_dc, 1)} MW`, '', true);
      add(st.hvac.station[0] + 3, st.hvac.station[1] - 2, s.totals.cap_ac > 0 ? `HVAC ${PB.fmt(s.totals.link_ac, 1)} MW` : 'HVAC (PLANNED)', '', true);
      for (const [id, f] of Object.entries(st.farms)) { const b = st.buses[f[1]]; if (b) add(b[2], b[3] - 2, f[0].toUpperCase(), 'small'); }
    }
    labelsEl.innerHTML = out.join('');
  }

  // ------------------------------------------------------------ hit testing and interaction
  function hit(px, py) {
    const st = PB.static, s = PB.snap; let best = null, bd = 1e9;
    const consider = (id, x, y, r) => { const [qx, qy] = toPx(x, y), d = Math.hypot(qx - px, qy - py); if (d <= r && d < bd) { bd = d; best = id; } };
    for (const [id, t] of Object.entries(st.turbines)) consider(id, t[1], t[2], view.z >= 3.2 ? 5 : 3);
    for (const [id, b] of Object.entries(st.storage)) consider(id, b[2], b[3], 5);
    for (const [id, x] of Object.entries(st.substations)) consider(id, x[1], x[2], 5);
    consider('link', st.link.x, st.link.y, 6);
    consider('link', st.hvac.station[0], st.hvac.station[1], 6);
    if (mode === 'island' && layers.island.industry) for (const [id, f] of Object.entries(st.firms)) {
      if (!['cement', 'quarry', 'dairy', 'feedmill', 'slaughter', 'brewery', 'port', 'hospital', 'datacenter'].includes(f[1])) continue;
      const b = st.buses[f[4]]; if (!b) continue; const off = hash(id.length, id.charCodeAt(2)) * 1.6 - .8; consider(id, b[2] + off, b[3] - .9 + off * .4, 4);
    }
    if (best) return best;
    if (mode === 'grid') for (const [id, b] of Object.entries(st.buses)) { if (b[4] !== 'turbine') consider(id, b[2], b[3], 3); }
    if (best) return best;
    if (mode === 'grid' || layers.island.grid) {
      for (const [id, b] of Object.entries(st.branches)) {
        if (id === 'hvdc') continue;
        const [[x0, y0], [x1, y1]] = branchEnds(st, b), L2 = (x1 - x0) ** 2 + (y1 - y0) ** 2; if (L2 < 1) continue;
        const t = PB.clamp(((px - x0) * (x1 - x0) + (py - y0) * (y1 - y0)) / L2), d = Math.hypot(x0 + t * (x1 - x0) - px, y0 + t * (y1 - y0) - py);
        if (d < 2.5 && d < bd) { bd = d; best = id; }
      }
      if (best) return best;
    }
    if (Math.hypot(...toPx(st.island.mainland[0] + 30, st.island.mainland[1]).map((v, k) => v - [px, py][k])) < 30) return 'link';
    const [x, y] = toKm(px, py), k = cellAt(x, y);
    if (k >= 0 && PB.land.classes[k] !== '~') return `parcel_${k % PB.land.nx}_${Math.floor(k / PB.land.nx)}`;
    return null;
  }
  function tooltip(id, ev) {
    const tip = PB.$('tooltip'); if (!id) { tip.hidden = true; return; }
    const s = PB.snap, st = PB.static; let text = `<b>${PB.esc(PB.name(id))}</b>`;
    if (st.turbines[id]) { const v = s.turbines[id]; text += `<br>${PB.fmt(v[0], 2)} MW · ${v[1]} · hub wind ${PB.fmt(v[2], 1)} m/s`; }
    else if (st.branches[id]) { const v = s.branches[id]; text += `<br>${PB.fmt(v[0], 2)} MW · loading ${PB.pct(v[2])} · ${v[3]}`; }
    else if (st.buses[id]) { const v = s.buses[id]; text += `<br>${PB.fmt(v[0], 4)} pu · ${PB.fmt(v[1], 1)}°`; }
    else if (st.substations[id]) { const v = s.buses[st.substations[id][4]]; text += `<br>20 kV busbar ${PB.fmt(v && v[0], 3)} pu`; }
    else if (st.firms[id]) { const v = s.firms[id]; text += `<br>${PB.int(v[1])} staff · ${PB.fmt(v[3], 2)} MW`; }
    else if (id.startsWith('parcel_')) {
      const [, i, j] = id.split('_').map(Number), k = j * PB.land.nx + i, z = PB.static.zones[PB.land.zones.charCodeAt(k) - 65];
      text = `<b>${PB.esc(PB.land.legend[PB.land.classes[k]])}</b><br>${PB.esc(z ? z.name : '')} · click for the parcel`;
    } else { const z = s.zones[id]; if (z) text += `<br>${PB.int(z[0])} residents · ${PB.int(z[1] + z[2])} visitors · ${PB.fmt(z[5], 1)} MW`; }
    tip.innerHTML = text; tip.hidden = false;
    const r = wrap.getBoundingClientRect();
    tip.style.left = Math.min(r.width - 200, ev.clientX - r.left + 14) + 'px'; tip.style.top = (ev.clientY - r.top + 14) + 'px';
  }
  function local(ev) { const r = wrap.getBoundingClientRect(); return [(ev.clientX - r.left) / P, (ev.clientY - r.top) / P]; }
  wrap.addEventListener('pointerdown', ev => { drag = {x: ev.clientX, y: ev.clientY, cx: view.cx, cy: view.cy, moved: false}; wrap.setPointerCapture(ev.pointerId); });
  wrap.addEventListener('pointermove', ev => {
    if (drag) {
      const dx = (ev.clientX - drag.x) / P / view.z, dy = (ev.clientY - drag.y) / P / view.z;
      if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4) drag.moved = true;
      if (drag.moved) { view.cx = drag.cx - dx; view.cy = drag.cy + dy; terrainKey = ''; placeLabels(); }
      return;
    }
    const [px, py] = local(ev);
    if (PB.building) { PB.building.mouse = toKm(px, py); return; }
    hover = hit(px, py); tooltip(hover, ev);
  });
  wrap.addEventListener('pointerup', ev => {
    const d = drag; drag = null;
    if (d && d.moved) return;
    const [px, py] = local(ev);
    if (PB.building) { PB.emit('build-click', toKm(px, py), hit(px, py)); return; }
    const id = hit(px, py); if (id) PB.select(id);
  });
  wrap.addEventListener('pointerleave', () => { PB.$('tooltip').hidden = true; });
  wrap.addEventListener('wheel', ev => {
    ev.preventDefault();
    const [px, py] = local(ev), [x, y] = toKm(px, py), f = ev.deltaY < 0 ? 1.25 : 1 / 1.25;
    view.z = PB.clamp(view.z * f, 1, 40);
    const [nx, ny] = toKm(px, py); view.cx += x - nx; view.cy += y - ny; terrainKey = ''; placeLabels();
  }, {passive: false});
  wrap.addEventListener('dblclick', () => { fit(); placeLabels(); });
  new ResizeObserver(() => { resize(); placeLabels(); }).observe(wrap);

  function drawBuild() {
    const b = PB.building; if (!b || !b.mouse) return;
    const [px, py] = toPx(b.mouse[0], b.mouse[1]);
    if (b.type === 'turbine') { R(px, py - 6, 1, 7, css('--accent')); for (let k = 0; k < 3; k++) { const a = frame * .05 + k * 2.094; for (let r = 1; r <= 4; r++) R(px + Math.round(Math.cos(a) * r), py - 6 + Math.round(Math.sin(a) * r), 1, 1, css('--accent')); } }
    else R(px - 2, py - 2, 5, 5, css('--accent'));
    if (b.plan && b.plan.x != null) { const [qx, qy] = toPx(b.plan.x, b.plan.y); R(qx - 3, qy - 3, 7, 1, css('--green')); R(qx - 3, qy + 3, 7, 1, css('--green')); }
    if (b.a) { const x = PB.static.substations[b.a]; const [ax, ay] = toPx(x[1], x[2]); L(ax, ay, px, py, css('--accent'), 1, 3); }
  }

  // ------------------------------------------------------------ public
  function loop() { try { draw(); } catch (e) { console.error(e); } requestAnimationFrame(loop); }
  requestAnimationFrame(loop);
  PB.on('theme', () => { terrainKey = ''; });
  PB.on('static', () => { terrainKey = ''; placeLabels(); });
  PB.on('snapshot', () => { if (frame % 4 === 0) placeLabels(); });
  return {
    setMode(m) { mode = m; terrainKey = ''; placeLabels(); PB.map.renderLayers(); },
    get mode() { return mode; },
    layers, focus(id) { const p = positionOf(id); if (p) { view.cx = p[0]; view.cy = p[1]; view.z = Math.max(view.z, 6); terrainKey = ''; placeLabels(); } },
    fit() { fit(); placeLabels(); },
    renderLayers() {
      const el = PB.$('layers'), set = layers[mode];
      el.innerHTML = '<h4>LAYERS</h4>' + Object.keys(set).map(k => `<label><input type="checkbox" data-layer="${k}" ${set[k] ? 'checked' : ''}> ${LAYER_NAMES[k]}</label>`).join('');
      el.querySelectorAll('input').forEach(i => i.onchange = () => { set[i.dataset.layer] = i.checked; terrainKey = ''; zoneFillKey = ''; PB.map.legend(); placeLabels(); });
      PB.map.legend();
    },
    legend() {
      const el = PB.$('legend');
      if (mode === 'grid') {
        el.innerHTML = (layers.grid.loading ? `<div><b class="px">LOADING</b> <i style="background:${css('--green')}"></i>&lt;60% <i style="background:${css('--accent')}"></i>60–90 <i style="background:${css('--orange')}"></i>90–100 <i style="background:${css('--red')}"></i>&gt;100</div>` : '')
          + (layers.grid.voltage ? `<div><b class="px">VOLTAGE</b> <i style="background:${css('--red')}"></i>&lt;0.90 <i style="background:${css('--orange')}"></i>&lt;0.95 <i style="background:${css('--green')}"></i>ok <i style="background:${css('--blue')}"></i>&gt;1.05</div>` : '')
          + `<div class="small muted">White dots: active power flow. Dashed red: open or tripped. Grey: de-energised.</div>`;
      } else {
        const f = FILL_LAYERS.filter(k => layers.island[k]);
        el.innerHTML = f.length ? `<div class="small">${f.map(k => LAYER_NAMES[k]).join(' · ')} shading by zone${layers.island.outages ? '; red stripes: zones losing supply' : ''}.</div><div class="small muted">Drag to pan, wheel to zoom, double-click to fit.</div>` : '<div class="small muted">Drag to pan, wheel to zoom, double-click to fit.</div>';
      }
    },
  };
})();
