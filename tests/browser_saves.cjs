// Run with Node.js, Playwright and Chromium: node --test tests/browser_saves.cjs
const assert = require('node:assert/strict');
const {before, after, test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
let browser, server, data, url;
before(async () => {
  data = fs.mkdtempSync(path.join(os.tmpdir(), 'powerbolaget-browser-saves-'));
  server = spawn(process.env.POWERBOLAGET_TEST_PYTHON || 'python',
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '0'],
    {cwd:root, env:{...process.env, COASTAL_DATA:data, PYTHONDONTWRITEBYTECODE:'1'}, stdio:['ignore', 'ignore', 'pipe']});
  await new Promise((resolve, reject) => {
    let log = '';
    const timeout = setTimeout(() => reject(Error('Test server startup timed out: '+log)), 20000);
    server.on('error', error => {clearTimeout(timeout);reject(error);});
    server.on('exit', code => {clearTimeout(timeout);reject(Error('Test server exited: '+code+' '+log));});
    server.stderr.on('data', chunk => {
      log += chunk;
      const match = log.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
      if(match) {url=match[1];clearTimeout(timeout);resolve();}
    });
  });
  browser = await chromium.launch({headless:true,
    ...(process.env.POWERBOLAGET_TEST_CHROMIUM ? {executablePath:process.env.POWERBOLAGET_TEST_CHROMIUM} : {})});
});
after(async () => {
  if(browser) await browser.close();
  if(server && server.exitCode === null) {
    await new Promise(resolve => {server.once('exit', resolve);server.kill('SIGTERM');});
  }
  if(data) fs.rmSync(data, {recursive:true, force:true});
});

async function scenario(t, memoryOnly=false) {
  const context = await browser.newContext();
  t.after(() => context.close());
  if(memoryOnly) await context.addInitScript(() => {
    Object.defineProperty(window, 'indexedDB', {get(){throw Error('Storage disabled');}});
  });
  const page = await openPage(context);
  return {context, page};
}
async function openPage(context) {
  const page = await context.newPage();
  await page.goto(url);
  await page.waitForFunction(() => typeof game !== 'undefined' && game && !busy);
  assert.equal(await page.locator('#connection').textContent(), 'Saved in this browser');
  return page;
}
async function current(page) {
  return page.evaluate(() => ({save:structuredClone(save), game:structuredClone(game)}));
}
async function consistent(page) {
  const result = await page.evaluate(async () => {
    const replayed = await api('/import', {save:{format:SAVE_FORMAT, seed:save.seed, commands:save.commands}});
    return {stored:save.state, replayed:replayed.state};
  });
  assert.equal(result.stored, result.replayed, 'signed state must match command replay');
}

test('pending simulation blocks checkpoint, new-scenario and import operations', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.evaluate(async () => {
    await command({kind:'advance', steps:4});
    await action('checkpoint');
    await command({kind:'advance', steps:4});
  });
  const initial = await current(page);
  let release, received;
  const gate = new Promise(resolve => release=resolve);
  const responseReady = new Promise(resolve => received=resolve);
  await page.route('**/api/command', async route => {
    const response = await route.fetch();
    received();await gate;await route.fulfill({response});
  });
  try {
    await page.locator('#stepSize').selectOption('672');
    await page.locator('#advance').click();await responseReady;
    assert.equal(await page.locator('[data-modal="saves"]').isDisabled(), true);
    await page.evaluate(async () => {
      for(const kind of ['restore', 'checkpoint', 'new', 'import']) await action(kind);
      saves();
    });
    assert.deepEqual(await current(page), initial);
    assert.equal(await page.locator('#dialog').evaluate(el => el.open), false);
  } finally {release();}
  await page.waitForFunction(() => !busy && game.step === 680);
  await consistent(page);
  await page.locator('[data-modal="saves"]').click();
  await page.locator('[data-action="restore"]').click();
  await page.waitForFunction(() => !busy && game.step === 4);
  await consistent(page);
});

