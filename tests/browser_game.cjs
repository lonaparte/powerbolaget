// Browser tests of the game client. Run with Node.js, Playwright and Chromium:
//   POWERBOLAGET_TEST_PYTHON=.venv/bin/python node --test tests/browser_game.cjs
const assert = require('node:assert/strict');
const {before, after, test} = require('node:test');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
let browser, server, url;
before(async () => {
  server = spawn(process.env.POWERBOLAGET_TEST_PYTHON || 'python',
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '0'],
    {cwd: root, env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}, stdio: ['ignore', 'ignore', 'pipe']});
  await new Promise((resolve, reject) => {
    let log = '';
    const timeout = setTimeout(() => reject(Error('Test server startup timed out: ' + log)), 30000);
    server.on('exit', code => { clearTimeout(timeout); reject(Error('Test server exited: ' + code + ' ' + log)); });
    server.stderr.on('data', chunk => {
      log += chunk;
      const match = log.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
      if (match) { url = match[1]; clearTimeout(timeout); resolve(); }
    });
  });
  browser = await chromium.launch({headless: true, ...(process.env.POWERBOLAGET_TEST_CHROMIUM ? {executablePath: process.env.POWERBOLAGET_TEST_CHROMIUM} : {})});
});
after(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
});

async function open(context) {
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(url);
  await page.waitForFunction(() => window.PB && PB.snap && document.getElementById('boot').classList.contains('gone'), null, {timeout: 30000});
  return {page, errors};
}

test('the island starts running on its own and every view renders', {timeout: 90000}, async t => {
  const context = await browser.newContext({viewport: {width: 1366, height: 860}});
  t.after(() => context.close());
  const {page, errors} = await open(context);
  const start = await page.evaluate(() => PB.snap.minute);
  assert.equal(await page.locator('#date').textContent(), await page.evaluate(() => PB.snap.label));
  await page.waitForFunction(m => PB.snap.minute >= m + 60, start, {timeout: 20000});
  for (const view of ['grid', 'island', 'economy']) {
    await page.click(`[data-view="${view}"]`);
    await page.waitForTimeout(800);
  }
  await page.click('[data-tab="firms"]');
  await page.waitForSelector('#econ table tbody tr');
  await page.click('[data-view="island"]');
  // The day theme is the default; night and the day/night cycle are switched on by hand and remembered.
  assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'day');
  await page.click('[data-theme-mode="night"]');
  assert.equal(await page.evaluate(() => [document.documentElement.dataset.theme, PB.lightTarget()].join()), 'night,0');
  await page.waitForFunction(() => PB.light() < .05, null, {timeout: 5000});   // the map fades rather than jumps
  await page.click('[data-theme-mode="auto"]');
  assert.equal(await page.evaluate(() => localStorage.getItem('pb-theme-mode')), 'auto');
  await page.getByLabel('Wind field').check();
  await page.waitForTimeout(300);
  assert.deepEqual(errors, []);
});

test('a parcel shows its land, wind and turbine site, and a turbine can be built there', {timeout: 90000}, async t => {
  const context = await browser.newContext({viewport: {width: 1366, height: 860}});
  t.after(() => context.close());
  const {page, errors} = await open(context);
  await page.evaluate(() => { PB.running = false; });
  await page.evaluate(() => PB.select('parcel_68_124'));
  await page.waitForFunction(() => document.querySelector('#inspector h2')?.textContent === 'FARMLAND');
  assert.match(await page.locator('#inspector').textContent(), /Mean wind at 100 m/);
  await page.click('[data-buildhere]');
  await page.waitForSelector('#dialog[open] #dok');
  assert.match(await page.locator('#dialogBody').textContent(), /Capital cost/);
  await page.click('#dok');
  await page.waitForFunction(() => PB.snap.projects.some(p => p.kind === 'turbine'));
  assert.deepEqual(errors, []);
});

test('reloading the page continues the game from the browser save', {timeout: 90000}, async t => {
  const context = await browser.newContext({viewport: {width: 1366, height: 860}});
  t.after(() => context.close());
  const {page} = await open(context);
  await page.waitForFunction(() => PB.snap.minute >= 120, null, {timeout: 20000});
  await page.evaluate(async () => { PB.running = false; await PB.saveNow(); });
  const saved = await page.evaluate(() => PB.snap.minute);
  await page.reload();
  await page.waitForFunction(() => window.PB && PB.snap && document.getElementById('boot').classList.contains('gone'), null, {timeout: 30000});
  assert.ok(await page.evaluate(() => PB.snap.minute) >= saved);
});

test('the layout fits a phone screen', {timeout: 60000}, async t => {
  const context = await browser.newContext({viewport: {width: 390, height: 844}});
  t.after(() => context.close());
  const {page, errors} = await open(context);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), 0);
  assert.deepEqual(errors, []);
});

test('engineering, retail offers and teaching-data recording work through the client', {timeout:90000}, async t => {
  const context=await browser.newContext({viewport:{width:1366,height:860}});
  t.after(()=>context.close());
  const {page,errors}=await open(context);
  await page.evaluate(()=>{PB.running=false;});
  await page.click('#engineering');
  await page.selectOption('#engineeringForm [name="type"]','station');
  await page.fill('#engineeringForm [name="name"]','Teaching station');
  await page.click('#engineeringForm button[type="submit"]');
  await page.waitForSelector('#dialog[open] #dok');
  assert.match(await page.locator('#dialogBody').textContent(),/Independent 110 kV/);
  await page.click('#dok');
  await page.waitForFunction(()=>PB.snap.projects.some(p=>p.kind==='station'));
  await page.click('[data-view="economy"]');
  await page.click('[data-tab="finance"]');
  const policy=page.locator('form[data-retail="business"]');
  await policy.locator('[name="network_fee"]').fill('.35');
  await policy.locator('button[type="submit"]').click();
  await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('business contract offers updated'));
  assert.equal(await page.evaluate(async()=>(await PB.call('/table',{name:'finance'})).retail_policy.business.network_fee),.35);
  await page.click('#menuBtn');
  await page.click('[data-menu="history"]');
  await page.selectOption('#dataExport [name="key"]','res_z01');
  await page.click('#recordObject');
  await page.waitForFunction(()=>document.getElementById('dataStatus').textContent.includes('recording started'));
  await page.evaluate(async()=>{const j=await PB.call('/tick',{minutes:2});PB.apply(j.snapshot);});
  await page.selectOption('#dataExport [name="resolution"]','minute');
  await page.fill('#dataExport [name="end"]','9999');
  const downloaded=page.waitForEvent('download');
  await page.click('#dataExport button[type="submit"]');
  assert.match((await downloaded).suggestedFilename(),/res_z01\.csv$/);
  assert.deepEqual(errors,[]);
});
