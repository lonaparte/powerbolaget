'use strict';
// Pixel-art presentation layer: the day/night theme and the coastal wind farm map.
// It only reads `game`. app.js calls pixelTheme() before each render and coastal() returns pixelMap().
(()=>{
const PALETTES={
 night:{screen:'#121a36',grid:'#202a55',text:'#ece3cc',sub:'#9aa0c0',faint:'#666c92',box:'#1b2347',boxEdge:'#4a5690',shadow:'#05070f',ok:'#5ec8b4',trip:'#ff6f5e',bus:'#72d69c',storage:'#f0a656',feeder:'#8f97b8',wind:'#72d69c',demand:'#6cb6ee',battery:'#f0a656',import:'#9aa0c0',accent:'#f2c55c',pending:'#5d648a',sel:'#3a3418'},
 day:{screen:'#f3ead6',grid:'#e0d3b4',text:'#33261f',sub:'#786756',faint:'#a4927a',box:'#fbf6ea',boxEdge:'#3b2b22',shadow:'#cdbb93',ok:'#2a8576',trip:'#b83a2a',bus:'#2f8f5c',storage:'#c27a24',feeder:'#6d7686',wind:'#2f8f5c',demand:'#2f6fa8',battery:'#c27a24',import:'#7d8696',accent:'#c4572f',pending:'#a8a294',sel:'#fff1d0'}};
const ink={},MODES={auto:'◐ Auto',day:'☀ Day',night:'☾ Night'};
let mode='auto',theme='',light=0,dusk=0;
try{mode=localStorage.getItem('powerbolaget-theme')||'auto';}catch{}
if(!MODES[mode])mode='auto';
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const current=()=>typeof game!=='undefined'&&game?game:null;
// Daylight follows the simulated clock and the coastal climate's sunrise and sunset.
function sky(){const g=current();if(!g)return{day:0,dusk:0};const w=g.snapshot.weather,[,clock='00:00']=String(g.timestamp).split(' '),[hh,mm]=clock.split(':').map(Number),h=hh+mm/60,rise=w.sunrise_hour??7.5,set=w.sunset_hour??16.5;
 return{day:clamp((h-rise+.6)/1.2)*clamp((set+.6-h)/1.2),dusk:Math.max(0,1-Math.abs(h-rise)/1.1,1-Math.abs(h-set)/1.1)};}
function pixelTheme(){const s=sky();light=mode==='auto'?s.day:mode==='day'?1:0;dusk=mode==='auto'?s.dusk:0;const name=mode==='auto'?(light>=.5?'day':'night'):mode;
 if(name!==theme){theme=name;Object.assign(ink,PALETTES[name]);document.documentElement.dataset.theme=name;}
 const b=document.getElementById('themeToggle');if(b){b.textContent=MODES[mode];b.title=mode==='auto'?'Day and night follow the simulated clock':'Fixed '+mode+' theme';}}
function cycleTheme(){mode={auto:'day',day:'night',night:'auto'}[mode];try{localStorage.setItem('powerbolaget-theme',mode);}catch{}pixelTheme();if(current())render();}
window.ink=ink;window.pixelTheme=pixelTheme;
document.getElementById('themeToggle')?.addEventListener('click',cycleTheme);
pixelTheme();

// ---------- Pixel helpers ----------
const W=366,H=216,U=3;  // map pixels; one pixel is three units of the 1098×648 overlay
const canvas=document.getElementById('mapCanvas'),ctx=canvas.getContext('2d'),cache=document.createElement('canvas');cache.width=W;cache.height=H;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const rgbCache=new Map();
function rgb(h){let x=rgbCache.get(h);if(!x){const k=parseInt(h.slice(1),16);x=[k>>16,k>>8&255,k&255];rgbCache.set(h,x);}return x;}
function mix(a,b,t){t=clamp(t);const x=rgb(a),y=rgb(b);return '#'+x.map((q,i)=>Math.round(q+(y[i]-q)*t).toString(16).padStart(2,'0')).join('');}
function rgba(h,a){const [r,g,b]=rgb(h);return `rgba(${r},${g},${b},${clamp(a).toFixed(3)})`;}
function R(c,x,y,w,h,col){c.fillStyle=col;c.fillRect(Math.round(x),Math.round(y),w,h);}
function P(c,x,y,col){R(c,x,y,1,1,col);}
function L(c,x0,y0,x1,y1,col,step=1){x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);c.fillStyle=col;const dx=Math.abs(x1-x0),dy=-Math.abs(y1-y0),sx=x0<x1?1:-1,sy=y0<y1?1:-1;let e=dx+dy;for(let i=0;i<600;i++){if(i%step===0)c.fillRect(x0,y0,1,1);if(x0===x1&&y0===y1)break;const e2=2*e;if(e2>=dy){e+=dy;x0+=sx;}if(e2<=dx){e+=dx;y0+=sy;}}}
function glow(c,x,y,r,col,a){for(let k=r;k>0;k--)R(c,x-k,y-k,k*2+1,k*2+1,rgba(col,a/r));}
function rng(seed){return()=>{seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
const BAYER=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5].map(v=>(v+.5)/16);
const dither=(x,y)=>BAYER[(y&3)*4+(x&3)];
function hash(x,y){let h=Math.imul(x,374761393)+Math.imul(y,668265263)|0;h=Math.imul(h^h>>>13,1274126177);return((h^h>>>16)>>>0)/4294967296;}
function noise(x,y,s){const gx=Math.floor(x/s),gy=Math.floor(y/s),fx=x/s-gx,fy=y/s-gy,a=hash(gx,gy),b=hash(gx+1,gy),c=hash(gx,gy+1),d=hash(gx+1,gy+1);return a+(b-a)*fx+(c-a)*fy+(a-b-c+d)*fx*fy;}
const tone=(day,night)=>mix(day,night,1-light);

// ---------- Map layout (same arrangement as the original schematic) ----------
const COAST=[[0,244],[20,236],[40,240],[60,237],[85,226],[110,224],[140,217],[170,207],[195,214],[216,210]];
function coastX(y){let i=0;while(i<COAST.length-2&&COAST[i+1][0]<y)i++;const [y0,x0]=COAST[i],[y1,x1]=COAST[i+1],k=clamp((y-y0)/(y1-y0));return x0+(x1-x0)*(k*k*(3-2*k))+Math.round(Math.sin(y*.37)*1.2);}
const BASIN={x1:352,y0:143,y1:159};
const water=(x,y)=>x<coastX(y)-1||(y>=BASIN.y0&&y<=BASIN.y1&&x<=BASIN.x1);
const TURBINES=[[35,58],[82,58],[128,58],[175,58],[35,132],[82,132],[128,132],[175,132]],TOWER=24,ROTOR=13;
const CABLES={a:[[35,84],[197,84],[197,172]],b:[[35,158],[197,158],[197,172]],farm:[[197,172],[224,172]],city:[[264,170],[298,170],[298,100]],bess:[[264,176],[327,176],[327,182]],grid:[[244,186],[244,216]]};
const SUB={x:222,y:161,w:45,h:26},BESS={x:300,y:178,w:54,h:23};
// The city is drawn at grid scale: each district is a load zone with its own 10 kV feeder and bus node.
const ZONES={center:{box:[248,40,47,59],hue:'#e0b04a',node:[284,94],feeder:[[298,100],[284,100],[284,96]],label:[271,66]},
 homes:{box:[300,40,61,59],hue:'#d9776a',node:[312,94],feeder:[[298,100],[312,100],[312,96]],label:[330,66]},
 harbor:{box:[240,106,57,34],hue:'#5fa8b8',node:[284,110],feeder:[[298,104],[284,104],[284,108]],label:[266,121]},
 water:{box:[302,106,49,34],hue:'#6a8fd0',node:[312,110],feeder:[[298,104],[312,104],[312,108]],label:[330,121]}};
const TREE_ZONES=[[250,2,116,30],[269,163,19,11],[256,190,36,26],[304,204,62,12],[226,190,10,26],[353,106,13,33]];
const TREES=(()=>{const r=rng(5),out=[];for(const [x,y,w,h] of TREE_ZONES)for(let i=0;i<w*h/34;i++){const tx=x+Math.floor(r()*w),ty=y+Math.floor(r()*h);if(!water(tx,ty+6)&&!water(tx+4,ty+6))out.push([tx,ty,r()<.6?'pine':'oak']);}return out.sort((a,b)=>a[1]-b[1]);})();
function cells(up){return up?[[304,181,41,8],[304,192,41,8]]:[[304,183,41,13]];}
function ring(c,cx,cy,r,col){for(let y=-r-1;y<=r+1;y++)for(let x=-r-1;x<=r+1;x++)if(Math.abs(Math.hypot(x,y)-r)<.55)P(c,cx+x,cy+y,col);}
function zoneState(g){const out={};for(const d of g.snapshot.districts)out[d.id]={ratio:d.demand_mw>0?clamp(d.served_mw/d.demand_mw):1,live:!!(g.breakers[d.id]&&g.breakers.transformer)};return out;}

// ---------- Static terrain cache (rebuilt when light, snow or upgrades change) ----------
let cacheKey='';
function buildCache(snow,upgraded,zones){const g=cache.getContext('2d'),img=g.createImageData(W,H),px=img.data,night=1-light;
 const sea=[['#6cb4cc','#1f3d5f'],['#55a0c0','#1a3557'],['#4689b0','#162e4d'],['#3a749e','#132843'],['#33658f','#11233c']].map(([d,n])=>rgb(mix(d,n,night)));
 const foam=rgb(mix('#d8eef0','#3d5c7c',night)),sand=[rgb(mix('#e6d29c','#4d4862',night)),rgb(mix('#d8c087','#433f58',night))],
  land=snow?[rgb(mix('#eef3f6','#5a6888',night)),rgb(mix('#d6e0e8','#4c5a7a',night))]:[rgb(mix('#86a35d','#25363a',night)),rgb(mix('#728f4f','#1f2f33',night))];
 for(let y=0;y<H;y++){const cx=coastX(y);for(let x=0;x<W;x++){const i=(y*W+x)*4;let c;
  if(water(x,y)){const basin=x>=cx-1,t=basin?.15:clamp((cx-x)/120)*4,lv=Math.min(4,Math.floor(t)+(t%1>dither(x,y)?1:0));c=!basin&&cx-x<2.5?foam:sea[lv];}
  else if(x-cx<5&&!(y>=BASIN.y0-2&&y<=BASIN.y1+2&&x>cx+1))c=sand[(x+y)%3===0?1:0];
  else c=land[noise(x,y,7)*.7+hash(x,y)*.3>.5+((dither(x,y)-.5)*.3)?1:0];
  px[i]=c[0];px[i+1]=c[1];px[i+2]=c[2];px[i+3]=255;}}
 g.putImageData(img,0,0);
 // Harbor quay and jetty.
 const stone=tone('#b8ad98','#4a4658'),stoneD=tone('#958a76','#38364a'),conc=tone('#b8b2a4','#3e3c4a');
 R(g,coastX(141)-1,140,BASIN.x1-coastX(141)+3,3,stone);R(g,coastX(141)-1,142,BASIN.x1-coastX(141)+3,1,stoneD);R(g,coastX(160)-1,159,BASIN.x1-coastX(160)+3,2,stone);R(g,BASIN.x1+1,140,2,21,stone);
 R(g,299,143,4,12,tone('#8a6a48','#3e3238'));for(let y=145;y<155;y+=3)R(g,299,y,4,1,tone('#6e523a','#30282e'));
 // District load zones: a tinted, dashed planning zone by day; by night lit in proportion to served demand.
 for(const [id,z] of Object.entries(ZONES)){const [x0,y0,w,h]=z.box,st=zones[id]||{ratio:1,live:true},lit=st.live?st.ratio:0,night=1-light,glowC=mix('#ffd77a',z.hue,.3);
  R(g,x0,y0,w,h,rgba(z.hue,.20*light+.10*night));
  for(let y=y0;y<y0+h;y++)for(let x=x0;x<x0+w;x++){if(light>0&&(x+y)%4===0)P(g,x,y,rgba(mix(z.hue,'#000000',.15),.6*light));if(night>0&&x%3===0&&y%3===0&&hash(x,y)<lit*.55)P(g,x,y,rgba(hash(y,x)<.2?'#cfe6ff':glowC,.85*night));}
  const edge=tone(mix(z.hue,'#000000',.4),z.hue);for(let x=x0;x<x0+w;x+=2){P(g,x,y0,edge);P(g,x,y0+h-1,edge);}for(let y=y0;y<y0+h;y+=2){P(g,x0,y,edge);P(g,x0+w-1,y,edge);}}
 // Onshore substation: fenced yard, busbars and two transformer symbols (grid 110/35 kV, city 35/10 kV).
 const fence=tone('#4a4a52','#1e2030');R(g,SUB.x,SUB.y,SUB.w,SUB.h,tone('#aaa597','#3a3a4a'));for(let x=SUB.x;x<SUB.x+SUB.w;x+=2){P(g,x,SUB.y,fence);P(g,x,SUB.y+SUB.h-1,fence);}for(let y=SUB.y;y<SUB.y+SUB.h;y+=2){P(g,SUB.x,y,fence);P(g,SUB.x+SUB.w-1,y,fence);}
 const steel=tone('#4a5466','#8f9abc'),sym=tone('#2e3a4c','#b8c2e0');R(g,226,165,37,1,steel);R(g,226,183,37,1,steel);
 for(const x of [234,254]){R(g,x,165,1,3,steel);R(g,x,181,1,2,steel);ring(g,x,170,3,sym);ring(g,x,175,3,sym);}
 // Battery site: pad and battery symbols; the charge segments are drawn live.
 R(g,BESS.x,BESS.y,BESS.w,BESS.h,conc);R(g,BESS.x,BESS.y,BESS.w,1,tone('#cfc9bb','#4a4858'));
 for(const [x,y,w,h] of cells(upgraded)){R(g,x-1,y-1,w+2,h+2,tone('#2e3440','#8f9abc'));R(g,x,y,w,h,tone('#3a3f4c','#141726'));R(g,x+w+1,y+Math.floor(h/2)-2,2,4,tone('#2e3440','#8f9abc'));}
 // Grid pylon.
 const pyl=tone('#6d7280','#4a5068');L(g,240,214,243,198,pyl);L(g,248,214,245,198,pyl);R(g,243,196,3,2,pyl);R(g,238,199,13,1,pyl);R(g,239,203,11,1,pyl);L(g,241,206,247,212,pyl);L(g,247,206,241,212,pyl);
 // Trees, dusted with snow below freezing.
 for(const [x,y,kind] of TREES){const dark=tone(snow?'#4f6b5a':'#3a6438','#152622'),hi=tone(snow?'#f2f6f8':'#5a8a48',snow?'#6a7a96':'#1e3430'),trunk=tone('#5a3e2a','#1e1a1e');
  R(g,x+1,y+7,4,1,rgba('#000000',.18));
  if(kind==='pine'){R(g,x+2,y,1,1,hi);R(g,x+1,y+1,3,2,dark);P(g,x+2,y+1,hi);R(g,x,y+3,5,2,dark);R(g,x+1,y+3,2,1,hi);R(g,x+2,y+5,1,2,trunk);}
  else{R(g,x+1,y+1,3,4,dark);R(g,x,y+2,5,2,dark);R(g,x+1,y+1,2,1,hi);P(g,x,y+2,hi);R(g,x+2,y+5,1,2,trunk);}}}

// ---------- Animated layer ----------
const rotor={},seeded=(n,seed,f)=>Array.from({length:n},(_,i)=>f(rng(seed+i)));
const SPARKS=seeded(80,100,r=>[Math.floor(r()*215),Math.floor(r()*216),r()*6]),STREAKS=seeded(40,300,r=>[r()*W,r()*H,2+Math.floor(r()*4),.6+r()*.8]),CLOUDS=seeded(6,500,r=>[r()*W,r()*H,24+Math.floor(r()*26),10+Math.floor(r()*10)]);
function pathLen(p){let s=0;for(let i=1;i<p.length;i++)s+=Math.abs(p[i][0]-p[i-1][0])+Math.abs(p[i][1]-p[i-1][1]);return s;}
function along(p,d){for(let i=1;i<p.length;i++){const [x0,y0]=p[i-1],[x1,y1]=p[i],l=Math.abs(x1-x0)+Math.abs(y1-y0);if(d<=l){const k=l?d/l:0;return[x0+(x1-x0)*k,y0+(y1-y0)*k];}d-=l;}return p[p.length-1];}
function cable(c,p,live,t,dir,mw){const col=live?tone('#24566a','#3a5a8a'):tone('#c0392b','#ff6f5e');for(let i=1;i<p.length;i++)L(c,p[i-1][0],p[i-1][1],p[i][0],p[i][1],col,live?2:3);
 if(!live||Math.abs(mw)<.02)return;const len=pathLen(p),speed=(8+Math.min(30,Math.abs(mw)*3))*Math.sign(mw)*dir,dot=tone('#ffe08a','#9ef0d8');for(let d=((t*speed)%7+7)%7;d<len;d+=7){const [x,y]=along(p,d);P(c,x,y,dot);}}
function turbine(c,x,hub,u,t,built,dt){const base=hub+TOWER,nightK=1-light;
 if(light>.3)L(c,x+1,base,x+10,base+3,rgba('#0a1a2a',.22*light));
 if(built<=0){R(c,x,base-2,2,2,tone('#e2b53a','#8a7030'));for(let y=hub+2;y<base-2;y+=3)P(c,x,y,rgba(tone('#ffffff','#9aa0c0'),.35));if(nightK>.4&&Math.floor(t*1.5+x)%2)P(c,x,base-3,'#ffd060');return;}
 R(c,x-2,base-1,6,2,rgba(tone('#e8f4f6','#5a7a9a'),.6+.3*Math.sin(t*2+x)));R(c,x-1,base-3,4,3,tone('#e2b53a','#8a7030'));
 if(built<.3)return;const th=Math.round((TOWER-3)*clamp((built-.3)/.5));R(c,x,base-3-th,1,th,tone('#f4f6f6','#a8b0c8'));R(c,x+1,base-3-th,1,th,tone('#b9c2c9','#6a7290'));
 if(built<.8)return;const face=game.snapshot.weather.direction_deg>180?-1:1;R(c,x-(face>0?1:3),hub-1,5,3,tone('#eef1f2','#a8b0c8'));R(c,x-(face>0?1:3),hub+1,5,1,tone('#b9c2c9','#6a7290'));if(built<1)return;
 const on=u.status==='Operating'&&u.output_mw>.02;rotor[u.id]=((rotor[u.id]??x%3)+(on?(.8+3.2*u.output_mw/(u.rated_mw||5))*dt:0))%(Math.PI*2);
 for(let k=0;k<3;k++){const a=rotor[u.id]+k*2.0944;L(c,x+.5,hub,x+.5+Math.cos(a)*ROTOR,hub+Math.sin(a)*ROTOR,tone('#fbfcfc','#c8cee0'));L(c,x+.5+Math.cos(a+.25)*1.5,hub+Math.sin(a+.25)*1.5,x+.5+Math.cos(a+.08)*ROTOR*.45,hub+Math.sin(a+.08)*ROTOR*.45,tone('#dfe4e8','#9aa2bc'));}
 R(c,x,hub,2,2,tone('#8a949c','#5a6080'));
 const blink=Math.floor(t*1.3)%2===0;if(u.status!=='Operating')P(c,x,hub-2,blink?(u.maintenance?'#ffb040':'#ff4a3a'):tone('#8a949c','#3a3e52'));else if(nightK>.4&&blink){P(c,x,hub-2,'#ff4a3a');glow(c,x,hub-2,2,'#ff4a3a',.35);}}
function vessel(c,x,y,t){y+=Math.round(Math.sin(t*1.5));for(const lx of [x+1,x+12])R(c,lx,y-9,1,12,tone('#8a8f9a','#4a5068'));R(c,x,y,14,4,tone('#c8463a','#6a2a30'));R(c,x,y,14,1,tone('#e06a5a','#8a3a40'));R(c,x+8,y-3,4,3,tone('#ece8e0','#6a6a80'));L(c,x+3,y-1,x+9,y-9,tone('#e2b53a','#8a7030'));if(light<.5)P(c,x+10,y-4,'#ffe08a');}
let lastT=0;
function frame(ms){requestAnimationFrame(frame);const g=current();if(!g||!document.querySelector('#scene .map-overlay'))return;if(reduced&&ms-(frame.last||0)<250)return;frame.last=ms;
 const t=ms/1000*(reduced?.25:1),dt=clamp(t-lastT,0,.1);lastT=t;const w=g.snapshot.weather,m=g.metrics,up=g.upgrades.includes('battery_phase2'),snow=(w.temperature_c??5)<-.5,zones=zoneState(g),key=Math.round(light*24)+'|'+snow+'|'+up+'|'+Object.entries(zones).map(([k,z])=>k+Math.round(z.ratio*20)+z.live).join();
 if(key!==cacheKey){cacheKey=key;buildCache(snow,up,zones);}
 ctx.imageSmoothingEnabled=false;ctx.drawImage(cache,0,0);const nightK=clamp((.6-light)/.45),wind=w.wind_10m_ms??5,dir=(w.direction_deg??270)*Math.PI/180,vx=-Math.sin(dir),vy=Math.cos(dir);
 // Sea surface: glints and wind streaks travel downwind.
 for(const [x,y,p] of SPARKS)if(water(x,y)&&Math.sin(t*1.7+p)>.86)P(ctx,x,y,rgba(tone('#ffffff','#c8d8ff'),.55));
 for(const [x0,y0,len,s] of STREAKS.slice(0,Math.round(clamp(wind/14)*STREAKS.length))){const x=((x0+t*wind*1.6*s*vx)%W+W)%W,y=((y0+t*wind*1.6*s*vy)%H+H)%H;if(water(x,y)&&water(x+vx*len,y+vy*len))L(ctx,x,y,x+vx*len,y+vy*len,rgba(tone('#e8f6fa','#6a8ab8'),.35));}
 // Power flow: dots run toward the substation, then on to the city, the battery or the grid.
 const br=g.breakers,f=g.faults||{},s=g.snapshot.turbines,strA=s.slice(0,4).reduce((a,u)=>a+u.output_mw,0),strB=s.slice(4,8).reduce((a,u)=>a+u.output_mw,0);
 cable(ctx,CABLES.a,br.collector_a&&br.farm&&!f.collector_a,t,1,strA);cable(ctx,CABLES.b,br.collector_b&&br.farm&&!f.collector_b,t,1,strB);cable(ctx,CABLES.farm,br.farm,t,1,strA+strB);
 cable(ctx,CABLES.city,br.transformer&&!f.transformer,t,1,m.served_mw);for(const d of g.snapshot.districts){const z=ZONES[d.id];if(z)cable(ctx,z.feeder,zones[d.id].live,t,1,d.served_mw);}cable(ctx,CABLES.bess,br.bess,t,-1,m.battery_mw);cable(ctx,CABLES.grid,br.pcc,t,-1,m.grid_mw);
 // Turbines; phase 2 sites grow while construction is under way.
 const p2=g.projects.find(p=>p.id==='wind_phase2'),prog=p2?clamp((g.step-p2.start)/Math.max(1,p2.finish-p2.start)):null;let crane=null;
 TURBINES.forEach(([x,hub],i)=>{const u=s[i];if(!u)return;const built=u.installed?1:prog!==null?.1+prog*.9:0;if(!u.installed&&prog!==null&&!crane)crane=[x+5,hub+TOWER-2];turbine(ctx,x,hub,u,t,built,dt);});
 if(crane)vessel(ctx,crane[0],crane[1],t);
 // Harbor traffic.
 const ferry=262+Math.round(Math.sin(t*.15)*4),bob=Math.round(Math.sin(t*1.2));R(ctx,ferry,151,20,4,tone('#2f4a6a','#1a2640'));R(ctx,ferry+4,149,10,2,tone('#ece8e0','#5a5a70'));R(ctx,ferry,155,20,1,rgba('#000000',.2));
 R(ctx,305,147+bob,11,3,tone('#b5523b','#5a2a30'));R(ctx,308,145+bob,4,2,tone('#ece8e0','#5a5a70'));
 // Cloud shadows drift with the wind by day.
 if(light>.2)for(const [x0,y0,cw,ch] of CLOUDS.slice(0,Math.round((w.cloud_fraction??.5)*CLOUDS.length))){const x=((x0+t*(1+wind*.5)*vx)%(W+cw)+W+cw)%(W+cw)-cw,y=((y0+t*(1+wind*.5)*vy)%(H+ch)+H+ch)%(H+ch)-ch,shade=rgba('#0a1830',.22*light);ctx.fillStyle=shade;
  // Cloud shadows are dithered ellipses, the pixel-art way of drawing transparency.
  for(let j=0;j<ch;j++){const k=(j+.5)/ch*2-1,half=Math.round(cw/2*Math.sqrt(1-k*k)),cx=Math.round(x+cw/2),yy=Math.round(y+j);for(let i=cx-half;i<cx+half;i++)if((i+yy)%2===0)ctx.fillRect(i,yy,1,1);}}
 // Load zones that are shed or switched off flash red; bus nodes show each feeder's state.
 const blink=Math.floor(t*2)%2;for(const [id,z] of Object.entries(ZONES)){const st=zones[id];if(!st)continue;const [x0,y0,wz,hz]=z.box,[nx,ny]=z.node,bad=!st.live||st.ratio<.99;
  if(bad&&blink){for(let x=x0;x<x0+wz;x+=2){P(ctx,x,y0,'#ff4a3a');P(ctx,x,y0+hz-1,'#ff4a3a');}for(let y=y0;y<y0+hz;y+=2){P(ctx,x0,y,'#ff4a3a');P(ctx,x0+wz-1,y,'#ff4a3a');}}
  R(ctx,nx-2,ny-2,5,5,tone('#2e3440','#05070f'));R(ctx,nx-1,ny-1,3,3,st.live?(st.ratio<.99?'#f2c55c':'#5fe08a'):'#ff4a3a');}
 if(nightK>0){for(const [x,y] of [[224,162],[264,162],[302,179],[352,179]]){P(ctx,x,y,'#f4f6ff');glow(ctx,x,y,4,'#dfe8ff',.25*nightK);}P(ctx,244,195,Math.floor(t*1.2)%2?'#ff4a3a':'#5a1a1a');}
 R(ctx,253,173,3,3,br.transformer?'#5fe08a':'#ff4a3a');R(ctx,233,173,3,3,br.pcc?'#5fe08a':'#ff4a3a');
 const soc=m.soc,full=Math.round(soc*10),sc=soc>.5?'#5fe08a':soc>.25?'#f2c55c':'#ff6f5e',pulse=Math.floor(t*3)%2;
 for(const [x,y,,h] of cells(up))for(let k=0;k<10;k++){let on=k<full;if(m.battery_mw<-.05&&k===full)on=!!pulse;if(m.battery_mw>.05&&k===full-1)on=!pulse;R(ctx,x+1+k*4,y+1,3,h-2,on?sc:tone('#4a4d5a','#20243a'));}
 if(dusk>0)R(ctx,0,0,W,H,rgba('#ff8a50',.10*dusk));}
requestAnimationFrame(frame);

// ---------- Overlay: labels and turbine click targets, aligned to map pixels ----------
const T=(x,y,s,cls='',extra='')=>`<text x="${x*U}" y="${y*U}" class="${cls}" ${extra}>${esc(s)}</text>`;
function pixelMap(){const g=current(),s=g.snapshot,m=g.metrics,br=g.breakers;let o=`<svg class="map-overlay" viewBox="0 0 ${W*U} ${H*U}" xmlns="http://www.w3.org/2000/svg">`;
 o+=T(7,15,'Bay offshore wind farm','t-title')+T(7,21,`${g.upgrades.includes('wind_phase2')?40:20} MW · 5 MW Reference turbine · 35 kV collector`,'t-sub')+T(7,29,'Wind → city · Surplus → battery','t-label')+T(7,35,`${n(m.wind_direct_pct,0)}% direct wind supply`,'t-sub');
 TURBINES.forEach(([x,hub],i)=>{const u=s.turbines[i];if(!u)return;const box=`x="${(x-15)*U}" y="${(hub-15)*U}" width="${31*U}" height="${(TOWER+17)*U}"`;
  o+=`<g class="unit" data-unit="${esc(u.id)}" tabindex="0" role="button" aria-label="Inspect turbine ${esc(u.id)}"><rect class="hit" ${box}/><rect class="frame" ${box}/>`+T(x,hub+TOWER+9,`${u.id} / ${u.installed?n(u.output_mw,2)+' MW':'reserved'}`,'t-unit','text-anchor="middle"')+T(x,hub+TOWER+14,u.installed?u.status:'Phase 2 site',u.status==='Operating'?'t-ok':u.installed?'t-warn':'t-faint','text-anchor="middle"')+'</g>';});
 o+=T(195,80,'Collector A',br.collector_a&&br.farm?'t-sub':'t-trip','text-anchor="end"')+T(195,154,'Collector B',br.collector_b&&br.farm?'t-sub':'t-trip','text-anchor="end"');
 o+=T(250,15,'Baltic coast','t-title')+T(362,12,'N ↑','t-label','text-anchor="end"')+T(250,22,`City demand ${n(m.demand_mw,2)} MW · served ${n(m.supply_pct,1)}%`,m.unserved_mw>.01?'t-trip':'t-sub');
 for(const d of s.districts){const z=ZONES[d.id];if(!z)continue;const live=br[d.id]&&br.transformer,shed=d.served_mw<d.demand_mw-.01;o+=T(z.label[0],z.label[1],d.name,'t-label','text-anchor="middle"')+T(z.label[0],z.label[1]+6,live?`${n(d.served_mw,2)} / ${n(d.demand_mw,2)} MW`:'Feeder open',live&&!shed?'t-sub':'t-trip','text-anchor="middle"');}
 o+=T(252,193,'Onshore substation','t-label')+T(252,199,'110 / 35 / 10 kV','t-sub')+T(327,208,`Battery ${n(s.storage.power_mw,0)} MW / ${n(s.storage.capacity_mwh,0)} MWh`,'t-label','text-anchor="middle"')+T(327,214,`SOC ${n(m.soc*100,0)}% · ${m.battery_mw>.05?'discharging':m.battery_mw<-.05?'charging':'idle'}`,'t-sub','text-anchor="middle"');
 o+=T(236,213,br.pcc?`Grid ${m.grid_mw>=0?'import':'export'} ${n(Math.abs(m.grid_mw),2)} MW`:'PCC open · Anti-islanding',br.pcc?'t-sub':'t-trip','text-anchor="end"')+T(7,213,`Hub-height wind ${n(m.wind_ms)} m/s · Direction ${n(s.weather.direction_deg,0)}°`,'t-sub');
 return o+'</svg>';}
window.pixelMap=pixelMap;
})();
