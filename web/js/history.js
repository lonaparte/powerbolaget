'use strict';
PB.history = (() => {
  function download(text,format,key) {
    const url=URL.createObjectURL(new Blob([text],{type:format==='csv'?'text/csv':'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=`powerbolaget-${key.replace(/[^a-z0-9_-]/gi,'_')}.${format}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  function open(key='global') {
    const root=PB.$('dialogBody'),dialog=PB.$('dialog');
    const ids=new Set(['global',...Object.keys(PB.static.buses),...Object.keys(PB.static.branches),...Object.keys(PB.static.turbines),...Object.keys(PB.static.storage),...Object.keys(PB.static.oil||{}),...Object.keys(PB.static.devices||{}),...Object.keys(PB.static.firms),...PB.static.zones.map(z=>'zone:'+z.id)]);
    root.innerHTML=`<h2>TEACHING DATA</h2><form id="dataExport"><label>Object<select name="key">${[...ids].map(id=>`<option value="${PB.esc(id)}" ${id===key?'selected':''}>${PB.esc(PB.name(id))} (${PB.esc(id)})</option>`).join('')}</select></label><label>Resolution<select name="resolution"><option value="hour">Hourly</option><option value="day">Daily</option><option value="minute">Recorded minutes</option><option value="event">Electrical event waveforms</option></select></label><label>From simulation minute<input name="start" type="number" min="0" value="0" required></label><label>Through simulation minute<input name="end" type="number" min="0" value="${PB.snap.minute}" required></label><label>Format<select name="format"><option>csv</option><option>json</option></select></label><div class="actions"><button class="button primary" type="submit">Download</button><button class="button" type="button" id="recordObject">Start minute recording</button><button class="button" type="button" id="stopRecording">Stop recording</button><button class="button" type="button" id="closeData">Close</button></div><p class="small muted">Retention in this save: 7 days hourly, 30 days daily, 24 hours of recorded minutes for up to 8 selected electrical objects, and the latest 8 electrical events. Global day totals remain in the game history. Energy is integrated; voltage and power are snapshots. Export regularly for longer studies.</p><p id="dataStatus" class="small" role="status"></p></form>`;
    const form=root.querySelector('form'),status=root.querySelector('#dataStatus');
    root.querySelector('#closeData').onclick=()=>dialog.close();
    const recording=async on=>{
      const ok=await PB.command({kind:'record',target:form.elements.key.value,recording:on});
      if(ok)status.textContent=on?'Minute recording started.':'Minute recording stopped; recorded data is retained.';
    };
    root.querySelector('#recordObject').onclick=()=>recording(true);
    root.querySelector('#stopRecording').onclick=()=>recording(false);
    form.onsubmit=async e=>{
      e.preventDefault();
      const p=Object.fromEntries(new FormData(form));p.start=Number(p.start);p.end=Number(p.end);
      if(p.end<p.start){status.textContent='End must be after start.';return;}
      try {
        if(p.format==='json') {const data=await PB.call('/history',p);download(JSON.stringify(data,null,2),'json',p.key);status.textContent=`Exported ${data.rows?.length ?? data.events?.length ?? 0} records.`;}
        else {const request=()=>fetch('/api/history',{method:'POST',headers:{'Content-Type':'application/json','X-PowerGame':'1'},body:JSON.stringify({session:PB.session,...p})});let r=await request();if(r.status===410){await PB.recover();r=await request();}if(!r.ok)throw Error('Could not export this history.');download(await r.text(),'csv',p.key);status.textContent='Exported CSV with units in column headings.';}
      }catch(err){status.textContent=err.message;}
    };
    if(!dialog.open)dialog.showModal();
  }
  return {open};
})();
