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
PB.daylight = () => {
  const s = PB.snap; if (!s) return 0;
  const h = s.hour + s.minute_of_hour / 60, rise = s.weather.sunrise ?? 7, set = s.weather.sunset ?? 17;
  return PB.clamp((h - rise + .5) / 1) * PB.clamp((set + .5 - h) / 1);
};
// Light level the map is drawn with: full day, full night, or the simulated sun.
PB.light = () => PB.themeMode === 'auto' ? PB.daylight() : PB.themeMode === 'day' ? 1 : 0;
PB.theme = () => {
  const name = PB.themeMode === 'auto' ? (PB.daylight() >= .5 ? 'day' : 'night') : PB.themeMode;
  if (document.documentElement.dataset.theme !== name) { document.documentElement.dataset.theme = name; PB.emit('theme', name); }
  document.querySelectorAll('[data-theme-mode]').forEach(b => b.classList.toggle('on', b.dataset.themeMode === PB.themeMode));
};
PB.setTheme = mode => {
  PB.themeMode = mode;
  try { localStorage.setItem('pb-theme-mode', mode); } catch {}
  PB.theme();
};
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
