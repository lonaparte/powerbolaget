// Measured rendering and large-table acceptance in headless Chromium.
const fs=require('node:fs');
const path=require('node:path');
const {spawn,execFileSync}=require('node:child_process');
const {chromium}=require('playwright');

const root=path.resolve(__dirname,'..');
const savePath=process.argv[2]||'/workspace/powerbolaget-scale-full-save.json';
const output=process.argv[3]||path.join(root,'results','acceptance-browser.json');

async function serverUrl(server){return new Promise((resolve,reject)=>{
  let log='';const timer=setTimeout(()=>reject(Error('server timeout '+log)),30000);
  server.stderr.on('data',chunk=>{log+=chunk;const found=log.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);if(found){clearTimeout(timer);resolve(found[1]);}});
  server.on('exit',code=>{clearTimeout(timer);reject(Error(`server exited ${code} ${log}`));});
});}

async function measureMap(page,view){
  await page.click(`[data-view="${view}"]`);
  await page.evaluate(()=>PB.map.resetPerformance());
  await page.waitForTimeout(4000);
  return page.evaluate(()=>PB.map.performance());
}

(async()=>{
  const python=process.env.POWERBOLAGET_TEST_PYTHON||'python';
  const server=spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','0'],
    {cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','ignore','pipe']});
  let browser;
  try{
    const url=await serverUrl(server);
    browser=await chromium.launch({headless:true,...(process.env.POWERBOLAGET_TEST_CHROMIUM?{executablePath:process.env.POWERBOLAGET_TEST_CHROMIUM}:{})});
    const page=await browser.newPage({viewport:{width:1366,height:860}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    await page.goto(url);await page.waitForFunction(()=>window.PB&&PB.snap&&document.getElementById('boot').classList.contains('gone'),null,{timeout:30000});
    await page.evaluate(()=>{PB.running=false;});
    const baseline={island:await measureMap(page,'island'),grid:await measureMap(page,'grid')};
    const save=JSON.parse(fs.readFileSync(savePath,'utf8'));
    const loadMs=await page.evaluate(async state=>{const start=performance.now();PB.adopt(await PB.api('/session/load',{save:state}));PB.running=false;return performance.now()-start;},save);
    const counts=await page.evaluate(()=>({pops:PB.snap.kpi.pops,turbines:Object.keys(PB.static.turbines).length,buses:Object.keys(PB.static.buses).length,branches:Object.keys(PB.static.branches).length}));
    const full={island:await measureMap(page,'island'),grid:await measureMap(page,'grid')};
    const tableStart=Date.now();await page.click('[data-view="economy"]');await page.click('[data-tab="pops"]');
    await page.waitForFunction(()=>document.querySelector('#econ .actions span')?.textContent.includes('rows'),null,{timeout:30000});
    const firstRows=await page.locator('#econ tbody tr').count(),tableMs=Date.now()-tableStart;
    const pageText=await page.locator('#econ .actions span').textContent();
    await page.click('#econ [data-page="1"]');
    await page.waitForFunction(()=>document.querySelector('#econ .actions span')?.textContent.trim().startsWith('2 /'));
    const secondRows=await page.locator('#econ tbody tr').count();
    if(firstRows!==100||secondRows!==100||errors.length)throw Error(JSON.stringify({firstRows,secondRows,errors}));
    const cpu=fs.readFileSync('/proc/cpuinfo','utf8').match(/^model name\s*:\s*(.+)$/m)?.[1]||process.arch;
    const report={git_commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),method:'Headless Chromium, 1366x860, 4 seconds per map view after counter reset; FPS includes animation-frame scheduling',
      chromium:await browser.version(),cpu,save_bytes:fs.statSync(savePath).size,load_round_trip_ms:loadMs,counts,
      baseline,full,pop_table:{load_and_render_ms:tableMs,rows_per_page:firstRows,second_page_rows:secondRows,page_text:pageText,total_objects:counts.pops},errors};
    fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  }finally{
    if(browser)await browser.close();
    if(server.exitCode===null)await new Promise(resolve=>{server.once('exit',resolve);server.kill('SIGTERM');});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
