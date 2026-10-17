// Browser-level diagnostic readback, only for the isolated compatibility port.
import assert from 'node:assert/strict';
const port=Number(process.argv[2]);assert.equal(port,18903);
const version=await(await fetch(`http://127.0.0.1:${port}/json/version`)).json();
assert(version.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18903/'));
const ws=new WebSocket(version.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let id=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
const call=(method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error('Owned cookie diagnostic timeout'))},10000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
try{
  const targets=(await call('Target.getTargets')).targetInfos.filter(x=>x.type==='page');
  const contexts=[...new Set(targets.map(x=>x.browserContextId).filter(Boolean))];
  const results=[];
  for(const context of [null,...contexts]){
    const data=await call('Storage.getCookies',context?{browserContextId:context}:{});
    results.push({context,cookieCount:data.cookies.length,canaries:data.cookies.filter(c=>c.name==='SAPISID'&&c.value==='metabrowser-owned-cookie-canary')});
  }
  console.log(JSON.stringify({targets:targets.map(x=>({id:x.targetId,url:x.url,context:x.browserContextId})),contexts:results}));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned diagnostic closed'))}}
