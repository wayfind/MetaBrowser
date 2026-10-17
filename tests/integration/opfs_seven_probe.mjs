import assert from 'node:assert/strict';
assert.equal(process.argv[2],'18877');
const origin='http://127.0.0.1:18878';
const targets=await(await fetch('http://127.0.0.1:18877/json/list')).json();
const target=targets.find(t=>t.type==='page');
assert(target?.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18877/'));
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let id=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
const call=(method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error(method+' timeout'))},60000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value;}

async function invoke(realm,kind,scenario){
 if(realm==='window')return ownedOpfsTrial(realm,kind,scenario);
 const message={realm,kind,scenario};
 let dispose=async()=>{},timer;
 try{return await Promise.race([new Promise(async(resolve,reject)=>{
  try{
   const receive=e=>e.data.error?reject(Error(e.data.error)):resolve(e.data.result);
   if(realm==='iframe'){
    const frame=document.createElement('iframe');
    const listener=e=>{if(e.source===frame.contentWindow&&e.origin===location.origin)receive(e)};
    addEventListener('message',listener);dispose=async()=>{removeEventListener('message',listener);frame.remove()};
    frame.src='/opfs-frame.html?'+new URLSearchParams(message);document.body.append(frame);
   }else if(realm==='service'){
    const reg=await navigator.serviceWorker.register('/opfs-service.js',{scope:'/owned-opfs/'});
    dispose=()=>reg.unregister();const worker=reg.active??reg.installing??reg.waiting;
    if(!worker)throw Error('No actual service worker');
    if(worker.state!=='activated')await new Promise((ok,no)=>{worker.addEventListener('statechange',()=>{if(worker.state==='activated')ok();if(worker.state==='redundant')no(Error('Service worker redundant'))})});
    const channel=new MessageChannel();dispose=async()=>{channel.port1.close();await reg.unregister()};
    channel.port1.onmessage=receive;worker.postMessage(message,[channel.port2]);
   }else if(realm==='shared'){
    const worker=new SharedWorker('/opfs-shared.js','owned-opfs-seven');dispose=async()=>worker.port.close();
    worker.port.onmessage=receive;worker.onerror=e=>reject(Error(e.message));worker.port.start();worker.port.postMessage(message);
   }else{
    const path=realm==='module'?'/opfs-module.js':realm==='nested'?'/opfs-nested.js':'/opfs-worker.js';
    const worker=new Worker(path,realm==='module'?{type:'module'}:{});dispose=async()=>worker.terminate();
    worker.onmessage=receive;worker.onerror=e=>reject(Error(e.message));worker.postMessage(message);
   }
  }catch(error){reject(error)}
 }),new Promise((ok,no)=>{timer=setTimeout(()=>no(Error('Owned realm did not settle: '+realm)),25000)})]);
 }finally{clearTimeout(timer);await dispose()}
}

try{
 const nav=await call('Page.navigate',{url:origin+'/'});assert(!nav.errorText);
 let ready=false;
 for(let i=0;i<100;i++){try{ready=await evaluate(`location.origin===${JSON.stringify(origin)}&&document.readyState==='complete'&&typeof ownedOpfsTrial==='function'`)}catch{}if(ready)break;await new Promise(r=>setTimeout(r,100));}
 assert(ready);const rows=[];
 const cases=[...['uint8','arraybuffer','offset_uint8','dataview','blob','string'].map(k=>[k,'quota']),['uint8','cancel'],['uint8','delete_inflight']];
 for(const realm of ['window','iframe','dedicated','module','nested','shared','service']){
  for(const [kind,scenario] of cases)rows.push(await evaluate(`(${invoke.toString()})(${JSON.stringify(realm)},${JSON.stringify(kind)},${JSON.stringify(scenario)})`));
 }
 console.log(JSON.stringify({completed:true,rows,paid_model_calls:0}));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned probe closed'))}}