test('concurrent tabs commit one save and keep the losing tab unchanged', {timeout:20000}, async t => {
  const {context, page:first} = await scenario(t);
  const second = await openPage(context);
  const baseline = await second.evaluate(() => structuredClone(save));
  for(const page of [first, second]) await page.evaluate(s => {save=s;game=gameFrom(save);render();}, baseline);
  const previous = await Promise.all([current(first), current(second)]);
  const outcomes = await Promise.all([
    first.evaluate(() => command({kind:'advance', steps:4})),
    second.evaluate(() => command({kind:'weather', target:'calm'}))
  ]);
  assert.equal(outcomes.filter(Boolean).length, 1);
  const winner = outcomes[0] ? first : second, loser = outcomes[0] ? second : first;
  const winning = (await current(winner)).save;
  assert.deepEqual(await winner.evaluate(() => saveStore.get()), winning);
  assert.equal(winning.rev, baseline.rev+1);
  assert.equal(winning.commands.length, 1);
  assert.deepEqual(await current(loser), previous[outcomes[0] ? 1 : 0]);
  assert.match(await loser.locator('#toast').textContent(), /another tab/);
  await consistent(winner);
  await loser.reload();await loser.waitForFunction(() => !busy && game);
  assert.equal((await current(loser)).save.state, winning.state);
});

test('IndexedDB refuses two writes from the same revision', {timeout:20000}, async t => {
  const {context, page:first} = await scenario(t);
  const second = await openPage(context);
  const baseline = await second.evaluate(() => structuredClone(save));
  const outcomes = await Promise.allSettled([
    [first, {kind:'advance', steps:4}], [second, {kind:'weather', target:'calm'}]
  ].map(([page, action]) => page.evaluate(async ({baseline, action}) => {
    const b = await api('/command', {state:baseline.state, sig:baseline.sig, action});
    return saveStore.put({...baseline, state:b.state, sig:b.sig, view:b.view, history:b.rows,
      commands:[...baseline.commands, action]});
  }, {baseline, action})));
  const accepted = outcomes.filter(result => result.status === 'fulfilled');
  assert.equal(accepted.length, 1, 'only one candidate from a shared revision may commit');
  assert.match(outcomes.find(result => result.status === 'rejected').reason.message, /another tab/);
  assert.deepEqual(await first.evaluate(() => saveStore.get()), accepted[0].value);
});

test('checkpoint persistence holds the same-page write lock', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.evaluate(() => {
    const original = saveStore.put;
    const gate = new Promise(resolve => window.releaseWrite=resolve);
    saveStore.put = async candidate => {window.writeStarted=true;await gate;return original(candidate);};
    window.checkpointWrite=action('checkpoint');
  });
  await page.waitForFunction(() => window.writeStarted);
  assert.equal(await page.evaluate(() => busy), true);
  assert.equal(await page.evaluate(() => command({kind:'advance', steps:4})), false);
  await page.evaluate(async () => {window.releaseWrite();await window.checkpointWrite;});
  assert.equal((await current(page)).game.step, 0);
  assert.equal((await current(page)).game.has_checkpoint, true);
  await consistent(page);
});

test('file import acquires the write lock before reading the file', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.locator('[data-modal="saves"]').click();
  await page.evaluate(() => {
    const original=File.prototype.text;
    File.prototype.text=function(){window.readStarted=true;return new Promise(resolve => window.releaseFile=()=>resolve(original.call(this)));};
  });
  await page.locator('#importFile').setInputFiles({name:'legacy-save.json', mimeType:'application/json',
    buffer:Buffer.from(JSON.stringify({format:'powergame.coastal.v2', seed:7, commands:[{kind:'advance', steps:4}]}))});
  await page.waitForFunction(() => window.readStarted);
  assert.equal(await page.evaluate(() => busy), true);
  assert.equal(await page.evaluate(() => command({kind:'advance', steps:4})), false);
  await page.evaluate(() => window.releaseFile());
  await page.waitForFunction(() => !busy && game.seed === 7 && game.step === 4);
  await consistent(page);
});

