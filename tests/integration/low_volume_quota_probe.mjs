import assert from 'node:assert/strict';
const port = Number(process.argv[2]), phase = process.argv[3];
assert.equal(port, 18877);
assert(['write', 'read', 'delete'].includes(phase));
const A = 'http://127.0.0.1:18878', B = 'http://localhost:18878';
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find(t => t.type === 'page'); assert(page);
assert(page.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18877/'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
let id = 0; const pending = new Map();
ws.onmessage = event => {
  const m = JSON.parse(event.data), p = pending.get(m.id);
  if (!p) return;
  pending.delete(m.id); clearTimeout(p.timer);
  m.error ? p.reject(Error(m.error.message)) : p.resolve(m.result);
};
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const seq = ++id, timer = setTimeout(() => { pending.delete(seq); reject(Error(method + ' timeout')); }, 20000);
  pending.set(seq, {resolve, reject, timer}); ws.send(JSON.stringify({id: seq, method, params}));
});
async function evaluate(expression) {
  const r = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  assert(!r.exceptionDetails, JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function navigate(origin) {
  await call('Page.navigate', {url: origin + '/'});
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    try {
      if (await evaluate(`location.origin === ${JSON.stringify(origin)} && document.readyState === 'complete' && typeof collectStorageRealms === 'function'`)) return;
    } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  throw Error('Owned storage page not ready');
}
async function firstParty(origin, marker) {
  await navigate(origin);
  return evaluate(`collectStorageRealms(${JSON.stringify(phase)}, ${JSON.stringify(marker)}).then(async result=>{result.extra=await ownedLowVolumeSignals();return result;})`);
}
async function framed(origin, marker) {
  const url = origin + '/frame.html?operation=' + phase + '&value=' + encodeURIComponent(marker);
  return evaluate(`new Promise((resolve,reject)=>{
    const frame=document.createElement('iframe');
    const timer=setTimeout(()=>{removeEventListener('message',receive);frame.remove();reject(Error('Owned frame timeout'))},15000);
    function receive(event){
      if(event.source!==frame.contentWindow || event.origin!==${JSON.stringify(origin)})return;
      clearTimeout(timer);removeEventListener('message',receive);frame.remove();
      event.data.error?reject(Error(event.data.error)):resolve(event.data.result);
    }
    addEventListener('message',receive);frame.src=${JSON.stringify(url)};document.body.append(frame);
  })`);
}
try {
  const contexts = {};
  contexts.firstA = await firstParty(A, 'first-a');
  contexts.bUnderA = await framed(B, 'b-under-a');
  contexts.firstB = await firstParty(B, 'first-b');
  contexts.aUnderB = await framed(A, 'a-under-b');
  console.log(JSON.stringify({phase, contexts}));
} finally {
  ws.close();
  for (const p of pending.values()) { clearTimeout(p.timer); p.reject(Error('Owned connection closed')); }
}
