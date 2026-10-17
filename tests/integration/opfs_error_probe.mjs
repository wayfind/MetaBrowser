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

async function trial(realm,kind,scenario){
 const digest=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');
 const name=`owned-opfs-${realm}-${kind}-${scenario}`;
 const bucket=await navigator.storageBuckets.open(name,{quota:scenario==='delete_inflight'?16*1024**2:2*1024**2});
 const directory=await bucket.getDirectory();
 const file=await directory.getFileHandle('canary.bin',{create:true});
 const initial=await file.createWritable();await initial.write(new Uint8Array(4096).fill(7));await initial.close();
 const writer=await file.createWritable();
 let result={realm,kind,scenario,origin:location.origin};
 const payload=kind==='blob'?new Blob([new Uint8Array(8*1024**2).fill(42)]):kind==='string'?'x'.repeat(8*1024**2):new Uint8Array(8*1024**2).fill(42);
 try{
  if(scenario==='cancel'){
   await writer.write(new Uint8Array(4096).fill(42));await writer.abort('owned-cancel');
   result.cancelled=true;
  }else{
   let stage='write';
   const write=async()=>{try{await writer.write(payload);stage='close';await writer.close();return{completed:true};}catch(e){return{completed:false,error:e.name,message:e.message,stage}}};
   const work=write();
   if(scenario==='delete_inflight')await navigator.storageBuckets.delete(name);
   let timer;
   try{result.write=await Promise.race([work,new Promise((ok,no)=>{timer=setTimeout(()=>no(Error('Owned write did not settle')),10000)})]);}
   finally{clearTimeout(timer);}
   if(!result.write.completed)await writer.abort().catch(()=>{});
  }
  if(scenario!=='delete_inflight'){
   const data=await(await file.getFile()).arrayBuffer();
   result.retained={bytes:data.byteLength,sha256:await digest(data)};
  }
  await navigator.storageBuckets.delete(name);
  const recovered=await navigator.storageBuckets.open(name+'-recovered',{quota:2*1024**2});
  try{
   const dir=await recovered.getDirectory(),handle=await dir.getFileHandle('recovered.bin',{create:true});
   const stream=await handle.createWritable();await stream.write(new Uint8Array(4096).fill(21));await stream.close();
   const data=await(await handle.getFile()).arrayBuffer();result.recovered={bytes:data.byteLength,sha256:await digest(data)};
  }finally{await navigator.storageBuckets.delete(name+'-recovered');}
  result.completed=true;return result;
 }finally{await navigator.storageBuckets.delete(name).catch(()=>{});}
}

try{
 const nav=await call('Page.navigate',{url:origin+'/'});assert(!nav.errorText);
 let ready=false;
 for(let i=0;i<100;i++){try{ready=await evaluate(`location.origin===${JSON.stringify(origin)}&&document.readyState==='complete'`)}catch{}if(ready)break;await new Promise(r=>setTimeout(r,100));}
 assert(ready);const rows=[];
 for(const realm of ['window','dedicated']){
  for(const [kind,scenario] of [['array','quota'],['blob','quota'],['string','quota'],['array','cancel'],['array','delete_inflight']]){
   const expression=realm==='window'?`(${trial.toString()})(${JSON.stringify(realm)},${JSON.stringify(kind)},${JSON.stringify(scenario)})`:
    `new Promise((resolve,reject)=>{const url=URL.createObjectURL(new Blob([${JSON.stringify(`onmessage=async()=>{try{postMessage({result:await (${trial.toString()})(${JSON.stringify(realm)},${JSON.stringify(kind)},${JSON.stringify(scenario)})})}catch(e){postMessage({error:String(e)})}}`)}],{type:'text/javascript'}));const w=new Worker(url);const t=setTimeout(()=>{w.terminate();URL.revokeObjectURL(url);reject(Error('Owned worker did not settle'))},20000);w.onmessage=e=>{clearTimeout(t);w.terminate();URL.revokeObjectURL(url);e.data.error?reject(Error(e.data.error)):resolve(e.data.result)};w.onerror=e=>{clearTimeout(t);w.terminate();URL.revokeObjectURL(url);reject(Error(e.message))};w.postMessage({})})`;
   rows.push(await evaluate(expression));
  }
 }
 console.log(JSON.stringify({completed:true,rows,paid_model_calls:0}));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned probe closed'))}}
