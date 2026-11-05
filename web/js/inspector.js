'use strict';
// Context inspector (spec 9.2-9.5): first the island overview, then whatever the player selects.
// Every number comes from the model; nothing here is estimated by the client.
PB.inspector = (() => {
  const el = PB.$('inspector');
  let data = null, timer = null;
  const kv = rows => `<div class="kv">${rows.filter(Boolean).map(([k, v]) => `<span>${PB.esc(k)}</span><span>${v}</span>`).join('')}</div>`;
  const chip = (text, cls = '') => `<span class="chip ${cls}">${PB.esc(text)}</span>`;
  const bar = (x, cls = '') => `<div class="bar ${x > 1 ? 'bad' : x > .9 ? 'warn' : cls}"><i style="width:${Math.min(100, 100 * (x || 0))}%"></i></div>`;
  const link = (id, text) => `<a href="#" data-goto="${PB.esc(id)}">${PB.esc(text ?? PB.name(id))}</a>`;
  const statusChip = s => chip(s, ['ok', 'running', 'operating'].includes(s) ? 'ok' : ['fault', 'tripped', 'repair', 'dead', 'construction'].includes(s) ? 'bad' : 'warn');
  const pin = id => `<button class="button" data-pin="${PB.esc(id)}">${PB.pins.includes(id) ? 'Unpin' : 'Pin'}</button>`;

  function overview() {
    const s = PB.snap, st = PB.static; if (!s) return '';
    const t = s.totals, k = s.kpi;
    const farms = Object.entries(st.farms).map(([id, f]) => {
      const ids = Object.entries(st.turbines).filter(([, x]) => x[3] === id).map(([tid]) => tid);
      const ok = ids.filter(tid => s.turbines[tid] && s.turbines[tid][1] === 'ok').length, mw = ids.reduce((a, tid) => a + (s.turbines[tid] ? s.turbines[tid][0] : 0), 0);
      return `<li class="click" data-goto="${ids[0] || ''}">${PB.esc(f[0])}<span class="muted small" style="margin-left:auto">${ok}/${ids.length} running · ${PB.fmt(mw, 1)} MW</span></li>`;
    }).join('');
    const alerts = PB.logs.filter(e => ['protection', 'fault', 'shedding'].includes(e.kind)).slice(-5).reverse()
      .map(e => `<li><time>${PB.esc(e.label.split(' · ').slice(1).join(' '))}</time>${PB.esc(e.text)}</li>`).join('') || '<li class="muted">No recent faults.</li>';
    return `<div class="eyebrow">${PB.esc(st.island.name)} · ${PB.esc(st.island.era)}</div><h2>ISLAND NOW</h2>
      <p class="small muted">The island runs on its own: weather, residents, visitors, firms and faults keep changing. You plan and operate Powerbolaget's grid. Click anything on the map.</p>
      ${kv([['Residents', PB.int(k.residents)], ['Visitors and holiday homes', PB.int(k.tourists + k.holiday)], ['Unemployment', PB.pct(k.unemployed / Math.max(1, k.labour), 1)],
        ['Demand served', `${PB.fmt(t.load, 1)} of ${PB.fmt(t.requested, 1)} MW`], ['Wind output', `${PB.fmt(t.wind, 1)} of ${PB.fmt(t.wind_avail, 1)} MW available`],
        ['Mainland exchange', `${PB.fmt(t.link, 1)} MW (capacity ${PB.fmt(t.link_cap, 0)})`], ['· HVDC / HVAC', `${PB.fmt(t.link_dc, 1)} / ${PB.fmt(t.link_ac, 1)} MW`],
        ['Voltage reference', PB.esc(t.reference)], ['Batteries', PB.mw(t.battery)], ['Network losses', PB.mw(t.losses)],
        ['Mainland price', `${PB.fmt(t.price, 2)} SEK/kWh`], ['Household tariff', `${PB.fmt(t.tariff, 2)} SEK/kWh`],
        ['Powerbolaget cash', PB.msek(k.pb_cash)], ['External financing', PB.msek(k.financing)]])}
      <h3>WIND FARMS</h3><ul class="list">${farms}</ul>
      <h3>LATEST FAULTS</h3><ul class="list">${alerts}</ul>
      <h3>SIMULATION</h3>${kv([['Server time per simulated hour', s.perf.ms_per_sim_hour ? PB.fmt(s.perf.ms_per_sim_hour, 0) + ' ms' : '—'],
        ['Power flow p50 / p95', `${PB.fmt(s.perf.solve_p50, 2)} / ${PB.fmt(s.perf.solve_p95, 2)} ms`], ['Numerical failures', PB.int(s.perf.failures)],
        ['POP objects', `${PB.int(k.pops)} of 10,000`], ['Firms', PB.int(k.firms)]])}`;
  }

  function render() {
    if (!PB.selected) { el.innerHTML = overview(); return; }
    const d = data; if (!d) { el.innerHTML = '<p class="muted">Loading…</p>'; return; }
    const head = (eyebrow, title, status) => `<div class="eyebrow">${PB.esc(eyebrow)}</div><h2>${PB.esc(title)}</h2>${status ? statusChip(status) : ''}`;
    let html = '';
    if (d.type === 'turbine') {
      html = head(`Wind turbine · ${d.farm}`, d.title, d.status) + kv([['Output', PB.mw(d.p)], ['Rated power', PB.mw(d.mw)], ['Hub wind (after wakes)', PB.fmt(d.hub_wind, 1) + ' m/s'],
        ['Cut-in / rated / cut-out', `${d.cut_in} / ${d.rated_speed} / ${d.cut_out} m/s`], ['Rotor / hub height', `${d.rotor} / ${d.hub} m`],
        ['Terminal voltage', PB.fmt(d.bus_v, 4) + ' pu'], ['Age', PB.fmt(d.age, 1) + ' years'], ['Last maintenance', PB.esc(d.maintained)]])
        + `<h3>ENERGY, LAST ${d.history.length} H</h3><canvas class="mini" data-hist="mwh"></canvas>`
        + `<div class="actions"><button class="button" data-cmd="maintenance">${d.status === 'maintenance' ? 'End maintenance' : 'Planned maintenance (2 days)'}</button>${pin(d.id)}</div>`
        + `<p class="small muted">Faults become more likely with age and time since maintenance; storms and icing add risk.</p>`;
    } else if (d.type === 'branch') {
      const f = d.flow || [0, 0, 0, 0, 0];
      html = head(d.label, d.title, d.status) + kv([['From', PB.esc(d.a)], ['To', PB.esc(d.b)], d.km ? ['Length', PB.fmt(d.km, 2) + ' km' + (d.circuits > 1 ? ` · ${d.circuits} circuits` : '')] : null,
        ['Rating', PB.fmt(d.rating_mva, 1) + ' MVA' + (d.amps ? ` · ${PB.int(d.amps)} A` : '')], d.tap ? ['Tap (low-voltage side)', PB.fmt(d.tap, 4)] : null,
        ['P / Q at start', `${PB.fmt(f[0], 2)} MW / ${PB.fmt(f[1], 2)} Mvar`], ['P / Q at end', `${PB.fmt(f[2], 2)} MW / ${PB.fmt(f[3], 2)} Mvar`],
        ['Losses', PB.fmt((f[0] + f[2]) * 1000, 0) + ' kW'], ['Current', PB.int(f[4]) + ' A'], ['Loading', PB.pct(d.loading, 1)],
        d.fault ? ['Last protection action', PB.esc(d.fault)] : null, d.repair_until ? ['Repair crew done', PB.esc(d.repair_until)] : null,
        d.section_out != null ? ['Faulted section isolated', PB.pct(d.section_out, 0) + ' of customers off until repair'] : null])
        + bar(d.loading) + `<h3>LOADING, LAST ${d.history.length} H</h3><canvas class="mini" data-hist="load"></canvas>`
        + `<div class="actions">${d.actions.includes('switch') ? `<button class="button ${d.status === 'open' ? 'primary' : 'danger'}" data-cmd="switch">${d.status === 'open' ? 'Close breaker' : 'Open breaker'}</button>` : ''}${pin(d.id)}</div>`;
    } else if (d.type === 'bus') {
      html = head(`Busbar · ${d.kv} kV`, d.title, d.energized ? 'ok' : 'dead') + kv([['Voltage', PB.fmt(d.v, 4) + ' pu'], ['Angle', PB.fmt(d.angle, 2) + '°']])
        + `<h3>CONNECTED LOADS</h3><ul class="list">${d.loads.map(l => `<li>${PB.esc(l.name)} <span class="muted small" style="margin-left:auto">${PB.fmt(l.p, 2)} MW · ${PB.pct(l.served)} served · priority ${l.priority}</span></li>`).join('') || '<li class="muted">None</li>'}</ul>`
        + `<h3>BRANCHES</h3><ul class="list">${d.branches.map(b => `<li class="click" data-goto="${b}">${PB.esc(PB.name(b))}</li>`).join('')}</ul>`;
    } else if (d.type === 'substation') {
      html = head('Substation 110/20 kV', d.title, null) + kv([['110 kV busbar', PB.fmt(d.v_hv, 4) + ' pu'], ['20 kV busbar', PB.fmt(d.v_mv, 4) + ' pu']])
        + `<h3>TRANSFORMERS</h3><ul class="list">${d.transformers.map(t => `<li class="click" data-goto="${t.id}">${PB.esc(PB.name(t.id))}<span class="small muted" style="margin-left:auto">${PB.pct(t.loading)} · tap ${PB.fmt(t.tap, 4)} · ${t.status}</span></li>`).join('')}</ul>`
        + `<div class="actions"><button class="button" data-build="storage" data-station="${d.id}">Build battery here…</button><button class="button" data-build="transformer" data-station="${d.id}">Add 40 MVA unit…</button>${pin(d.id)}</div>`
        + `<p class="small muted">On-load tap changers keep the 20 kV busbar between 1.00 and 1.04 pu.</p>`;
    } else if (d.type === 'zone') {
      const comp = d.load, total = Object.values(comp).reduce((a, b) => a + b, 0) || 1;
      const colors = {residential: '--blue', services: '--accent', public: '--teal', lodging: '--orange', farm: '--green', industry: '--gray'};
      html = head(`Economic zone · ${d.kind}`, d.title, null) + kv([['Residents', PB.int(d.residents)], ['Households / homes', `${PB.int(d.households)} / ${PB.int(d.housing_units)}`],
        ['Visitors in lodging', PB.int(d.tourists) + ` (beds ${PB.int(d.beds)})`], ['Holiday-home users', PB.int(d.holiday) + ` (homes ${PB.int(d.holiday_homes)})`],
        ['Seasonal workers', PB.int(d.seasonal)], ['Labour force / unemployed', `${PB.int(d.working)} / ${PB.int(d.unemployed)} (${PB.pct(d.unemployed / Math.max(1, d.working), 1)})`],
        ['Electric heating', `${PB.pct(d.heating.direct)} direct · ${PB.pct(d.heating.heat_pump)} heat pumps`], ['Indoor temperature', PB.fmt(d.indoor_c, 1) + ' °C'],
        ['Customer outage, 30 days', PB.fmt(d.outage_h_30d, 2) + ' h'], ['20 kV supply voltage', PB.fmt(d.bus_v, 4) + ' pu']])
        + `<h3>LOAD NOW · ${PB.mw(total)}</h3><div class="stack">${Object.entries(comp).map(([k, v]) => `<i title="${k} ${PB.fmt(v, 2)} MW" style="width:${100 * v / total}%;background:var(${colors[k] || '--gray'})"></i>`).join('')}</div>`
        + `<div class="small">${Object.entries(comp).map(([k, v]) => `<span style="color:var(${colors[k] || '--gray'})">■</span> ${k} ${PB.fmt(v, 2)}`).join(' · ')}</div>`
        + `<h3>HOUSEHOLD ENERGY, LAST ${d.history.length} H</h3><canvas class="mini" data-hist="pair"></canvas>`
        + `<h3>POPS</h3><ul class="list">${d.pops.map(p => `<li class="click" data-goto="${p.id}">${PB.esc(p.title)}<span class="small muted" style="margin-left:auto">${PB.int(p.count)}${p.employed ? ` · ${PB.int(p.employed)} employed` : ''}</span></li>`).join('')}</ul>`
        + `<h3>FIRMS</h3><ul class="list">${d.firms.map(f => `<li class="click" data-goto="${f.id}">${PB.esc(f.name)}<span class="small muted" style="margin-left:auto">${PB.int(f.staff)} staff</span></li>`).join('')}</ul>`
        + `<div class="actions">${pin(d.id)}</div>`;
    } else if (d.type === 'firm') {
      html = head(`${d.kind} · ${PB.name(d.zone)}`, d.title, d.status) + kv([['Staff / wanted', `${PB.int(d.staff)} / ${PB.int(d.desired_staff)}`], ['Cash', PB.msek(d.cash / 1e6)],
        d.output ? ['Sells', `${PB.esc(d.output)} at ${PB.fmt(d.price, 0)} SEK`] : null, ['Utilisation (EMA)', PB.pct(d.util)], ['Margin (EMA)', PB.pct(d.margin)],
        ['Electricity now', PB.mw(d.power)], d.beds ? ['Beds', PB.int(d.beds)] : null, d.herd ? ['Herd (cow equivalents)', PB.int(d.herd)] : null,
        ['Yesterday: produced / sold', `${PB.fmt(d.yesterday.produced, 1)} / ${PB.fmt(d.yesterday.sold, 1)}`], ['Yesterday: revenue', PB.int(d.yesterday.revenue) + ' SEK'],
        ['Yesterday: power cost', PB.int(d.yesterday.power_cost) + ' SEK'], ['Yesterday: outage', PB.int(d.yesterday.outage_min) + ' min']])
        + (Object.keys(d.inventory).length ? `<h3>STOCK</h3>${kv(Object.entries(d.inventory).map(([k, v]) => [k, PB.fmt(v, 0)]))}` : '')
        + (d.equipment.length ? `<h3>EQUIPMENT</h3><ul class="list">${d.equipment.map(e => `<li>${PB.esc(e.name)} ${statusChip(e.state)}<span class="small muted" style="margin-left:auto">${PB.fmt(e.p, 2)}/${PB.fmt(e.rated, 2)} MW${e.trips ? ` · ${e.trips} trips` : ''}</span></li>`).join('')}</ul>` : '')
        + `<p class="small muted">A firm decides for itself: it plans production from its own forecast, prices, stock and staff. Powerbolaget can only influence it through supply and price.</p>`
        + `<div class="actions">${link(d.zone, 'Go to zone')} ${pin(d.id)}</div>`;
    } else if (d.type === 'pop') {
      html = head(`POP · ${d.kind}`, d.title, null) + kv([['People', PB.int(d.count)], d.group ? ['Group', PB.esc(d.group)] : null, ['Employed', PB.int(d.employed)], ['Inactive (students, sick, at home)', PB.int(d.inactive)],
        ['Money held', PB.int(d.wealth) + ' SEK'], ['Income (EMA)', PB.int(d.income_day) + ' SEK/day'], ['Price elasticity', d.elasticity]])
        + `<h3>EMPLOYERS</h3><ul class="list">${Object.entries(d.jobs).map(([f, n]) => `<li class="click" data-goto="${f}">${PB.esc(PB.name(f))}<span class="small muted" style="margin-left:auto">${PB.int(n)}</span></li>`).join('') || '<li class="muted">None</li>'}</ul>`
        + `<p class="small muted">A POP is a group with a count, not a person. Moves, births, deaths and jobs change the counts.</p>`;
    } else if (d.type === 'storage') {
      html = head(`Battery${d.grid_forming ? ' · grid-forming' : ''}`, d.title, d.status) + kv([['Power now', PB.mw(d.p) + (d.p > 0 ? ' discharging' : d.p < 0 ? ' charging' : '')],
        ['Rating', `${PB.mw(d.p_mw)} / ${PB.fmt(d.e_mwh, 0)} MWh`], ['State of charge', PB.pct(d.soc, 1)], ['Mode', d.mode], ['Forming the island grid', d.forming ? 'yes' : 'no'], ['Energy throughput', PB.fmt(d.throughput_mwh, 0) + ' MWh']])
        + bar(d.soc) + `<h3>OPERATION</h3><label class="small">Mode <select id="bmode">${['auto', 'hold', 'charge', 'discharge'].map(m => `<option ${m === d.mode ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
        <label class="small">Set point (MW) <input id="bset" type="number" min="0" max="${d.p_mw}" step="1" value="${d.setpoint || d.p_mw}"></label>
        <div class="actions"><button class="button primary" data-cmd="storage">Apply</button>${pin(d.id)}</div>
        <p class="small muted">Auto: shaves import peaks, absorbs surplus wind and follows price. A grid-forming battery can carry the island when the link is lost.</p>`;
    } else if (d.type === 'link') {
      const ac = d.hvac, dc = d.hvdc;
      html = head('Connections to the mainland', d.title, null) + kv([['Exchange', `${PB.fmt(d.p, 1)} MW ${d.p >= 0 ? 'import' : 'export'}`], ['Available capacity', PB.mw(d.capacity)],
        ['Voltage reference', PB.esc(d.reference)], ['Operating margin', PB.pct(d.margin)]])
        + `<h3>HVDC · ${PB.fmt(dc.p, 1)} MW</h3><ul class="list">${dc.poles.map(p => `<li>${PB.esc(p.name || p.id)} ${statusChip(p.status)}<span class="small muted" style="margin-left:auto">${p.mw} MW</span></li>`).join('')}</ul>`
        + `<h3>HVAC 220 KV · ${PB.esc(ac.name.toUpperCase())} · ${ac.capacity ? PB.fmt(ac.p, 1) + ' MW' : 'PLANNED'}</h3>`
        + `<ul class="list">${ac.cables.map(c => `<li class="click" data-goto="${c.id}">${PB.esc(PB.name(c.id))} ${statusChip(c.status)}<span class="small muted" style="margin-left:auto">${c.status === 'ok' ? PB.pct(c.loading) : ''}</span></li>`).join('')}</ul>`
        + `<ul class="list">${ac.stages.map(st => `<li>${st.done ? '✓' : '○'} ${PB.esc(st.date)}<span class="small muted" style="margin-left:auto">${st.cables} cable${st.cables > 1 ? 's' : ''} · ${PB.int(st.mw)} MW</span></li>`).join('')}</ul>`
        + `<p class="small muted">The national grid operator builds the HVAC link (two 220 kV AC subsea cables, after the public Gotland connection plan: in service from 2031 = FE 6, 440 MW planned). It starts at a limited rating and grows as the mainland grid is reinforced. Once in service, the island is synchronous with the mainland and the HVDC runs on a schedule. If every connection is lost, only a grid-forming battery keeps the lights on.</p>`
        + `<label class="small">Operating margin (%) <input id="lmargin" type="number" min="0" max="30" step="1" value="${Math.round(d.margin * 100)}"></label>
        <div class="actions"><button class="button" data-cmd="margin">Apply</button>${pin('link')}</div>`;
    } else if (d.type === 'parcel') {
      const t = d.turbine_site || {};
      html = head(`Parcel · ${d.size_km} × ${d.size_km} km`, d.land.toUpperCase(), null)
        + (d.zone ? kv([['Zone', link(d.zone, d.zone_name)], ['People living here (est.)', PB.int(d.people)], ['Nearest town', `${PB.esc(d.nearest_town)} · ${PB.fmt(d.town_km, 1)} km`],
          ['Distance to the sea', PB.fmt(d.coast_km, 2) + ' km'], ['Mean wind at 100 m', PB.fmt(d.wind_mean_100m, 2) + ' m/s'], ['Wind at 100 m now', PB.fmt(d.wind_now_100m, 1) + ' m/s'],
          ['Nearest substation', `${PB.esc(d.substation)} · ${PB.fmt(d.substation_km, 1)} km`], ['Coordinates', `${PB.fmt(d.x, 2)}, ${PB.fmt(d.y, 2)} km`]])
          + (d.objects.length ? `<h3>ON THIS PARCEL</h3><ul class="list">${d.objects.map(o => `<li class="click" data-goto="${o}">${PB.esc(PB.name(o))}</li>`).join('')}</ul>` : '')
          + `<h3>WIND TURBINE SITE</h3>`
          + `<ul class="list">${(d.yields || []).map(y => `<li>${PB.esc(y.model)} · hub ${y.hub} m<span class="small muted" style="margin-left:auto">${PB.fmt(y.mean, 1)} m/s · ${PB.pct(y.cf)} · ${PB.fmt(y.gwh, 1)} GWh/yr</span></li>`).join('')}</ul>`
          + `<p class="small muted">Long-term mean wind from the Global Wind Atlas; expected output before wakes, outages and curtailment.</p>`
          + (t.ok ? `<p class="small ok">Suitable for a turbine.</p>${kv([['PB-3.6 incl. connection', PB.msek(t.cost)], ['Construction time', t.days + ' days'], ['Connection', PB.esc(t.connection)]])}
              <div class="actions"><button class="button primary" data-buildhere="1">Build a turbine here…</button></div>` : `<p class="small warn">${PB.esc(t.reason)}</p>`)
          : `<p class="small muted">${PB.esc(d.note || '')}</p>`);
    } else if (d.type === 'project') {
      html = head(`Project · ${d.kind}`, d.title, null) + bar(d.progress) + kv([['Progress', PB.pct(d.progress)], ['Ready', PB.esc(d.finish)], ['Cost / paid', `${PB.msek(d.cost)} / ${PB.msek(d.paid)}`]]);
    }
    el.innerHTML = `<button class="button" data-back="1" style="float:right">✕</button>` + html;
    el.querySelectorAll('canvas.mini').forEach(c => {
      const kind = c.dataset.hist, h = d.history || [];
      const series = kind === 'pair' ? [{name: 'served', color: PB.css('--blue'), values: h.map(v => Array.isArray(v) ? v[0] : v)}, {name: 'unserved', color: PB.css('--red'), values: h.map(v => Array.isArray(v) ? v[1] : 0)}]
        : [{name: kind === 'load' ? 'loading' : 'MWh', color: kind === 'load' ? PB.css('--orange') : PB.css('--green'), values: h.map(v => Array.isArray(v) ? v[0] : v)}];
      PB.chart.draw(c, series, {min: 0, steps: true});
    });
  }

  async function refresh() {
    if (!PB.selected) { render(); return; }
    try {
      if (PB.selected.startsWith('parcel_')) { const [x, y] = PB.parcelXY(PB.selected); data = await PB.call('/parcel', {x, y}); }
      else data = await PB.call('/entity', {id: PB.selected});
      render();
    }
    catch (e) { if (e.status === 404) { PB.selected = null; data = null; render(); } }
  }
  el.addEventListener('click', async ev => {
    const t = ev.target.closest('[data-goto],[data-cmd],[data-pin],[data-back],[data-build],[data-buildhere]'); if (!t) return;
    ev.preventDefault();
    if (t.dataset.back) { PB.select(null); return; }
    if (t.dataset.goto) { PB.select(t.dataset.goto); PB.map.focus(t.dataset.goto); return; }
    if (t.dataset.pin) { PB.togglePin(t.dataset.pin); render(); return; }
    if (t.dataset.build) { PB.emit('build-start', t.dataset.build, {station: t.dataset.station}); return; }
    if (t.dataset.buildhere) { PB.emit('build-start', 'turbine', {at: [data.x, data.y]}); return; }
    const d = data, c = t.dataset.cmd;
    const cmd = c === 'maintenance' ? {kind: 'maintenance', target: d.id}
      : c === 'switch' ? {kind: 'switch', target: d.id, closed: d.status === 'open'}
      : c === 'storage' ? {kind: 'storage_mode', target: d.id, mode: PB.$('bmode').value, setpoint: Number(PB.$('bset').value)}
      : c === 'margin' ? {kind: 'settings', link_margin: Number(PB.$('lmargin').value) / 100} : null;
    if (cmd) await PB.command(cmd);
  });
  PB.on('select', () => { data = null; clearTimeout(timer); refresh(); });
  PB.on('snapshot', () => { if (!PB.selected) render(); });
  setInterval(() => { if (PB.selected && !document.hidden) refresh(); }, 2500);
  return {refresh, render};
})();
