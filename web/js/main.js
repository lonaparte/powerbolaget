'use strict';
// Boot, the run loop, the top bar, menus, build mode and the bottom dock.
(() => {
  const $ = PB.$;
  const TICK_SECONDS = .5;
  let busy = false, paceEma = null, lastHistory = 0, hourly = [];

  // ------------------------------------------------------------ top bar
  function topbar(s) {
    $('date').textContent = s.label;
    $('weekday').textContent = `${s.weekday}${s.rest ? ' · rest day' : ''} · ${s.month} ${s.day}`;
    const w = s.weather, arrows = '↓↙←↖↑↗→↘', arrow = arrows[Math.round(((w.dir % 360) / 45)) % 8];
    $('weather').innerHTML = `<span><b>${PB.fmt(w.temp, 1)}°</b></span><span>${arrow} <b>${PB.fmt(w.wind, 1)}</b> m/s</span><span>☁ ${PB.pct(w.cloud)}</span>${w.thunder > .2 ? '<span class="warn">⚡</span>' : ''}${w.icing > .3 ? '<span class="warn">❄ ice</span>' : ''}`;
    const t = s.totals;
    $('balance').innerHTML = [['DEMAND', t.load], ['WIND', t.wind], [t.link >= 0 ? 'IMPORT' : 'EXPORT', Math.abs(t.link)], ['BATTERY', t.battery]]
      .map(([k, v]) => `<span><small>${k}</small><b>${PB.fmt(v, 1)}</b></span>`).join('')
      + (t.unserved > .005 ? `<span class="short"><small>UNSERVED</small><b>${PB.fmt(t.unserved, 1)}</b></span>` : '') + '<span><small>&nbsp;</small>MW</span>';
    const a = $('alerts'); a.textContent = PB.unread ? `⚠ ${PB.unread}` : '✓'; a.classList.toggle('hot', PB.unread > 0);
  }
  function updatePlay() { $('play').textContent = PB.running ? '❚❚' : '▶'; $('play').title = PB.running ? 'Pause (space)' : 'Run (space)'; }
  function pace(simMinutes, ms) {
    const rate = simMinutes / Math.max(1, ms) * 1000;
    paceEma = paceEma == null ? rate : .7 * paceEma + .3 * rate;
    const want = PB.speed;
    $('pace').textContent = paceEma < want * .8 ? `${PB.fmt(paceEma / 60, 1)} h/s (server limit)` : `${want >= 60 ? PB.fmt(want / 60, 0) + ' h/s' : want + ' min/s'}`;
  }

  // ------------------------------------------------------------ run loop
  async function loop() {
    const t0 = performance.now();
    if (PB.running && !busy && PB.session && !document.hidden) {
      busy = true;
      try {
        const before = PB.snap.minute;
        const j = await PB.call('/tick', {minutes: Math.max(1, Math.round(PB.speed * TICK_SECONDS)), since_log: PB.sinceLog,
          grid_version: PB.static.grid_version, firm_count: PB.static.firm_count});
        if (j.static) { PB.static = j.static; PB.emit('static'); }
        PB.apply(j.snapshot);
        pace(j.snapshot.minute - before, performance.now() - t0);
        if (Date.now() - (PB.lastSave || 0) > 45000) PB.saveNow().catch(() => {});
      } catch (e) { PB.toast(e.message, true); PB.running = false; updatePlay(); }
      busy = false;
    }
    setTimeout(loop, Math.max(40, TICK_SECONDS * 1000 - (performance.now() - t0)));
  }
  PB.command = async cmd => {
    cmd = {request_id: crypto.randomUUID(), ...cmd};
    try {
      const j = await PB.call('/command', {command: cmd, since_log: PB.sinceLog});
      if (j.static) { PB.static = j.static; PB.emit('static'); }
      PB.apply(j.snapshot); PB.toast(j.message); PB.inspector.refresh();
      PB.saveNow().catch(() => {});
      return true;
    } catch (e) { PB.toast(e.message, true); return false; }
  };

  // ------------------------------------------------------------ dock
  let dockTab = 'chart';
  function dock() {
    const s = PB.snap; if (!s) return;
    ['charts', 'events', 'projects', 'pins'].forEach(id => $(id).hidden = (id === 'charts' ? 'chart' : id) !== dockTab);
    if (dockTab === 'chart') {
      const css = PB.css, m = s.series;
      PB.chart.draw($('chartMin'), [{name: 'demand', color: css('--blue'), values: m.map(x => x[1]), bold: true}, {name: 'served', color: css('--teal'), values: m.map(x => x[2])},
        {name: 'wind', color: css('--green'), values: m.map(x => x[3])}, {name: 'link', color: css('--violet'), values: m.map(x => x[4])}, {name: 'battery', color: css('--orange'), values: m.map(x => x[5])}],
        {title: 'LAST 4 H · EACH MINUTE (MW)', xlabels: m.length ? ['−' + Math.round((m[m.length - 1][0] - m[0][0]) / 60) + ' h', 'now'] : null});
      const h = hourly.slice(-72);
      PB.chart.draw($('chartHour'), [{name: 'demand', color: css('--blue'), values: h.map(x => x.load)}, {name: 'wind', color: css('--green'), values: h.map(x => x.wind)},
        {name: 'import', color: css('--violet'), values: h.map(x => x.link_import - x.link_export)}, {name: 'unserved', color: css('--red'), values: h.map(x => x.unserved)},
        {name: 'curtailed', color: css('--gray'), values: h.map(x => Math.max(0, x.wind_avail - x.wind))}], {title: 'LAST 3 DAYS · EACH HOUR (MWH)', steps: true, xlabels: h.length ? [`−${h.length} h`, 'now'] : null});
    } else if (dockTab === 'events') {
      $('events').innerHTML = `<ul class="list">${PB.logs.slice().reverse().slice(0, 150).map(e => `<li class="click" data-ref="${PB.esc(e.turbine || e.branch || e.firm || e.storage || e.project || e.zone || '')}"><time>${PB.esc(e.label)}</time><span class="tag ${e.kind}">${e.kind}</span>${PB.esc(e.text)}</li>`).join('') || '<li class="muted">Nothing yet.</li>'}</ul>`;
    } else if (dockTab === 'projects') {
      $('projects').innerHTML = s.projects.length ? `<ul class="list">${s.projects.map(p => `<li class="click" data-ref="${PB.esc(p.id)}"><span style="flex:1">${PB.esc(p.title)}<div class="bar"><i style="width:${100 * p.progress}%"></i></div></span><span class="small muted">${PB.pct(p.progress)} · ready ${PB.esc(p.finish)} · ${PB.msek(p.cost)}</span></li>`).join('')}</ul>`
        : '<p class="muted small">No construction under way. Build from the left bar in the island view; firms\' own expansions appear here too.</p>';
    } else if (dockTab === 'pins') {
      $('pins').innerHTML = PB.pins.length ? `<ul class="list">${PB.pins.map(id => `<li class="click" data-ref="${PB.esc(id)}">${PB.esc(PB.name(id))}<span class="small muted" style="margin-left:auto">${pinValue(id)}</span></li>`).join('')}</ul>`
        : '<p class="muted small">Pin turbines, lines, zones or firms from the inspector to watch them here.</p>';
    }
  }
  function pinValue(id) {
    const s = PB.snap, k = PB.kindOf(id);
    if (k === 'turbine') return `${PB.fmt(s.turbines[id][0], 2)} MW · ${s.turbines[id][1]}`;
    if (k === 'branch') return `${PB.fmt(s.branches[id][0], 2)} MW · ${PB.pct(s.branches[id][2])} · ${s.branches[id][3]}`;
    if (k === 'zone') return `${PB.fmt(s.zones[id][5], 2)} MW · ${PB.int(s.zones[id][0])} residents`;
    if (k === 'firm') return `${PB.fmt(s.firms[id][3], 2)} MW · ${PB.int(s.firms[id][1])} staff`;
    if (k === 'storage') return `${PB.fmt(s.storage[id][0], 2)} MW · SOC ${PB.pct(s.storage[id][1])}`;
    if (k === 'substation') { const v = s.buses[PB.static.substations[id][4]]; return `${PB.fmt(v && v[0], 3)} pu`; }
    if (k === 'link') return `${PB.fmt(s.totals.link, 1)} MW`;
    return '';
  }
  async function history() {
    if (Date.now() - lastHistory < 15000 || dockTab !== 'chart') return;
    lastHistory = Date.now();
    try { hourly = (await PB.call('/table', {name: 'history'})).hours; } catch {}
  }
  $('dockBody').addEventListener('click', ev => { const li = ev.target.closest('[data-ref]'); if (li && li.dataset.ref) { PB.select(li.dataset.ref); PB.map.focus(li.dataset.ref); } });
  document.querySelectorAll('[data-dock]').forEach(b => b.onclick = () => {
    dockTab = b.dataset.dock; document.querySelectorAll('[data-dock]').forEach(x => x.classList.toggle('on', x === b));
    document.body.classList.remove('dock-closed'); if (dockTab === 'chart') lastHistory = 0; history(); dock();
  });
  $('dockToggle').onclick = () => document.body.classList.toggle('dock-closed');

  // ------------------------------------------------------------ views
  function setView(v) {
    PB.view = v;
    document.querySelectorAll('#nav>button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
    $('mapWrap').hidden = v === 'economy'; $('econ').hidden = v !== 'economy';
    $('buildbar').hidden = v !== 'island'; $('layers').hidden = v === 'economy';
    if (v === 'economy') PB.econ.show(); else PB.map.setMode(v);
    cancelBuild();
  }
  document.querySelectorAll('#nav>button').forEach(b => b.onclick = () => setView(b.dataset.view));

  // ------------------------------------------------------------ build mode
  const MODELS = ['PB-2.3', 'PB-3.6', 'PB-5.6'];
  function buildbar() {
    const st = PB.static; if (!st) return;
    $('buildbar').innerHTML = `<h4>BUILD</h4><select id="bmodel" title="Turbine model">${MODELS.map(m => `<option>${m}</option>`).join('')}</select>
      <button data-b="turbine">⚑ Wind turbine</button><button data-b="storage">▤ Battery</button><button data-b="line">╱ 110 kV line</button>
      <button data-b="transformer">◫ Transformer</button><button id="engineering">Engineering…</button>`;
    $('buildbar').querySelectorAll('[data-b]').forEach(b => b.onclick = () => PB.emit('build-start', b.dataset.b, {}));
    $('engineering').onclick = () => PB.engineering.open();
  }
  function hint(text) { $('hint').textContent = text || ''; }
  function cancelBuild() { PB.building = null; hint(''); $('mapWrap').classList.remove('building'); $('buildbar').querySelectorAll('[data-b]').forEach(x => x.classList.remove('on')); }
  PB.on('build-start', (type, opts) => {
    if (PB.view !== 'island') setView('island');
    cancelBuild();
    PB.building = {type, model: $('bmodel') ? $('bmodel').value : 'PB-3.6'};
    $('buildbar').querySelector(`[data-b="${type}"]`)?.classList.add('on');
    $('mapWrap').classList.add('building');
    if (type === 'turbine') hint(`Click a site on land for a ${PB.building.model} turbine (Esc cancels).`);
    else if (type === 'line') hint('Click the first substation of the new 110 kV line.');
    else hint('Click a substation.');
    if (opts.station) PB.emit('build-click', null, opts.station);
    if (opts.at) PB.emit('build-click', opts.at, null);
  });
  PB.on('build-click', async (km, id) => {
    const b = PB.building; if (!b) return;
    if (b.type === 'turbine') return preview({type: 'turbine', model: b.model, x: +km[0].toFixed(3), y: +km[1].toFixed(3)});
    if (!id || !PB.static.substations[id]) { PB.toast('Choose a substation (yellow square).', true); return; }
    if (b.type === 'line') {
      if (!b.a) { b.a = id; hint(`From ${PB.name(id)}: now click the other end.`); return; }
      return preview({type: 'line', a: b.a, b: id, line_type: 'OHL110'});
    }
    if (b.type === 'transformer') return preview({type: 'transformer', station: id});
    if (b.type === 'storage') return storageForm(id);
  });
  function storageForm(station) {
    dialog(`<div class="eyebrow">BATTERY AT ${PB.esc(PB.name(station).toUpperCase())}</div><h2>NEW BATTERY</h2>
      <label>Power (MW) <input id="sp" type="number" min="1" max="100" value="20"></label>
      <label>Duration (hours) <input id="sh" type="number" min="0.5" max="8" step="0.5" value="2"></label>
      <label>Grid-forming converter <input id="sg" type="checkbox" checked></label>
      <p class="small muted">A grid-forming battery can keep the island energised when the mainland link is lost.</p>
      <div class="actions"><button class="button primary" id="dok">Check cost…</button><button class="button" id="dno">Cancel</button></div>`);
    $('dok').onclick = () => preview({type: 'storage', station, p_mw: Number($('sp').value), hours: Number($('sh').value), grid_forming: $('sg').checked});
    $('dno').onclick = () => { closeDialog(); cancelBuild(); };
  }
  async function preview(build) {
    let j;
    try { j = await PB.call('/preview', {build}); } catch (e) { PB.toast(e.message, true); return; }
    if (!j.ok) { PB.toast(j.error, true); return; }
    const p = j.plan; if (PB.building) PB.building.plan = p;
    dialog(`<div class="eyebrow">CONSTRUCTION PROJECT</div><h2>${PB.esc(p.title)}</h2>
      <div class="kv"><span>Capital cost</span><span>${PB.msek(p.cost / 1e6)}</span><span>Construction time</span><span>${p.days} days</span>
      <span>Connection</span><span>${PB.esc(p.connection)}</span><span>Powerbolaget cash</span><span>${PB.msek(PB.snap.kpi.pb_cash)}</span></div>
      <p class="small muted">Paid monthly as work progresses; part of it goes to the island's construction firm. If cash runs short, the gap is booked as external financing. The power flow decides afterwards whether the network copes.</p>
      <div class="actions"><button class="button primary" id="dok">Start construction</button><button class="button" id="dno">Cancel</button></div>`);
    $('dok').onclick = async () => { closeDialog(); const ok = await PB.command({kind: 'build', build}); if (ok) { cancelBuild(); setDock('projects'); } };
    $('dno').onclick = () => { closeDialog(); if (PB.building && PB.building.type !== 'turbine') cancelBuild(); };
  }
  PB.on('engineering-preview', preview);
  function setDock(t) { document.querySelector(`[data-dock="${t}"]`)?.click(); }

  // ------------------------------------------------------------ dialogs and menu
  function dialog(html) { $('dialogBody').innerHTML = html; if (!$('dialog').open) $('dialog').showModal(); }
  function closeDialog() { if ($('dialog').open) $('dialog').close(); }
  $('menuBtn').onclick = ev => { ev.stopPropagation(); $('menu').hidden = !$('menu').hidden; };
  document.addEventListener('click', () => { $('menu').hidden = true; });
  $('menu').onclick = async ev => {
    const m = ev.target.dataset.menu; if (!m) return;
    $('menu').hidden = true;
    try {
      if (m === 'save') await PB.saveNow(false);
      if (m === 'export') PB.download(await PB.saveNow(false));
      if (m === 'import') $('importFile').click();
      if (m === 'new') newGame();
      if (m === 'about') about();
    } catch (e) { PB.toast(e.message, true); }
  };
  $('importFile').onchange = async ev => {
    const f = ev.target.files[0]; ev.target.value = ''; if (!f) return;
    try {
      const save = JSON.parse(await f.text());
      PB.adopt(await PB.api('/session/load', {save}), `Loaded ${save.saved || 'save file'}.`);
      await PB.store.put(save); PB.select(null);
    } catch (e) { PB.toast(e.message || 'This is not a Powerbolaget save file.', true); }
  };
  function newGame() {
    dialog(`<div class="eyebrow">NEW GAME</div><h2>START OVER</h2><p class="small">The island starts again on 1 January, year 1 of the Fantasy Era. The random seed sets the weather and every chance event.</p>
      <label>Seed <input id="nseed" type="number" min="0" max="1000000" value="${Math.floor(Math.random() * 1000000)}"></label>
      <p class="small muted">This replaces the game saved in this browser. Export it first to keep it.</p>
      <div class="actions"><button class="button danger" id="dok">Start new game</button><button class="button" id="dno">Cancel</button></div>`);
    $('dno').onclick = closeDialog;
    $('dok').onclick = async () => {
      closeDialog();
      try { PB.adopt(await PB.api('/session', {seed: Number($('nseed').value) || 0}), 'A new island begins.'); PB.select(null); await PB.saveNow(); }
      catch (e) { PB.toast(e.message, true); }
    };
  }
  function about() {
    dialog(`<div class="eyebrow">MODEL AND SOURCES</div><h2>HOW GUTNÖ WORKS</h2>
      <p class="small">Gutnö is fictional: it borrows Gotland's scale, climate and economic geography, but its firms, substations, wiring and settings are invented. It is not a digital twin of any real grid.</p>
      <h3>ENERGY</h3><p class="small">AC power flow every simulated minute (OpenDSS through OpenDSSDirect.py) on the full 110/33/20/0.69 kV network with every turbine and its unit transformer. Jensen wakes inside each farm. An automatic operator balances the island with the mainland link, batteries, wind curtailment and, last, load shedding by priority. Protection trips on faults and overloads; overhead lines reclose; repairs take time. Not modelled yet: electromechanical and electromagnetic transients, frequency dynamics, unbalanced faults.</p>
      <h3>SOCIETY AND ECONOMY</h3><p class="small">About 200 POPs (groups with counts) in 20 zones, plus visitors, holiday-home users and seasonal workers. Firms forecast demand, plan production by the hour, run real equipment, hire and invest by themselves. Money moves through a double-entry ledger. Every coefficient is an assumption listed in app/params.py.</p>
      <h3>DATA</h3><p class="small">Climate: NASA POWER monthly climatology 2001–2025 at 57.5° N, 18.5° E, used only to calibrate a continuous weather model. Everything else is synthetic.</p>
      <div class="actions"><button class="button" id="dno">Close</button></div>`);
    $('dno').onclick = closeDialog;
  }

  // ------------------------------------------------------------ controls
  $('play').onclick = () => { PB.running = !PB.running; updatePlay(); };
  document.querySelectorAll('[data-speed]').forEach(b => b.onclick = () => { PB.speed = Number(b.dataset.speed); paceEma = null; document.querySelectorAll('[data-speed]').forEach(x => x.classList.toggle('on', x === b)); });
  document.querySelectorAll('[data-theme-mode]').forEach(b => b.onclick = () => PB.setTheme(b.dataset.themeMode));
  $('alerts').onclick = () => { PB.unread = 0; setDock('events'); topbar(PB.snap); };
  document.addEventListener('keydown', ev => {
    if (ev.target.matches('input,select,textarea')) return;
    if (ev.key === ' ') { ev.preventDefault(); $('play').click(); }
    else if (ev.key === 'Escape') { cancelBuild(); closeDialog(); }
    else if (['1', '2', '3'].includes(ev.key)) setView(['island', 'grid', 'economy'][Number(ev.key) - 1]);
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) PB.saveNow().catch(() => {}); });
  PB.on('snapshot', s => { topbar(s); dock(); history(); });
  PB.on('static', () => { buildbar(); PB.map.renderLayers(); });
  PB.on('pins', dock);

  // ------------------------------------------------------------ boot
  (async () => {
    try {
      PB.land = await PB.api('/land');
      const save = await PB.store.get();
      if (save) {
        $('bootMsg').textContent = `Loading ${save.saved}…`;
        try { PB.adopt(await PB.api('/session/load', {save})); }
        catch (e) { PB.adopt(await PB.api('/session', {seed: 1}), `Your saved game could not be loaded (${e.message}); a new game has started.`); }
      } else {
        PB.adopt(await PB.api('/session', {seed: 1}));
        if (!await PB.store.persistent()) PB.toast('This browser blocks local storage: export your game before closing the page.', true);
        await PB.saveNow().catch(() => {});
      }
      setView('island'); updatePlay();
      $('ver').textContent = `GUTNÖ · ${PB.static.version}`;
      $('boot').classList.add('gone');
      loop();
    } catch (e) { $('bootMsg').textContent = 'The server could not start the island: ' + e.message; }
  })();
})();
