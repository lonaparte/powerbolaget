'use strict';
// Explicit electrical endpoints and routes, alongside the map's suggested construction tools.
PB.engineering = (() => {
  const esc = PB.esc, kinds = ['turbine','storage','line','transformer','station','interconnector'];
  function open(seed = {}) {
    const root = PB.$('dialogBody'), dialog = PB.$('dialog');
    let type = seed.type || 'line';
    const options = (items, value) => items.map(([id,label]) => `<option value="${esc(id)}" ${String(id)===String(value)?'selected':''}>${esc(label)}</option>`).join('');
    const subs = Object.entries(PB.static.substations).map(([id,s]) => [id,s[0]]);
    const buses = kv => Object.entries(PB.static.buses).filter(([,b]) => !kv || b[1]===kv).map(([id,b]) => [id,`${b[0]} · ${b[1]} kV (${id})`]);
    const select = (name,label,items,value) => `<label>${label}<select name="${name}">${options(items,value)}</select></label>`;
    const number = (name,label,value,min,max,step='any') => `<label>${label}<input name="${name}" type="number" value="${value}" min="${min}" max="${max}" step="${step}" required></label>`;
    function render() {
      let fields = '';
      if (['turbine','station'].includes(type)) fields += number('x','East (km)',30.25,-10,100)+number('y','North (km)',60.25,-10,130);
      if (type==='turbine') fields += select('model','Turbine',Object.keys(PB.static.catalog.turbines).map(k=>[k,k]),'PB-3.6')+select('connect_bus','Collector connection',[['','Suggest automatically'],...buses(33)]);
      if (['storage','transformer','interconnector'].includes(type)) fields += select('station','Substation',subs);
      if (type==='storage') fields += select('connect_bus','Connection override',[['','Use station collector'],...buses().filter(([id])=>[20,33].includes(PB.static.buses[id][1]))])+number('p_mw','Power (MW)',20,1,100)+number('hours','Energy duration (h)',2,.5,8)+`<label>Grid forming <input name="grid_forming" type="checkbox" checked></label>`;
      if (['station','transformer'].includes(type)) fields += number('mva','Transformer rating (MVA)',40,5,200);
      if (type==='station') fields += `<label>Name<input name="name" value="New substation" maxlength="60" required></label>`+select('mv_kv','Collector voltage',[[20,'20 kV'],[33,'33 kV']],20);
      if (type==='line') fields += select('line_type','Line type',Object.entries(PB.static.catalog.lines).map(([k,v])=>[k,v[0]]))+select('a','From bus',buses(110))+select('b','To bus',buses(110));
      if (type==='interconnector') fields += select('technology','Technology',[['HVAC','Grid connection · HVAC'],['HVDC','Grid-forming VSC-HVDC']])+number('p_mw','New total contracted capacity (MW)',440,50,640)+`<p class="small muted">Mainland limits: HVAC 440 MW, HVDC 640 MW. Synthetic project costs and 3–4 year lead times appear in the preview.</p>`;
      if (['line','turbine','interconnector'].includes(type)) fields += `<label>Route waypoints (optional, east,north km per line; endpoints supplied automatically)<textarea name="waypoints" rows="3" placeholder="30,65&#10;35,70"></textarea></label>`;
      root.innerHTML = `<h2>ENGINEERING</h2><form id="engineeringForm">${select('type','Project',kinds.map(k=>[k,k]),type)}${fields}<p class="small muted">Check the connection, route, cost and duration before starting. An isolated station needs incoming lines before it can supply power.</p><div class="actions"><button class="button primary" type="submit">Preview project…</button><button class="button" type="button" id="engineeringCancel">Cancel</button></div></form>`;
      root.querySelector('[name="type"]').onchange = e => {type=e.target.value;render();};
      root.querySelector('#engineeringCancel').onclick = () => dialog.close();
      root.querySelector('[name="line_type"]')?.addEventListener('change', e => {
        const kv = e.target.value.includes('110')?110:e.target.value.includes('33')?33:20;
        for (const k of ['a','b']) root.querySelector(`[name="${k}"]`).innerHTML = options(buses(kv));
      });
      root.querySelector('form').onsubmit = e => {
        e.preventDefault();
        const f = e.target, values = Object.fromEntries(new FormData(f));
        const build = {type};
        for (const [k,v] of Object.entries(values)) if (v!=='' && !['waypoints','grid_forming','type'].includes(k)) build[k]=['x','y','p_mw','hours','mv_kv','mva'].includes(k)?Number(v):v;
        if (type==='storage') build.grid_forming=f.elements.grid_forming.checked;
        if (values.waypoints?.trim()) {
          const point = id => PB.static.buses[id].slice(2,4);
          const middle = values.waypoints.trim().split('\n').map(row=>row.split(',').map(Number));
          let a,b;
          if(type==='line') {a=point(build.a);b=point(build.b);}
          else if(type==='turbine' && build.connect_bus) {a=point(build.connect_bus);b=[build.x,build.y];}
          else if(type==='interconnector') {a=PB.static.hvac.mainland;b=point(PB.static.substations[build.station][3]);}
          else {PB.toast('Choose a collector bus before specifying a route.',true);return;}
          build.route=[a,...middle,b];
        }
        PB.emit('engineering-preview',build);
      };
    }
    render(); if (!dialog.open) dialog.showModal();
  }
  return {open};
})();
