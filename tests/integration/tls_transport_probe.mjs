import assert from 'node:assert/strict';
assert.equal(process.argv[2], '18911');
const origin='https://transport.metabrowser.test:18912';
const targets=await(await fetch('http://127.0.0.1:18911/json/list')).json();
const target=targets.find(t=>t.type==='page'&&t.url==='about:blank');
assert(target?.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18911/'));
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let id=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
const call=(method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error(method+' timeout'))},15000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
try{
 const navigation=await call('Page.navigate',{url:origin+'/owned-transport'});
 assert(!navigation.errorText,JSON.stringify(navigation));
 let observation;
 for(let i=0;i<100;i++){
  const result=await call('Runtime.evaluate',{expression:`({url:location.href,title:document.title,ready:document.readyState,body:document.body?.innerText})`,returnByValue:true});
  observation=result.result.value;
  if(observation?.url===origin+'/owned-transport'&&observation.title==='Owned transport'&&observation.body.includes('Owned transport ready'))break;
  await new Promise(r=>setTimeout(r,100));
 }
 assert.equal(observation?.title,'Owned transport');
 assert.equal(observation.url,origin+'/owned-transport');
 assert(observation.body.includes('Owned transport ready'));
 console.log(JSON.stringify({completed:true,observation,paid_model_calls:0}));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned probe closed'))}}
