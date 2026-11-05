'use strict';
// Shared client state, the API, browser saves, formatting and the day/night theme.
// The browser never simulates: it shows the server's world and sends Powerbolaget's commands.
const PB = window.PB = {
  session: null, static: null, snap: null, view: 'island', selected: null, running: true, speed: 60,
  sinceLog: 0, logs: [], unread: 0, pins: [], listeners: {}, building: null,
};
PB.$ = id => document.getElementById(id);
PB.on = (name, fn) => (PB.listeners[name] ||= []).push(fn);
PB.emit = (name, ...args) => (PB.listeners[name] || []).forEach(fn => fn(...args));
PB.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
PB.fmt = (x, d = 1) => x == null || !isFinite(x) ? '—' : Number(x).toLocaleString('en-GB', {minimumFractionDigits: d, maximumFractionDigits: d});
PB.mw = x => PB.fmt(x, Math.abs(x) >= 100 ? 0 : 1) + ' MW';
PB.pct = (x, d = 0) => x == null ? '—' : PB.fmt(100 * x, d) + ' %';
PB.msek = x => x == null ? '—' : PB.fmt(Math.abs(x) < .05 ? 0 : x, Math.abs(x) >= 100 ? 0 : 1) + ' MSEK';
PB.int = x => x == null ? '—' : Math.round(x).toLocaleString('en-GB');
PB.clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));

PB.toast = (text, error = false) => {
  const t = PB.$('toast'); t.textContent = text; t.className = 'show' + (error ? ' error' : '');
  clearTimeout(PB.toast.timer); PB.toast.timer = setTimeout(() => t.className = '', error ? 6000 : 3500);
};

// ---------------------------------------------------------------- API
PB.api = async (path, body) => {
  const r = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json', 'X-PowerGame': '1'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  let j = null;
  try { j = await r.json(); } catch { j = {}; }
  if (!r.ok) throw Object.assign(Error(typeof j.detail === 'string' ? j.detail : 'The server could not process this request.'), {status: r.status});
  return j;
};
PB.call = async (path, body = {}) => {
  try { return await PB.api(path, {session: PB.session, ...body}); }
  catch (e) {
    if (e.status === 410) { await PB.recover(); return PB.api(path, {session: PB.session, ...body}); }
    throw e;
  }
};

