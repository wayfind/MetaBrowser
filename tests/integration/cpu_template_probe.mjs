import assert from 'node:assert/strict';
const port = Number(process.argv[2]); assert.equal(port, 18879);
const page = (await (await fetch('http://127.0.0.1:18879/json/list')).json()).find(t => t.type === 'page');
assert(page && page.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18879/'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
let id = 0; const pending = new Map();
ws.onmessage = event => {
  const r = JSON.parse(event.data), p = pending.get(r.id); if (!p) return;
  clearTimeout(p.timer); pending.delete(r.id);
  r.error ? p.reject(Error(r.error.message)) : p.resolve(r.result);
};
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const seq = ++id, timer = setTimeout(() => { pending.delete(seq); reject(Error(method + ' timeout')); }, 15000);
  pending.set(seq, {resolve, reject, timer}); ws.send(JSON.stringify({id: seq, method, params}));
});
async function evaluate(expression) {
  const r = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  assert(!r.exceptionDetails, JSON.stringify(r.exceptionDetails)); return r.result.value;
}
try {
  await call('Page.navigate', {url: 'http://127.0.0.1:18880/'});
  for (let i = 0; i < 100; i++) {
    try { if (await evaluate("location.origin==='http://127.0.0.1:18880' && document.readyState==='complete'")) break; } catch {}
    await new Promise(r => setTimeout(r, 100));
    assert(i < 99, 'Owned CPU page not ready');
  }
  await evaluate(`new Promise((ok,no)=>{globalThis.__cpuFrame=document.createElement('iframe');__cpuFrame.onload=ok;__cpuFrame.onerror=no;__cpuFrame.src='/frame';document.body.append(__cpuFrame)})`);
  const identity = await evaluate("navigator.userAgentData.getHighEntropyValues(['architecture','bitness','platformVersion'])");
  const samples = [];
  for (const cores of [8, 4, 1, 8]) {
    // Native inspector control of the public core count; no JS getter patches.
    await call('Emulation.setHardwareConcurrencyOverride', {hardwareConcurrency: cores});
    const observed = await evaluate(`(()=>{const read=n=>({cores:n.hardwareConcurrency,tier:n.cpuPerformance,present:'cpuPerformance' in n});return {window:read(navigator),iframe:read(__cpuFrame.contentWindow.navigator)}})()`);
    assert.equal(observed.window.cores, cores);
    samples.push({requestedCores: cores, observed});
  }
  const retained = await evaluate(`(()=>{const n=__cpuFrame.contentWindow.navigator;const read=()=>({cores:n.hardwareConcurrency,tier:n.cpuPerformance});const before=read();__cpuFrame.remove();return {before,after:read()}})()`);
  console.log(JSON.stringify({identity, samples, retained}));
} finally { ws.close(); for (const p of pending.values()) clearTimeout(p.timer); }
