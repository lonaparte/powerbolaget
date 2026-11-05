'use strict';
// Socio-economic statistics (spec 9.4): regions, POPs, firms, markets, finance and demography.
// Aggregates by default; the full POP list is searchable rather than shown all at once.
PB.econ = (() => {
  const el = PB.$('econ');
  const TABS = [['overview', 'OVERVIEW'], ['zones', 'REGIONS'], ['pops', 'POPS'], ['firms', 'FIRMS'], ['markets', 'MARKETS'], ['finance', 'FINANCE'], ['demography', 'DEMOGRAPHY']];
  let tab = 'overview', data = {}, sort = {}, filter = '',page=0;
  function table(cols, rows, clickCol = 0, opts = {}) {
    const s = sort[tab] || {col: -1, dir: 1};
    let body = rows.filter(r => !filter || r.join(' ').toLowerCase().includes(filter.toLowerCase()));
    if (s.col >= 0) body = [...body].sort((a, b) => (typeof a[s.col] === 'number' && typeof b[s.col] === 'number' ? a[s.col] - b[s.col] : String(a[s.col]).localeCompare(String(b[s.col]))) * s.dir);
    const pages=Math.max(1,Math.ceil(body.length/100));page=PB.clamp(page,0,pages-1);const count=body.length;
    body=body.slice(page*100,(page+1)*100);
    const fmt = v => typeof v === 'number' ? (Math.abs(v) < 1 && v !== 0 ? PB.fmt(v, 3) : Number.isInteger(v) ? PB.int(v) : PB.fmt(v, 1)) : PB.esc(v ?? '—');
    const hide = opts.hide || [];
    return `<div class="table-wrap"><table><thead><tr>${cols.map((c, i) => hide.includes(i) ? '' : `<th data-sort="${i}" class="${i <= 1 ? 'l' : ''}">${PB.esc(c)}${s.col === i ? (s.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
      <tbody>${body.map(r => `<tr data-goto="${PB.esc(r[clickCol])}">${r.map((v, i) => hide.includes(i) ? '' : `<td class="${i <= 1 ? 'l' : ''}">${fmt(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${pages>1?`<div class="actions"><button class="button" data-page="${page-1}" ${page===0?'disabled':''}>Previous</button><span>${page+1} / ${pages} · ${PB.int(count)} rows</span><button class="button" data-page="${page+1}" ${page===pages-1?'disabled':''}>Next</button></div>`:''}`;
  }
  async function load() {
    const name = tab === 'overview' ? 'history' : tab;
    try { data[tab] = await PB.call('/table', {name}); } catch (e) { data[tab] = {error: e.message}; }
    render();
  }
  function render() {
    const d = data[tab];
    let html = `<div class="econ-tabs">${TABS.map(([k, t]) => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${t}</button>`).join('')}
      ${['pops', 'firms', 'zones'].includes(tab) ? `<input id="efilter" type="search" placeholder="Filter…" value="${PB.esc(filter)}" style="margin-left:auto">` : ''}</div>`;
    if (!d) html += '<p class="muted">Loading…</p>';
    else if (d.error) html += `<p class="bad">${PB.esc(d.error)}</p>`;
    else if (tab === 'overview') html += overview(d);
    else if (tab === 'zones' || tab === 'firms') html += table(d.columns, d.rows, 0, {hide: [0]});
    else if (tab === 'pops') html += `<p class="small muted">${PB.int(d.total)} POP objects (cap 10,000). Each is a group with a count.</p>` + table(d.columns, d.rows, 0, {hide: [0]});
    else if (tab === 'markets') html += `<h3>ISLAND MARKETS (YESTERDAY)</h3>` + table(d.columns, d.rows, 0) + `<h3>LOCAL SERVICES, LODGING AND FERRY</h3>` + table(d.services_columns, d.services, 0, {hide: [0]})
      + `<p class="small muted">Island prices move between mainland export and import parity. Electricity is not traded here: it is billed from metered supply at Powerbolaget's tariffs.</p>`;
    else if (tab === 'finance') html += finance(d);
    else if (tab === 'demography') html += demography(d);
    el.innerHTML = html;
    el.querySelectorAll('canvas[data-series]').forEach(c => drawSeries(c));
    const f = PB.$('efilter'); if (f) { f.oninput = () => { filter = f.value;page=0; const pos = f.selectionStart; render(); const g = PB.$('efilter'); g.focus(); g.setSelectionRange(pos, pos); }; }
  }
  let hist = null;
  function overview(d) {
    hist = d;
    const k = PB.snap.kpi;
    return `<div class="kpis">${[['Residents', PB.int(k.residents)], ['Visitors', PB.int(k.tourists)], ['Holiday-home users', PB.int(k.holiday)],
      ['Unemployment', PB.pct(k.unemployed / Math.max(1, k.labour), 1)], ['Powerbolaget cash', PB.msek(k.pb_cash)], ['External financing', PB.msek(k.financing)],
      ['POP objects', PB.int(k.pops)], ['Firms', PB.int(k.firms)]].map(([a, b]) => `<div class="kpi"><small>${a}</small><b>${b}</b></div>`).join('')}</div>
      <div class="card"><div class="eyebrow">ELECTRICITY PER DAY (MWH)</div><canvas class="mini" style="height:140px" data-series="energy"></canvas></div>
      <div class="card"><div class="eyebrow">PEOPLE PER DAY</div><canvas class="mini" style="height:140px" data-series="people"></canvas></div>
      <div class="card"><div class="eyebrow">MAINLAND PRICE (SEK/KWH, DAILY MEAN)</div><canvas class="mini" style="height:110px" data-series="price"></canvas></div>
      <p class="small muted">No score and no win condition: the island's state is reported as it is. Every value can be traced in the inspector.</p>`;
  }
  function drawSeries(c) {
    const days = (hist && hist.days) || [], kind = c.dataset.series, css = PB.css;
    const v = key => days.map(x => x[key]);
    const series = kind === 'energy' ? [{name: 'demand', color: css('--blue'), values: v('load_mwh')}, {name: 'wind', color: css('--green'), values: v('wind_mwh')},
      {name: 'import', color: css('--violet'), values: v('import_mwh')}, {name: 'export', color: css('--teal'), values: v('export_mwh')}, {name: 'unserved', color: css('--red'), values: v('unserved_mwh')}]
      : kind === 'people' ? [{name: 'visitors', color: css('--orange'), values: v('tourists')}, {name: 'unemployed', color: css('--red'), values: v('unemployed')}]
      : [{name: 'price', color: css('--accent'), values: v('price')}];
    PB.chart.draw(c, series, {min: 0, steps: true, xlabels: days.length ? [`day ${Math.floor(days[0].t / 1440) + 1}`, `day ${Math.floor(days[days.length - 1].t / 1440) + 1}`] : null});
  }
  function finance(d) {
    const top = d.totals.slice(0, 40);
    const c=d.conservation,goods=c?Object.entries(c.goods||{}).map(([g,x])=>[g,x.unit,x.stock,x.expected,x.residual]):[];
    const maxWater=c?Math.max(0,...Object.values(c.water||{}).map(Math.abs)):null;
    const checks=c?`<h3>CONSERVATION CHECKS · DAY ${Math.floor(c.t/1440)}</h3>
      <div class="kv"><span>Money-ledger residual</span><span>${Number(c.money).toExponential(3)} SEK</span><span>Largest goods residual</span><span>${Math.max(0,...goods.map(x=>Math.abs(x[4]))).toExponential(3)}</span><span>Largest water residual</span><span>${maxWater.toExponential(3)} m³</span></div>
      ${table(['good','unit','actual stock','identity expected','residual'],goods,0)}`:'<p class="small muted">Conservation checks appear after the first completed day.</p>';
    return `<div class="kpis"><div class="kpi"><small>Powerbolaget cash</small><b>${PB.msek(d.pb_cash / 1e6)}</b></div><div class="kpi"><small>External financing</small><b>${PB.msek(d.financing / 1e6)}</b></div>
      <div class="kpi"><small>Region (public sector)</small><b>${PB.msek(d.region / 1e6)}</b></div></div>
      <h3>RETAIL CONTRACT OFFERS · SEK/KWH</h3>
      <p class="small muted">Signed contracts keep their terms until expiry. Customers choose a new fixed or indexed offer at renewal. Monthly index uses the last complete calendar month.</p>
      ${Object.entries(d.retail_policy || {}).map(([group, p]) => `<form data-retail="${group}" class="card"><b>${PB.esc(group)}</b>
        ${[['network_fee','Network fee'],['fixed_markup','Fixed markup'],['floating_markup','Indexed markup'],['fixed_days','Fixed days'],['floating_days','Indexed days']].map(([k,label]) => `<label>${label} <input name="${k}" type="number" step="${k.endsWith('days') ? '1' : '.01'}" min="${k.endsWith('days') ? 1 : k==='network_fee' ? 0 : -.5}" max="${k.endsWith('days') ? 1095 : 5}" value="${p[k]}" required></label>`).join('')}
        <label>Index <select name="floating_index"><option value="spot" ${p.floating_index==='spot'?'selected':''}>Hourly mainland</option><option value="monthly" ${p.floating_index==='monthly'?'selected':''}>Previous month</option></select></label>
        <button type="submit">Update new offers</button></form>`).join('')}
      <h3>PRIVATE COMPANY CREDIT · SEK</h3>${table(['id','company','status','limit','debt','interest paid','repaid','bank losses'], (d.loans || []).map(x => [x.id,x.name,x.status,x.limit,x.debt,x.interest,x.repaid,x.losses]), 0, {hide:[0]})}
      <h3>MONEY MOVED SINCE FE 1, BY CATEGORY</h3>${table(['category', 'SEK'], top.map(([k, v]) => [k, v]), 0)}
      <h3>LATEST LARGE PAYMENTS</h3>${table(['time', 'payer', 'payee', 'SEK', 'category', 'good', 'qty'], d.journal.slice().reverse().map(j => [j[0], j[1], j[2], j[3], j[4], j[5] || '', j[6] ?? '']), 0)}
      ${checks}
      <p class="small muted">Every payment has a payer and payee. Powerbolaget investment shortfalls use explicit external financing. Private firms have finite credit; interest, repayment and liquidation losses are recorded separately.</p>`;
  }
  function demography(d) {
    const rows = d.months.map(m => [`month ${m.month + 1}`, m.start, m.births, m.deaths, m.immigration, m.emigration, m.internal_moves, m.end, m.tourist_arrivals, m.tourists_turned_away]);
    return `<h3>MONTHLY POPULATION ACCOUNT</h3>${table(['month', 'start', 'births', 'deaths', 'moved in', 'moved out', 'moves within island', 'end', 'visitor arrivals', 'visitors turned away'], rows, 0)}
      <p class="small muted">End = start + births − deaths + moved in − moved out. Migration follows jobs, wages, housing, commuting, amenities and outages (logit choice), with inertia.</p>`;
  }
  el.addEventListener('click', ev => {
    const t = ev.target.closest('[data-tab],[data-sort],[data-page],tr[data-goto]'); if (!t) return;
    if(t.dataset.page!=null){page=Number(t.dataset.page);render();return;}
    if (t.dataset.tab) { tab = t.dataset.tab; filter = '';page=0; render(); load(); return; }
    if (t.dataset.sort != null) { const i = Number(t.dataset.sort), s = sort[tab] || {col: -1, dir: 1}; sort[tab] = {col: i, dir: s.col === i ? -s.dir : -1};page=0; render(); return; }
    if (t.dataset.goto) { const id = t.dataset.goto; if (['zones', 'firms', 'pops'].includes(tab)) PB.select(id); }
  });
  el.addEventListener('submit', async ev => {
    const form = ev.target.closest('form[data-retail]'); if (!form) return;
    ev.preventDefault();
    const policy = Object.fromEntries([...new FormData(form)].map(([k,v]) => [k,k==='floating_index'?v:Number(v)]));
    if (await PB.command({kind:'retail_policy',category:form.dataset.retail,policy})) load();
  });
  setInterval(() => { if (!el.hidden && !document.hidden) load(); }, 6000);
  return {show() { load(); }, render};
})();