// ---------------------------------------------------------------- saves in this browser (IndexedDB, memory fallback)
PB.store = (() => {
  let db, memory = null;
  const open = () => db ??= new Promise(resolve => {
    try { const r = indexedDB.open('powerbolaget', 2); r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains('worlds')) r.result.createObjectStore('worlds'); };
      r.onsuccess = () => resolve(r.result); r.onerror = r.onblocked = () => resolve(null); } catch { resolve(null); }
  });
  const run = async (mode, fn) => { const d = await open(); if (!d) return undefined;
    return new Promise((resolve, reject) => { const t = d.transaction('worlds', mode), req = fn(t.objectStore('worlds'));
      t.oncomplete = () => resolve(req.result); t.onerror = t.onabort = () => reject(t.error || Error('Browser storage failed; export your save.')); }); };
  return {
    persistent: async () => !!await open(),
    get: async () => (await run('readonly', s => s.get('current'))) ?? memory,
    put: async save => { memory = save; await run('readwrite', s => s.put(save, 'current')); },
  };
})();
PB.saveNow = async (quiet = true) => {
  if (!PB.session) return;
  const state = await PB.call('/save');
  await PB.store.put(state);
  PB.lastSave = Date.now();
  if (!quiet) PB.toast(`Saved in this browser (${state.saved}).`);
  return state;
};
PB.download = state => {
  const p = state.saved || 'world';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(state)], {type: 'application/json'}));
  a.download = `powerbolaget-${p.replace(/[^0-9A-Za-z-]/g, '_')}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
PB.adopt = (j, message) => {
  PB.session = j.session; PB.static = j.static; PB.sinceLog = 0; PB.logs = [];
  PB.apply(j.snapshot); PB.emit('static');
  if (message) PB.toast(message);
};
PB.recover = async () => {
  const save = await PB.store.get();
  if (save) { PB.adopt(await PB.api('/session/load', {save}), `The server restarted; your game continues from the browser save (${save.saved}).`); }
  else { PB.adopt(await PB.api('/session', {seed: 1}), 'The server restarted; a new game has started.'); }
};

// ---------------------------------------------------------------- snapshots
PB.apply = snap => {
  PB.snap = snap;
  for (const e of snap.logs || []) {
    if (e.id > PB.sinceLog) { PB.logs.push(e); PB.sinceLog = e.id; if (['protection', 'fault', 'shedding', 'numerical'].includes(e.kind)) PB.unread++; }
  }
  if (PB.logs.length > 400) PB.logs.splice(0, PB.logs.length - 400);
  PB.theme();
  PB.emit('snapshot', snap);
};

// ---------------------------------------------------------------- theme: day by default; night, or a day/night cycle that follows the simulated sun
PB.themeMode = (() => { try { const m = localStorage.getItem('pb-theme-mode'); return ['day', 'night', 'auto'].includes(m) ? m : 'day'; } catch { return 'day'; } })();
// Daylight from the sun's elevation at the island: full night below -12 degrees, full day above +3.
// Twilight therefore lasts long in the Nordic summer (in June the sun never sinks below -10 degrees,
// so nights stay dim rather than dark) and is short in midwinter.
PB.daylight = () => {
  const s = PB.snap; if (!s) return 0;
  const e = s.weather.elev;
  if (e == null) { const h = s.hour + s.minute_of_hour / 60; return PB.clamp((h - s.weather.sunrise + .5) / 1) * PB.clamp((s.weather.sunset + .5 - h) / 1); }
  const t = PB.clamp((e + 12) / 15);
  return t * t * (3 - 2 * t);
};
// Light level the map is drawn with: full day, full night, or the simulated sun. The shown level eases
// towards the target (time constant 0.5 s), so neither the sun between ticks nor a theme switch jumps.
PB.lightTarget = () => PB.themeMode === 'auto' ? PB.daylight() : PB.themeMode === 'day' ? 1 : 0;
{
  let shown = null, last = 0;
  PB.light = () => {
    const target = PB.lightTarget(), now = performance.now();
    shown = shown == null ? target : shown + (target - shown) * (1 - Math.exp(-(now - last) / 500));
    last = now;
    return shown;
  };
}
let themeFade = 0;
PB.theme = () => {
  const name = PB.themeMode === 'auto' ? (PB.daylight() >= .5 ? 'day' : 'night') : PB.themeMode, root = document.documentElement;
  if (root.dataset.theme !== name) {
    root.classList.add('theme-fade'); clearTimeout(themeFade); themeFade = setTimeout(() => root.classList.remove('theme-fade'), 1000);
    root.dataset.theme = name; PB.emit('theme', name);
  }
  document.querySelectorAll('[data-theme-mode]').forEach(b => b.classList.toggle('on', b.dataset.themeMode === PB.themeMode));
};
PB.setTheme = mode => {
  PB.themeMode = mode;
  try { localStorage.setItem('pb-theme-mode', mode); } catch {}
  PB.theme();
};
// ---------------------------------------------------------------- wind field (same functions as app/windfield.py)
// The wind at a place = its long-term mean at 100 m (Global Wind Atlas) x the island's current anomaly x a
// smooth random variation that changes over about 12 km and 3 hours.
{
  const hash = (ix, iy, iz, seed) => {
    let h = (Math.imul(ix, 374761393) + Math.imul(iy, 668265263) + Math.imul(iz, 1274126177) + Math.imul(seed, 2246822519)) >>> 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
    h = (h ^ (h >>> 16)) >>> 0;
    return h / 4294967296 * 2 - 1;
  };
  const smooth = f => f * f * f * (10 + f * (-15 + 6 * f));
  PB.windNoise = (seed, x, y, z) => {
    const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z), fx = smooth(x - ix), fy = smooth(y - iy), fz = smooth(z - iz);
    let total = 0;
    for (const [dz, wz] of [[0, 1 - fz], [1, fz]]) for (const [dy, wy] of [[0, 1 - fy], [1, fy]]) for (const [dx, wx] of [[0, 1 - fx], [1, fx]])
      total += wx * wy * wz * hash(ix + dx, iy + dy, iz + dz, seed);
    return total;
  };
  PB.windMean = (x, y) => {
    const f = PB.land && PB.land.wind; if (!f) return 0;
    const gx = Math.min(Math.max((x - f.x0) / f.cell_km - .5, 0), f.nx - 1.0001), gy = Math.min(Math.max((y - f.y0) / f.cell_km - .5, 0), f.ny - 1.0001);
    const i = Math.floor(gx), j = Math.floor(gy), fx = gx - i, fy = gy - j, k = j * f.nx + i, v = f.values;
    return (v[k] * (1 - fx) + v[k + 1] * fx) * (1 - fy) + (v[k + f.nx] * (1 - fx) + v[k + f.nx + 1] * fx) * fy;
  };
  // Speed at 100 m (m/s) and the direction it blows from (degrees) at a place, now.
  PB.windAt = (x, y) => {
    const s = PB.snap, seed = PB.static ? PB.static.seed : 0, t = s.minute / 1440;
    const speed = PB.windMean(x, y) * (s.weather.ratio ?? 1) * (1 + .09 * PB.windNoise(seed, x / 12, y / 12, t * 8));
    return [Math.max(0, speed), s.weather.dir + 12 * PB.windNoise(seed + 101, x / 20, y / 20, t * 4)];
  };
}
PB.css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Pins are kept per browser.
try { PB.pins = JSON.parse(localStorage.getItem('pb-pins') || '[]'); } catch { PB.pins = []; }
PB.togglePin = id => {
  const i = PB.pins.indexOf(id); if (i >= 0) PB.pins.splice(i, 1); else PB.pins.push(id);
  try { localStorage.setItem('pb-pins', JSON.stringify(PB.pins)); } catch {}
  PB.emit('pins');
};

// Names for ids, from the static description.
PB.name = id => {
  const st = PB.static; if (!st || !id) return id || '';
  if (st.turbines[id]) return id.toUpperCase();
  if (st.branches[id]) return st.branches[id][7];
  if (st.buses[id]) return st.buses[id][0];
  if (st.firms[id]) return st.firms[id][0];
  if (st.substations[id]) return st.substations[id][0];
  if (st.storage[id]) return st.storage[id][0];
  if (st.oil?.[id]) return st.oil[id][0];
  const z = st.zones.find(z => z.id === id); if (z) return z.name;
  if (id === 'link') return 'Mainland link';
  if (id.startsWith('parcel_')) return 'Parcel ' + id.slice(7).replace('_', '·');
  return id;
};
PB.kindOf = id => {
  const st = PB.static; if (!st) return '';
  return st.turbines[id] ? 'turbine' : st.branches[id] ? 'branch' : st.substations[id] ? 'substation' : st.buses[id] ? 'bus'
    : st.firms[id] ? 'firm' : st.storage[id] ? 'storage' : st.zones.some(z => z.id === id) ? 'zone' : id === 'link' ? 'link' : 'other';
};
PB.select = id => { PB.selected = id; PB.emit('select', id); };
PB.parcelXY = id => { const [, i, j] = id.split('_').map(Number), L = PB.land; return [L.x0 + (i + .5) * L.cell, L.y0 + (j + .5) * L.cell]; };
