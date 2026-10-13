'use strict';
const PL={plan:null,selected:null,mode:'select',from:null,history:[],report:null,dirty:false,checking:false,readonly:false,drag:null};
let activeFarm='base';
const plCopy=x=>JSON.parse(JSON.stringify(x));
const plKinds={substation:'Substation',turbine:'Turbine',junction:'Junction'};
function plRemember(){PL.history.push(plCopy(PL.plan));if(PL.history.length>40)PL.history.shift();}
function plDirty(){PL.dirty=true;PL.report=null;plSummary();$('plResult').innerHTML='<p class="fine">Plan changed. Revalidate to update the schedule.</p>';}
function plId(prefix,items){let i=1;while(items.some(n=>n.id===prefix+String(i).padStart(2,'0')))i++;return prefix+String(i).padStart(2,'0');}
function plField(label,key,value,min,max,step=1,scope='node'){return `<label class="field">${esc(label)}<input type="number" data-pl-field="${key}" data-pl-scope="${scope}" value="${Number(Number(value).toFixed(6))}" min="${min}" max="${max}" step="${step}" ${PL.readonly?'disabled':''}></label>`;}
function openPlanner(project=null){
 stop();PL.plan=plCopy(project?.plan||game.draft);PL.selected={type:'node',id:PL.plan.nodes.find(x=>x.kind==='substation').id};PL.mode='select';PL.from=null;PL.history=[];PL.report=null;PL.dirty=false;PL.readonly=!!project;
 $('plName').value=PL.plan.name;$('plName').disabled=PL.readonly;$('plCount').value=PL.plan.nodes.filter(n=>n.kind==='turbine').length;
 $('plResult').innerHTML='<p class="fine">Validate the electrical topology and calculate the construction schedule.</p>';$('plannerDialog').showModal();plRender();
 if(project){$('plResult').innerHTML=`<p class="notice">${project.finish<=game.step?'Commissioned · Parameters and topology are frozen':'Under construction · Frozen plan; no generation yet'}</p>`+plSchedule(project.schedule);}
}
function plSummary(){
 const p=PL.plan,count=p.nodes.filter(n=>n.kind==='turbine').length,mw=p.nodes.reduce((a,n)=>a+(n.kind==='turbine'?n.rated_mw:0),0);
 $('plSummary').innerHTML=`<span><b>${count}</b> turbines</span><span><b>${n(mw,1)}</b> MW</span><span><b>${n(p.edges.reduce((a,e)=>a+e.length_km,0),2)}</b> km of cable</span><span>${PL.readonly?'Frozen':PL.dirty?'Unsaved draft':'Draft saved'}</span>`;
 $('plBuild').disabled=PL.readonly||PL.checking||!PL.report||PL.report.errors.length>0||!PL.report.affordable;
 $('plSave').disabled=PL.readonly||PL.checking;$('plValidate').disabled=PL.checking||PL.readonly;
 $('plBuild').textContent=PL.report&&!PL.report.errors.length?`Approve construction · ${money(PL.report.cost)}`:'Validate before approval';
 document.querySelectorAll('#plannerDialog [data-pl-edit]').forEach(b=>b.disabled=PL.readonly||PL.checking);
 $('plCopy').hidden=!PL.readonly;$('plClose').textContent=PL.readonly?'Return to operation':'Save & return';
}
function plLayout(plan){
 const xs=plan.nodes.map(n=>n.x_m),ys=plan.nodes.map(n=>n.y_m),minX=Math.min(...xs)-400,minY=Math.min(...ys)-450;
 const w=Math.max(2000,Math.max(...xs)-minX+500),h=Math.max(1400,Math.max(...ys)-minY+500),scale=Math.min(900/w,460/h);
 return {minX,minY,scale,x:x=>65+(x-minX)*scale,y:y=>65+(y-minY)*scale};
}
function planSvg(plan,selected=null,runtime=null){
 const frame=PL.drag&&!runtime?PL.drag.frame:plLayout(plan);if(!runtime)PL.frame=frame;
 const xy=new Map(plan.nodes.map(n=>[n.id,[frame.x(n.x_m),frame.y(n.y_m)]]));
 let s=`<svg viewBox="0 0 1050 610" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges" aria-label="Editable wind farm topology"><defs><pattern id="plGrid" width="35" height="35" patternUnits="userSpaceOnUse"><rect width="3" height="3" fill="${ink.grid}"/></pattern></defs><rect width="1050" height="610" fill="${ink.screen}"/><rect width="1050" height="610" fill="url(#plGrid)"/>${text(26,28,runtime?runtime.name:'Offshore collector system · Drag nodes to reposition',16,ink.text,runtime?'data-no-i18n':'')}${text(1020,28,'N ↑',14,ink.sub,'text-anchor="end"')}`;
 for(const e of plan.edges){const a=xy.get(e.source),b=xy.get(e.target);if(!a||!b)continue;const chosen=selected?.type==='edge'&&selected.id===e.id,loading=runtime?.network?.lines?.[runtime.id.toLowerCase()+'_'+e.id.toLowerCase()];
  s+=`<g data-pl-edge="${esc(e.id)}" role="button" tabindex="0" aria-label="Select cable ${esc(e.id)}"><line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="transparent" stroke-width="20"/><line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${chosen?ink.accent:runtime&&(runtime.pending||!runtime.network?.energized)?ink.pending:e.closed?ink.ok:ink.pending}" stroke-width="${chosen?5:3}" ${e.closed?'':'stroke-dasharray="8 6"'}/>${text((a[0]+b[0])/2,(a[1]+b[1])/2-10,`${e.id} · ${n(e.length_km,2)} km · ${n(e.amps,0)} A${loading?' · '+n(loading.loading_pct,0)+'%':''}`,10,ink.sub,'text-anchor="middle"')}</g>`;
 }
 for(const node of plan.nodes){const [x,y]=xy.get(node.id),chosen=selected?.type==='node'&&selected.id===node.id,unit=runtime?.units?.find(t=>t.farm_id===runtime.id&&t.local_id===node.id),status=runtime?(runtime.pending?'Under construction':unit?.status||'Commissioned'):'',c=chosen?ink.accent:runtime?.pending?ink.pending:unit&&unit.status!=='Operating'?ink.trip:node.kind==='substation'?ink.text:node.kind==='junction'?ink.demand:ink.ok;
  s+=`<g transform="translate(${x},${y})" ${runtime?(unit?`data-unit="${esc(unit.id)}"`:''):`data-pl-node="${esc(node.id)}"`} role="button" tabindex="0" aria-label="Select node ${esc(node.id)}"><circle r="32" fill="${chosen?ink.sel:ink.box}" stroke="${c}" stroke-width="${chosen?3:1.5}"/>`;
  if(node.kind==='turbine')s+=`<path d="M0 0L0 23 M0 0L-3 -22Q2 -27 3 -19L3 -3 M0 0L20 11Q23 15 17 15L2 5 M0 0L-20 12Q-24 13 -19 7L-4 0" stroke="${c}" stroke-width="2" fill="${c}"/>`;
  else s+=text(0,6,node.kind==='substation'?'S':'＋',20,c,'text-anchor="middle"');
  s+=text(0,52,node.id+' · '+(node.kind==='turbine'?n(node.rated_mw,1)+' MW':plKinds[node.kind]),12,ink.text,'text-anchor="middle"');
  if(runtime)s+=text(0,70,unit?n(unit.output_mw,2)+' MW · '+status:status,10,ink.sub,'text-anchor="middle"');
  s+='</g>';
 }
 s+=text(25,568,`${plan.collector_kv} kV collector · Site transformer ${n(plan.transformer_mva)} MVA → Onshore 35 kV bus`,12,ink.sub);
 s+=text(25,589,runtime?(runtime.pending?'Under construction; excluded from operating power flow':'Commissioned topology and parameters; currents calculated by OpenDSS'):'Lengths are estimated on connection. After dragging, edit or recalculate lengths.',10,ink.faint);
 return s+'</svg>';
}
function plCanvas(){ $('plCanvas').innerHTML=planSvg(PL.plan,PL.selected);$('plMode').textContent=PL.mode==='connect'?(PL.from?'Select destination: '+PL.from+' → …':'Connect mode: select source, then destination'):'Select / drag mode'; }
function plInspector(){
 const p=PL.plan,sel=PL.selected;let h='';
 if(!sel){$('plInspector').innerHTML='<p class="fine">Select a node or cable to edit its parameters.</p>';return;}
 if(sel.type==='node'){
  const a=p.nodes.find(n=>n.id===sel.id);if(!a)return;h=`<h3>${esc(a.id)} · ${plKinds[a.kind]}</h3>`;
  h+=plField('Position X (m)','x_m',a.x_m,-20000,20000,50)+plField('Position Y (m)','y_m',a.y_m,-20000,20000,50);
  if(a.kind==='turbine'){
   for(const [l,k,min,max,step]of [['Rated power MW','rated_mw',.5,15,.5],['Rotor diameter m','rotor_m',40,260,1],['Hub height m','hub_m',40,200,1],['Cut-in wind m/s','cut_in',1,6,.1],['Rated wind m/s','rated_speed',7,18,.1],['Cut-out wind m/s','cut_out',20,35,.5],['Unit transformer MVA','transformer_mva',.5,25,.1],['Unit transformer reactance %','transformer_x_pct',2,15,.5]])h+=plField(l,k,a[k],min,max,step);
   h+='<button class="button full" data-pl-edit data-pl-action="copyParams">Apply these parameters to all turbines</button>';
  }
  if(a.kind==='substation'){
   h+=`<label class="field">Collector voltage kV<select data-pl-setting="collector_kv" ${PL.readonly?'disabled':''}><option value="35" ${p.collector_kv===35?'selected':''}>35 kV</option><option value="66" ${p.collector_kv===66?'selected':''}>66 kV</option></select></label>`;
   h+=plField('Site transformer MVA','transformer_mva',p.transformer_mva,2,200,.5,'plan')+plField('Site transformer reactance %','transformer_x_pct',p.transformer_x_pct,2,20,.5,'plan');
   h+='<h3>Shared onshore storage</h3><p class="fine">New storage connects to the onshore 35 kV bus and is dispatched with existing batteries.</p>';
   h+=plField('Additional storage MW','storage_power_mw',p.storage_power_mw,0,30,.5,'plan')+plField('Additional storage MWh','storage_capacity_mwh',p.storage_capacity_mwh,0,240,1,'plan');
  }
 }else{
  const e=p.edges.find(n=>n.id===sel.id);if(!e)return;h=`<h3>${esc(e.id)} · Cable</h3>`;
  for(const [key,label]of [['source','Source'],['target','Destination']])h+=`<label class="field">${label}<select data-pl-endpoint="${key}" ${PL.readonly?'disabled':''}>${p.nodes.map(n=>`<option value="${esc(n.id)}" ${e[key]===n.id?'selected':''}>${esc(n.id)} · ${plKinds[n.kind]}</option>`).join('')}</select></label>`;
  for(const [l,k,min,max,step]of [['Length km','length_km',.05,50,.05],['Rated current A','amps',50,1500,10],['Positive-sequence resistance Ω/km','r_ohm_km',.005,1,.005],['Positive-sequence reactance Ω/km','x_ohm_km',.01,.8,.01],['Capacitance nF/km','c_nf_km',0,500,10]])h+=plField(l,k,e[k],min,max,step,'edge');
  h+=`<label class="field inline"><input type="checkbox" id="plEdgeClosed" ${e.closed?'checked':''} ${PL.readonly?'disabled':''}>Closed at commissioning</label><p class="fine">Normally open ties are allowed. Every turbine must have a closed path to the substation.</p>`;
 }
 $('plInspector').innerHTML=h;plSummary();
}
function plResources(){
 let h='<h3>Resources & site</h3><p class="fine">Duration is calculated phase by phase. Resources affect the critical path, vessel cost and commissioning date.</p>';
 for(const [l,k,min,max]of [['Foundation vessels','foundation_vessels',1,4],['Installation vessels','installation_vessels',1,4],['Cable vessels','cable_vessels',1,4],['Engineering teams','engineering_teams',1,4],['Electrical teams','electrical_teams',1,4],['Turbine supply lines','supply_lines',1,4],['Port distance km','port_distance_km',1,200],['Water depth m (fixed-bottom)','water_depth_m',5,60]])h+=plField(l,k,PL.plan.resources[k],min,max,1,'resources');
 $('plResources').innerHTML=h;
}
function plRender(){$('plCount').value=PL.plan.nodes.filter(n=>n.kind==='turbine').length;plSummary();plCanvas();plInspector();plResources();
 $('plElements').innerHTML=PL.plan.nodes.map(a=>`<button class="pl-list-item ${PL.selected?.id===a.id&&PL.selected?.type==='node'?'selected':''}" data-pl-select-node="${esc(a.id)}"><b>${esc(a.id)}</b><span>${a.kind==='turbine'?n(a.rated_mw,1)+' MW':plKinds[a.kind]}</span></button>`).join('')+'<p class="fine">Cables</p>'+PL.plan.edges.map(e=>`<button class="pl-list-item" data-pl-select-edge="${esc(e.id)}"><b>${esc(e.id)}</b><span>${esc(e.source)} → ${esc(e.target)} ${e.closed?'':'○'}</span></button>`).join('');
}
function plSchedule(s){if(!s)return '<p class="fine">No phase schedule was saved for this legacy project.</p>';const max=Math.max(...s.phases.map(p=>p.end_hour),1);return `<div class="schedule-heading"><div><span>Calculated duration</span><strong>${n(s.days,1)} days</strong></div><div><span>Commissioning (CET)</span><strong>${esc(s.finish_date)}</strong></div><div><span>Weather delay (vessel-hours)</span><strong>${n(s.weather_wait_vessel_hours,0)} h</strong></div></div><div class="gantt">${s.phases.map(p=>`<div class="gantt-row"><span>${esc(p.name)}</span><div class="gantt-track"><i class="${s.critical_path.includes(p.id)?'critical':''}" style="left:${p.start_hour/max*100}%;width:${Math.max(.4,(p.end_hour-p.start_hour)/max*100)}%"></i></div><b>${n(p.duration_days,1)} days</b></div>`).join('')}</div><p class="fine">Dark bars show the critical path. Phases can overlap, so durations are not simply added. Weather uses the Baltic coastal climate function; production rates are assumptions.</p><details><summary>Work quantities, weather delays & resources</summary>${s.phases.map(p=>`<div class="row"><span>${esc(p.name)}</span><b>${n(p.work_hours,1)} work-hours / ${n(p.weather_wait_hours,0)} h weather delay</b></div><p class="fine">${esc(p.resource)}</p>`).join('')}</details>`;}
async function plValidate(){
 if(PL.checking||!Array.from($('plannerDialog').querySelectorAll('input')).every(el=>el.reportValidity()))return;PL.checking=true;plSummary();$('plResult').innerHTML='<p>Checking topology, AC power flow and construction windows…</p>';
 const fingerprint=JSON.stringify(PL.plan);
 try{const r=await signed('/plan/validate',{plan:PL.plan});if(JSON.stringify(PL.plan)!==fingerprint)return;PL.report=r;
  $('plResult').innerHTML=`<div class="pl-validation ${r.errors.length?'invalid':''}">${r.errors.length?'Validation failed':'Topology & AC power flow validated'} · ${n(r.capacity_mw,1)} MW · ${r.topology}</div>${r.errors.map(e=>`<p class="bad">${esc(e)}</p>`).join('')}${r.warnings.map(e=>`<p class="notice">${esc(e)}</p>`).join('')}<div class="row"><span>Total investment (including vessels)</span><b>${money(r.cost)}</b></div><div class="row"><span>Available funds</span><b class="${r.affordable?'':'bad'}">${money(game.cash)}</b></div>${!r.affordable?'<p class="bad">Insufficient funds. Save the draft, or reduce its size and recalculate.</p>':''}${plSchedule(r.schedule)}`;
 }catch(e){$('plResult').innerHTML=`<p class="bad">${esc(e.message)}</p>`;PL.report=null;}finally{PL.checking=false;plSummary();}
}
function plAdd(kind){plRemember();const id=plId(kind==='turbine'?'T':'J',PL.plan.nodes);PL.plan.nodes.push({id,kind,x_m:800+PL.plan.nodes.length%4*700,y_m:Math.floor(PL.plan.nodes.length/4)*700,rated_mw:5,rotor_m:126,hub_m:90,cut_in:3,rated_speed:11.4,cut_out:25,transformer_mva:5.5,transformer_x_pct:6});PL.selected={type:'node',id};plDirty();plRender();}
function plConnect(source,target){if(source===target)return;const a=PL.plan.nodes.find(n=>n.id===source),b=PL.plan.nodes.find(n=>n.id===target);plRemember();const id=plId('L',PL.plan.edges);PL.plan.edges.push({id,source,target,length_km:Math.max(.05,Math.round(Math.hypot(a.x_m-b.x_m,a.y_m-b.y_m)*1.08/50)*.05),r_ohm_km:.12,x_ohm_km:.1,c_nf_km:200,amps:300,closed:true});PL.selected={type:'edge',id};PL.from=null;plDirty();plRender();}
function plSelectNode(id){if(PL.mode==='connect'&&!PL.readonly){if(!PL.from){PL.from=id;PL.selected={type:'node',id};plCanvas();}else plConnect(PL.from,id);}else{PL.selected={type:'node',id};plRender();}}
function plBatch(){
 const count=Number($('plCount').value);if(!Number.isInteger(count)||count<1||count>24)return toast('Choose 1–24 turbines',true);
 plRemember();const mw=Number($('plPreset').value),root=PL.plan.nodes.find(n=>n.kind==='substation');PL.plan.nodes=[root];PL.plan.edges=[];
 for(let i=0;i<count;i++){const id='T'+String(i+1).padStart(2,'0');PL.plan.nodes.push({id,kind:'turbine',x_m:800+(i%4)*1000,y_m:Math.floor(i/4)*950-400,rated_mw:mw,rotor_m:mw===5?126:mw===8?164:220,hub_m:mw===5?90:mw===8?110:140,cut_in:3,rated_speed:mw===5?11.4:12,cut_out:25,transformer_mva:mw*1.1,transformer_x_pct:6});}
 PL.plan.transformer_mva=Math.min(200,Math.max(2,count*mw*1.1));plAutoWire(false);PL.selected={type:'node',id:root.id};plDirty();plRender();
}
function plAutoWire(remember=true){
 if(remember)plRemember();const nodes=PL.plan.nodes,root=nodes.find(n=>n.kind==='substation'),rest=nodes.filter(n=>n.kind!=='substation'),type=$('plTopology').value;PL.plan.edges=[];
 const link=(a,b)=>{PL.plan.edges.push({id:'L'+String(PL.plan.edges.length+1).padStart(2,'0'),source:a.id,target:b.id,length_km:Math.max(.05,Math.round(Math.hypot(a.x_m-b.x_m,a.y_m-b.y_m)*1.08/50)*.05),r_ohm_km:.12,x_ohm_km:.1,c_nf_km:200,amps:300,closed:true});};
 rest.forEach((node,i)=>link(type==='star'||i%4===0?root:rest[i-1],node));
 if(type==='ring'&&rest.length>1)for(let end=3;end<rest.length+3;end+=4){const index=Math.min(end,rest.length-1);if(index%4!==0)link(rest[index],root);}
 if(remember){plDirty();plRender();}
}
function plRuntime(){const p=[...(game.plants||[]),...game.projects.filter(p=>p.plan)].find(p=>p.id===activeFarm);if(!p)return null;return planSvg(p.plan,null,{...p,pending:!game.plants.some(x=>x.id===p.id),network:game.snapshot.network,units:game.snapshot.turbines});}
function renderFarmSelector(){const options=[['base','Original wind farm'],...(game.plants||[]).map(p=>[p.id,p.name]),...game.projects.filter(p=>p.plan).map(p=>[p.id,p.name+' · '+'Under construction'])];if(!options.some(x=>x[0]===activeFarm))activeFarm='base';$('farmView').innerHTML=options.map(([id,label])=>`<option ${id!=='base'?'data-no-i18n':''} value="${esc(id)}" ${activeFarm===id?'selected':''}>${esc(label)}</option>`).join('');}
function customProjectCards(){return [...game.projects.filter(p=>p.plan),...(game.plants||[])].map(p=>{const done=game.plants.some(x=>x.id===p.id),progress=Math.max(0,Math.min(100,(game.step-p.start)/(p.finish-p.start)*100));return `<article class="project"><h3 data-no-i18n>${esc(p.name)}</h3><p>${p.plan.nodes.filter(n=>n.kind==='turbine').length} turbines · ${n(p.plan.nodes.reduce((a,n)=>a+(n.kind==='turbine'?n.rated_mw:0),0),1)} MW · ${p.plan.collector_kv} kV</p><div class="progress"><i style="width:${progress}%"></i></div><p>${done?'Commissioned':`Calculated duration ${n(p.days,1)} days · Until commissioning: ${n((p.finish-game.step)/96,1)} days`}</p><button class="button full" data-inspect-plan="${esc(p.id)}">Inspect plan & schedule</button></article>`;}).join('');}
document.addEventListener('click',async e=>{
 const inspect=e.target.closest('[data-inspect-plan]');if(inspect){const p=[...game.projects,...(game.plants||[])].find(p=>p.id===inspect.dataset.inspectPlan);if(p)openPlanner(p);return;}
 const button=e.target.closest('#plannerDialog button');if(!button||button.disabled)return;
 if(button.dataset.plSelectNode)plSelectNode(button.dataset.plSelectNode);
 if(button.dataset.plSelectEdge){PL.selected={type:'edge',id:button.dataset.plSelectEdge};plRender();}
 const action=button.dataset.plAction;if(!action)return;
 if(action==='select'||action==='connect'){PL.mode=action;PL.from=null;plCanvas();}
 if(action==='addTurbine'&&PL.plan.nodes.filter(n=>n.kind==='turbine').length<24)plAdd('turbine');
 if(action==='addJunction'&&PL.plan.nodes.length<41)plAdd('junction');
 if(action==='batch')plBatch();if(action==='wire')plAutoWire();
 if(action==='undo'&&PL.history.length){PL.plan=PL.history.pop();PL.selected=null;plDirty();plRender();}
 if(action==='delete'&&PL.selected){const s=PL.selected;if(s.type==='node'&&PL.plan.nodes.find(n=>n.id===s.id)?.kind==='substation')return toast('The substation cannot be deleted',true);plRemember();if(s.type==='node'){PL.plan.nodes=PL.plan.nodes.filter(n=>n.id!==s.id);PL.plan.edges=PL.plan.edges.filter(e=>e.source!==s.id&&e.target!==s.id);}else PL.plan.edges=PL.plan.edges.filter(e=>e.id!==s.id);PL.selected=null;plDirty();plRender();}
 if(action==='lengths'){plRemember();for(const e of PL.plan.edges){const a=PL.plan.nodes.find(n=>n.id===e.source),b=PL.plan.nodes.find(n=>n.id===e.target);e.length_km=Math.max(.05,Math.round(Math.hypot(a.x_m-b.x_m,a.y_m-b.y_m)*1.08/50)*.05);}plDirty();plRender();}
 if(action==='copyParams'){const a=PL.plan.nodes.find(n=>n.id===PL.selected?.id);if(a?.kind==='turbine'){plRemember();for(const b of PL.plan.nodes)if(b.kind==='turbine')for(const k of ['rated_mw','rotor_m','hub_m','cut_in','rated_speed','cut_out','transformer_mva','transformer_x_pct'])b[k]=a[k];plDirty();plRender();}}
});
function plChange(e){
 const el=e.target;if(PL.readonly)return;if(el.id==='plName'){if(PL.plan.name===el.value)return;plRemember();PL.plan.name=el.value;plDirty();return;}
 if(el.dataset.plField){const scope=el.dataset.plScope;const obj=scope==='plan'?PL.plan:scope==='resources'?PL.plan.resources:scope==='edge'?PL.plan.edges.find(n=>n.id===PL.selected?.id):PL.plan.nodes.find(n=>n.id===PL.selected?.id);if(!obj||obj[el.dataset.plField]===Number(el.value))return;plRemember();obj[el.dataset.plField]=Number(el.value);plDirty();plCanvas();}
 if(el.dataset.plSetting){if(PL.plan[el.dataset.plSetting]===Number(el.value))return;plRemember();PL.plan[el.dataset.plSetting]=Number(el.value);plDirty();plCanvas();}
 if(el.dataset.plEndpoint||el.id==='plEdgeClosed'){const edge=PL.plan.edges.find(n=>n.id===PL.selected?.id);if(edge){plRemember();if(el.id==='plEdgeClosed')edge.closed=el.checked;else edge[el.dataset.plEndpoint]=el.value;plDirty();plCanvas();}}
}
$('plannerDialog').addEventListener('input',plChange);
$('plannerDialog').addEventListener('change',plChange);
$('plCanvas').addEventListener('pointerdown',e=>{
 if(PL.checking||PL.readonly)return;const target=e.target.closest('[data-pl-node]');if(!target)return;
 const id=target.dataset.plNode;if(PL.mode==='connect'){plSelectNode(id);return;}
 PL.selected={type:'node',id};const node=PL.plan.nodes.find(n=>n.id===id),rect=$('plCanvas').getBoundingClientRect();
 PL.drag={id,x:e.clientX,y:e.clientY,oldX:node.x_m,oldY:node.y_m,frame:PL.frame,ratio:1050/rect.width,moved:false};$('plCanvas').setPointerCapture(e.pointerId);
});
$('plCanvas').addEventListener('pointermove',e=>{const d=PL.drag;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(!d.moved&&Math.abs(dx)+Math.abs(dy)<4)return;if(!d.moved){plRemember();d.moved=true;}const node=PL.plan.nodes.find(n=>n.id===d.id);node.x_m=Math.max(-20000,Math.min(20000,Math.round((d.oldX+dx*d.ratio/d.frame.scale)/50)*50));node.y_m=Math.max(-20000,Math.min(20000,Math.round((d.oldY+dy*d.ratio/d.frame.scale)/50)*50));plCanvas();});
$('plCanvas').addEventListener('pointerup',()=>{if(PL.drag){const moved=PL.drag.moved;PL.drag=null;if(moved)plDirty();plRender();}});
$('plCanvas').addEventListener('click',e=>{const edge=e.target.closest('[data-pl-edge]');if(edge){PL.selected={type:'edge',id:edge.dataset.plEdge};plRender();}});
$('plCanvas').addEventListener('keydown',e=>{if(e.key==='Enter'){const node=e.target.closest('[data-pl-node]');if(node)plSelectNode(node.dataset.plNode);}});
$('plValidate').onclick=plValidate;
$('plSave').onclick=async()=>{if(await command({kind:'plan_save',plan:PL.plan})){PL.dirty=false;plSummary();toast('Planning draft saved.');}};
$('plBuild').onclick=async()=>{if(!PL.report||PL.report.errors.length)return;if(await command({kind:'plan_build',plan:PL.plan})){PL.dirty=false;$('plannerDialog').close();panel='build';render();toast('Construction started. Commissioning follows the calculated schedule.');}};
$('plClose').onclick=async()=>{if(PL.dirty&&!PL.readonly){if(!await command({kind:'plan_save',plan:PL.plan}))return;PL.dirty=false;}$('plannerDialog').close();};
$('plannerDialog').addEventListener('cancel',e=>{if(PL.dirty){e.preventDefault();$('plClose').click();}});
$('plCopy').onclick=()=>{PL.readonly=false;PL.plan.name+=' · Copy';$('plName').value=PL.plan.name;$('plName').disabled=false;plDirty();plRender();};
$('farmView').onchange=()=>{activeFarm=$('farmView').value;$('scene').innerHTML=view==='coast'?coastal():singleLine();};
