'use strict';
// Player saves live in this browser (IndexedDB). The server keeps nothing between requests: each action sends the
// signed core state and receives the next one. Save files are replays that also carry the signed state and chart history.
const SAVE_FORMAT='powergame.coastal.v2',HISTORY_LIMIT=672,COMMAND_LIMIT=2048;
const saveStore=(()=>{let db,memory=null;
 const open=()=>db??=new Promise(resolve=>{try{const r=indexedDB.open('powerbolaget',1);r.onupgradeneeded=()=>r.result.createObjectStore('saves');r.onsuccess=()=>resolve(r.result);r.onerror=r.onblocked=()=>resolve(null);}catch{resolve(null);}});
 const run=async(mode,fn)=>{const d=await open();if(!d)return undefined;return new Promise((resolve,reject)=>{const t=d.transaction('saves',mode),req=fn(t.objectStore('saves'));t.oncomplete=()=>resolve(req.result);t.onerror=t.onabort=()=>reject(t.error||Error('Browser storage failed; export your save.'));});};
 // Without IndexedDB (some private windows) the save lives in memory until the page closes.
 return{persistent:async()=>!!await open(),get:async()=>(await run('readonly',s=>s.get('current')))??memory,put:async save=>{memory=save;await run('readwrite',s=>s.put(save,'current'));}};})();
function gameFrom(save){return{...JSON.parse(save.state),...save.view,history:save.history,has_checkpoint:!!save.checkpoint};}
function savePart(save){return structuredClone({seed:save.seed,commands:save.commands,state:save.state,sig:save.sig,view:save.view,history:save.history});}
function downloadSave(save){const file={format:SAVE_FORMAT,seed:save.seed,commands:save.commands,state:save.state,sig:save.sig,history:save.history};
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(file)],{type:'application/json'}));a.download=`powerbolaget-day-${Math.floor(JSON.parse(save.state).step/96)+1}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
