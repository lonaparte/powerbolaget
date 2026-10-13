'use strict';
// Reference data and the seven-day weather outlook, computed in the browser.
// The outlook reproduces app/climate.py, including Python's random.Random(seed).gauss(0, 1);
// tests/test_browser_climate.py checks it against the Python implementation.
const climate=(()=>{
let ref=null;const knots=new Map(),days=new Map();
// First four 32-bit outputs of CPython's MT19937 seeded with an integer (init_by_array on |seed|).
function mt(seed){const N=624,s=new Uint32Array(N),key=[];let n=Math.abs(seed);do{key.push(n%4294967296);n=Math.floor(n/4294967296);}while(n>0);
 s[0]=19650218;for(let i=1;i<N;i++)s[i]=(Math.imul(1812433253,s[i-1]^(s[i-1]>>>30))+i)>>>0;
 let i=1,j=0;for(let k=Math.max(N,key.length);k;k--){s[i]=((s[i]^Math.imul(s[i-1]^(s[i-1]>>>30),1664525))+key[j]+j)>>>0;i++;j++;if(i>=N){s[0]=s[N-1];i=1;}if(j>=key.length)j=0;}
 for(let k=N-1;k;k--){s[i]=((s[i]^Math.imul(s[i-1]^(s[i-1]>>>30),1566083941))-i)>>>0;i++;if(i>=N){s[0]=s[N-1];i=1;}}
 s[0]=0x80000000;const out=[];
 for(let k=0;k<4;k++){const y=(s[k]&0x80000000)|(s[k+1]&0x7fffffff);let v=s[k+397]^(y>>>1)^(y&1?0x9908b0df:0);v^=v>>>11;v^=(v<<7)&0x9d2c5680;v^=(v<<15)&0xefc60000;v^=v>>>18;out.push(v>>>0);}
 return out;}
function gauss(seed){const w=mt(seed),r1=((w[0]>>>5)*67108864+(w[1]>>>6))/9007199254740992,r2=((w[2]>>>5)*67108864+(w[3]>>>6))/9007199254740992;
 return Math.cos(r1*(2*Math.PI))*Math.sqrt(-2*Math.log(1-r2));}
function normal(key,day){const [mean,terms]=ref.climate.coefficients[key];let sum=0;terms.forEach(([a,b],i)=>{const k=i+1;sum+=a*Math.cos(2*Math.PI*k*day/365)+b*Math.sin(2*Math.PI*k*day/365);});const value=mean+sum;return key==='ALLSKY_SFC_SW_DWN'?Math.exp(value):value;}
function dayNoise(seed,day,channel){const id=seed+'|'+day+'|'+channel;if(!knots.has(id)){let sum=0,norm=0;
 for(let k=0;k<16;k++){const w=.72**k;sum+=w*gauss(seed*1000003+(day-k)*9176+channel*15485863);}for(let k=0;k<16;k++)norm+=.72**k*.72**k;knots.set(id,sum/Math.sqrt(norm));}return knots.get(id);}
function smooth(seed,time,channel,scale=1){const point=time/scale,i=Math.floor(point),f=point-i,blend=f*f*f*(10+f*(-15+6*f));return dayNoise(seed,i,channel)*(1-blend)+dayNoise(seed,i+1,channel)*blend;}
function geometry(time){const declination=23.44*Math.PI/180*Math.sin(2*Math.PI*(time+1-81)/365),lat=ref.climate.latitude*Math.PI/180,a=Math.sin(lat)*Math.sin(declination),b=Math.cos(lat)*Math.cos(declination);
 const angle=Math.acos(Math.max(-1,Math.min(1,-Math.tan(lat)*Math.tan(declination)))),e=2*Math.PI*(time+1-81)/365,equation=9.87*Math.sin(2*e)-7.53*Math.cos(e)-1.5*Math.sin(e),noon=12+(15-ref.climate.longitude)/15-equation/60;
 return{daylight_hours:24*angle/Math.PI,shape:Math.max(0,a+b*Math.cos(((time%1)*24-noon)*Math.PI/12)),area:24/Math.PI*(a*angle+b*Math.sin(angle))};}
// Normal climate only: the outlook ignores operator-selected weather tests, as on the server.
function instant(seed,time){const hour=(time%1)*24,slow=smooth(seed,time,0),gust=smooth(seed,time,4,1/12),cloudNoise=.4*slow+.82*smooth(seed,time,1)+.18*smooth(seed,time,5,1/6);
 const wind10=Math.max(.2,normal('WS10M',time)*Math.exp(.26*slow-.26**2/2)+.3*Math.sin((hour-8)*Math.PI/12)+.22*gust),solar=geometry(time),cloud=Math.max(.05,Math.min(.98,.65+.18*cloudNoise));
 return{wind10,temperature:normal('T2M',time)+2.5*smooth(seed,time,2)+2*(1-.5*cloud)*Math.sin((hour-9)*Math.PI/12),
  irradiance:Math.min(1100,normal('ALLSKY_SFC_SW_DWN',time)*Math.exp(-.38*cloudNoise-.38**2/2)*1000*solar.shape/solar.area),daylight:solar.daylight_hours};}
function solarDay(seed,day){const id=seed+'|'+day;if(!days.has(id)){let sum=0;for(let i=0;i<96;i++)sum+=instant(seed,day+i/96).irradiance;days.set(id,sum*.25/1000);}return days.get(id);}
function outlook(seed,step){if(!ref)return [];const out=[],first=Math.floor(step/96);
 for(let day=first;day<first+7;day++){const hours=[];for(let h=0;h<24;h++)hours.push(instant(seed,(day*96+h*4)/96));let wind=0,temp=0;for(const x of hours){wind+=x.wind10;}for(const x of hours){temp+=x.temperature;}
  const date=new Date(Date.UTC(2030,0,1+day));out.push({date:`${String(date.getUTCMonth()+1).padStart(2,'0')}-${String(date.getUTCDate()).padStart(2,'0')}`,wind_ms:wind/24,temperature_c:temp/24,solar_kwh_m2:solarDay(seed,day),daylight_hours:hours[0].daylight});}
 return out;}
// Fixed reference data is fetched once per visit and kept for offline use.
async function load(){try{const r=await fetch('/api/reference');if(!r.ok)throw Error(r.statusText);ref=await r.json();try{localStorage.setItem('powerbolaget-reference',JSON.stringify(ref));}catch{}}
 catch{try{ref=JSON.parse(localStorage.getItem('powerbolaget-reference'));}catch{}}knots.clear();days.clear();return ref;}
return{load,outlook,configure(r){ref=r;knots.clear();days.clear();},get reference(){return ref;}};
})();
