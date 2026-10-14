'use strict';
// Player saves live in this browser (IndexedDB). The server keeps nothing between requests: each action sends the
// signed core state and receives the next one. Save files are replays that also carry the signed state and chart history.
const SAVE_FORMAT='powergame.coastal.v2',HISTORY_LIMIT=672,COMMAND_LIMIT=2048;
const saveStore=(()=>{let db,memory=null;
 const open=()=>db??=new Promise(resolve=>{try{const r=indexedDB.open('powerbolaget',1);r.onupgradeneeded=()=>r.result.createObjectStore('saves');r.onsuccess=()=>resolve(r.result);r.onerror=r.onblocked=()=>resolve(null);}catch{resolve(null);}});
 const conflict=()=>Error('This scenario changed in another tab. Reload the page to continue.');
 const storageError=()=>Error('Browser storage failed; export your save.');
 const get=async()=>{const d=await open();if(!d)return structuredClone(memory);return new Promise((resolve,reject)=>{const t=d.transaction('saves','readonly'),req=t.objectStore('saves').get('current');t.oncomplete=()=>resolve(req.result??null);t.onerror=t.onabort=()=>reject(t.error||storageError());});};
 const put=async save=>{
  const next=structuredClone(save),d=await open();
  if(!d){if(memory&&memory.rev!==next.rev)throw conflict();next.rev=(next.rev||0)+1;memory=structuredClone(next);return next;}
  // The revision check and write share one transaction, including across tabs.
  return new Promise((resolve,reject)=>{
   const t=d.transaction('saves','readwrite'),store=t.objectStore('saves'),req=store.get('current');let failure;
   req.onsuccess=()=>{if(req.result&&req.result.rev!==next.rev){failure=conflict();t.abort();return;}next.rev=(next.rev||0)+1;store.put(next,'current');};
   t.oncomplete=()=>{memory=structuredClone(next);resolve(next);};
   t.onerror=t.onabort=()=>reject(failure||t.error||storageError());
  });
 };
 // Without IndexedDB (some private windows) the save lives in memory until the page closes.
 return{persistent:async()=>!!await open(),get,put};})();
function gameFrom(save){return{...JSON.parse(save.state),...save.view,history:save.history,has_checkpoint:!!save.checkpoint};}
function savePart(save){return structuredClone({seed:save.seed,commands:save.commands,state:save.state,sig:save.sig,view:save.view,history:save.history});}
function downloadSave(save){const file={format:SAVE_FORMAT,seed:save.seed,commands:save.commands,state:save.state,sig:save.sig,history:save.history};
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(file)],{type:'application/json'}));a.download=`powerbolaget-day-${Math.floor(JSON.parse(save.state).step/96)+1}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
