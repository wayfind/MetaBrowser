import assert from 'node:assert/strict';
const port = Number(process.argv[2]);
assert.equal(port, 18877);
class Client {
  static async open(url) {
    assert(url.startsWith('ws://127.0.0.1:18877/'));
    const self = new Client(); self.ws = new WebSocket(url); self.pending = new Map(); self.id = 0;
    await new Promise((resolve, reject) => { self.ws.onopen = resolve; self.ws.onerror = reject; });
    self.ws.onmessage = event => {
      const message = JSON.parse(event.data), p = self.pending.get(message.id);
      if (!p) return;
      self.pending.delete(message.id); clearTimeout(p.timer);
      message.error ? p.reject(Error(message.error.message)) : p.resolve(message.result);
    };
    return self;
  }
  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      const timer = setTimeout(() => { this.pending.delete(id); reject(Error(method + ' timed out')); }, 30000);
      this.pending.set(id, {resolve, reject, timer}); this.ws.send(JSON.stringify({id, method, params}));
    });
  }
  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true});
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  close() {
    this.ws.close();
    for (const p of this.pending.values()) {clearTimeout(p.timer);p.reject(Error('Owned connection closed'));}
    this.pending.clear();
  }
}
const A = 'http://127.0.0.1:18878', B = 'http://localhost:18878';
const markers = {firstA:'first-a', firstB:'first-b', aUnderB:'a-under-b', bUnderA:'b-under-a'};
const targets = () => fetch(`http://127.0.0.1:${port}/json/list`).then(r=>r.json());
const clients = [];
const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const browser = await Client.open(version.webSocketDebuggerUrl); clients.push(browser);
const records = [];
let privateContext;
async function pageClient(id) {
  for(let i=0;i<100;i++) {
    const target = (await targets()).find(t=>t.id===id && t.type==='page');
    if(target) { const c = await Client.open(target.webSocketDebuggerUrl); clients.push(c); return c; }
    await new Promise(r=>setTimeout(r,50));
  }
  throw Error('Owned target unavailable');
}
async function navigate(client, origin) {
  await client.call('Page.navigate',{url:origin+'/'});
  for(let i=0;i<100;i++) {
    try {if(await client.evaluate(`location.origin===${JSON.stringify(origin)} && document.readyState==='complete' && typeof collectStorageRealms==='function'`))return;} catch {}
    await new Promise(r=>setTimeout(r,100));
  }
  throw Error('Owned page not ready');
}
async function sample(name, client, operation, prefix) {
  const info = (await client.call('Target.getTargetInfo')).targetInfo;
  const contexts = {};
  async function first(origin, key) {
    await navigate(client, origin);
    return client.evaluate(`collectStorageRealms(${JSON.stringify(operation)},${JSON.stringify(prefix+markers[key])})`);
  }
  async function frame(origin, key) {
    const url=origin+'/frame.html?operation='+operation+'&value='+encodeURIComponent(prefix+markers[key]);
    return client.evaluate(`new Promise((resolve,reject)=>{
      const frame=document.createElement('iframe');
      const timer=setTimeout(()=>{removeEventListener('message',receive);frame.remove();reject(Error('Owned frame timeout'))},20000);
      function receive(event){if(event.source!==frame.contentWindow || event.origin!==${JSON.stringify(origin)})return;
        clearTimeout(timer);removeEventListener('message',receive);frame.remove();
        event.data.error?reject(Error(event.data.error)):resolve(event.data.result);}
      addEventListener('message',receive);frame.src=${JSON.stringify(url)};document.body.append(frame);
    })`);
  }
  contexts.firstA=await first(A,'firstA'); contexts.bUnderA=await frame(B,'bUnderA');
  contexts.firstB=await first(B,'firstB'); contexts.aUnderB=await frame(A,'aUnderB');
  records.push({name,operation,prefix,targetId:info.targetId,browserContextId:info.browserContextId,contexts});
  console.log(JSON.stringify({checkpoint:records.at(-1)}));
}
try {
  const original=(await browser.call('Target.getBrowserContexts')).defaultBrowserContextId;
  assert(original);
  const regularTarget=(await targets()).find(t=>t.type==='page');assert(regularTarget);
  const regular=await pageClient(regularTarget.id);
  assert.equal((await regular.call('Target.getTargetInfo')).targetInfo.browserContextId,original);
  async function createPrivate() {
    privateContext=(await browser.call('Target.createBrowserContext',{disposeOnDetach:false})).browserContextId;
    assert(privateContext && privateContext!==original);
    const target=(await browser.call('Target.createTarget',{url:'about:blank',browserContextId:privateContext,newWindow:true})).targetId;
    const page=await pageClient(target);
    assert.equal((await page.call('Target.getTargetInfo')).targetInfo.browserContextId,privateContext);
    return page;
  }
  let privatePage=await createPrivate(); const firstPrivate=privateContext;
  await sample('regular_seed',regular,'write','regular:');
  await sample('private_initial_empty',privatePage,'read','private:');
  await sample('private_seed',privatePage,'write','private:');
  await sample('regular_unchanged',regular,'read','regular:');
  await sample('regular_clear',regular,'delete','regular:');
  await sample('private_survives_regular_clear',privatePage,'read','private:');
  await sample('regular_reseed',regular,'write','regular:');
  await sample('private_clear',privatePage,'delete','private:');
  await sample('regular_survives_private_clear',regular,'read','regular:');
  // Leave a private marker before disposal so a new OTR context must prove
  // destruction instead of merely observing an already-cleared store.
  await sample('private_reseed',privatePage,'write','private:');
  await browser.call('Target.disposeBrowserContext',{browserContextId:privateContext}); privateContext=null;
  const afterDispose=(await browser.call('Target.getTargets')).targetInfos;
  assert(!afterDispose.some(t=>t.browserContextId===firstPrivate));
  privatePage=await createPrivate(); const secondPrivate=privateContext;
  assert.notEqual(secondPrivate,firstPrivate);
  await sample('recreated_private_empty',privatePage,'read','private:');
  await sample('regular_survives_private_disposal',regular,'read','regular:');
  await browser.call('Target.disposeBrowserContext',{browserContextId:privateContext}); privateContext=null;
  console.log(JSON.stringify({completed:true,regularBrowserContextId:original,firstPrivateContextId:firstPrivate,
    secondPrivateContextId:secondPrivate,disposedFirstContextHasNoTargets:true,records,
    scope:'DevTools-created native OTR and regular visible targets share one process; not simultaneous in-flight writes or primary command-line OTR window closure.'}));
} finally {
  if(privateContext)await browser.call('Target.disposeBrowserContext',{browserContextId:privateContext}).catch(()=>{});
  for(const client of clients.reverse())client.close();
}