test('a file that is not a save only warns and keeps the saved scenario and status', {timeout:20000}, async t => {
  const {page} = await scenario(t), before = await current(page);
  for(const buffer of [Buffer.from('not json'), Buffer.from(JSON.stringify({format:'other', commands:[]}))]) {
    await page.locator('[data-modal="saves"]').click();
    await page.locator('#importFile').setInputFiles({name:'notes.json', mimeType:'application/json', buffer});
    await page.waitForFunction(() => !busy && document.getElementById('toast').className.includes('error'));
    assert.match(await page.locator('#toast').textContent(), /not a Powerbolaget save file/);
    assert.equal(await page.locator('#connection').textContent(), 'Saved in this browser');
    assert.deepEqual(await current(page), before);
    await page.evaluate(() => {if(document.getElementById('dialog').open) closeModal();document.getElementById('toast').className='';});
  }
});

test('opening the scenario in another tab keeps the first tab writable', {timeout:20000}, async t => {
  const {context, page:first} = await scenario(t);
  const rev = (await current(first)).save.rev;
  const second = await openPage(context);
  assert.equal((await current(second)).save.rev, rev, 'loading an unchanged save must not write it');
  assert.equal(await first.evaluate(() => command({kind:'advance', steps:4})), true);
  assert.equal(await second.evaluate(() => command({kind:'advance', steps:4})), false);
  assert.match(await second.locator('#toast').textContent(), /another tab/);
  await consistent(first);
});

test('an aborted IndexedDB transaction leaves the previous state and replay intact', {timeout:20000}, async t => {
  const {page} = await scenario(t), before = await current(page);
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function(...args){const request=original.apply(this,args);this.transaction.abort();return request;};
    window.restorePut = () => IDBObjectStore.prototype.put=original;
  });
  assert.equal(await page.evaluate(() => command({kind:'advance', steps:4})), false);
  await page.evaluate(() => window.restorePut());
  assert.deepEqual(await current(page), before);
  assert.deepEqual(await page.evaluate(() => saveStore.get()), before.save);
  assert.equal(await page.locator('#connection').textContent(), 'Action failed');
});

test('a rejected checkpoint or restore does not change the current scenario', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.evaluate(async () => {
    await command({kind:'advance', steps:4});await action('checkpoint');await command({kind:'advance', steps:4});
  });
  const before = await current(page);
  await page.evaluate(() => {saveStore.put=async()=>{throw Error('Storage write rejected');};});
  for(const kind of ['checkpoint', 'restore']) {
    await page.evaluate(kind => action(kind), kind);
    assert.deepEqual(await current(page), before);
  }
});

test('a rejected new scenario or file import preserves the current save', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.evaluate(() => command({kind:'advance', steps:4}));
  const before = await current(page);
  await page.evaluate(() => {saveStore.put=async()=>{throw Error('Storage write rejected');};});
  const results = await page.evaluate(async () => {
    const errors=[];
    for(const operation of [()=>startNew(7), ()=>loadSave({format:SAVE_FORMAT, seed:7, commands:[]})]) {
      try {await operation();} catch(e) {errors.push(e.message);}
    }
    return errors;
  });
  assert.equal(results.length, 2);
  assert.deepEqual(await current(page), before);
});

test('signature recovery preserves the full chart history and command replay', {timeout:20000}, async t => {
  const {page} = await scenario(t);
  await page.evaluate(async () => {
    await command({kind:'advance', steps:4});save.sig='0'.repeat(64);await command({kind:'advance', steps:4});
  });
  const saved = (await current(page)).save;
  assert.equal(saved.history.length, 8);
  assert.equal(saved.commands.length, 2);
  await consistent(page);
});

test('memory-only saves use independent snapshots and retain checkpoints', {timeout:20000}, async t => {
  const {page} = await scenario(t, true);
  assert.equal(await page.evaluate(() => saveStore.persistent()), false);
  await page.evaluate(async () => {
    await command({kind:'advance', steps:4});await action('checkpoint');await command({kind:'advance', steps:4});await action('restore');
  });
  const saved = (await current(page)).save;
  assert.equal(JSON.parse(saved.state).step, 4);
  assert.deepEqual(await page.evaluate(() => saveStore.get()), saved);
  await page.evaluate(() => {save.commands.push({kind:'weather',target:'calm'});});
  assert.deepEqual(await page.evaluate(() => saveStore.get()), saved, 'memory storage must not alias the page save');
});
