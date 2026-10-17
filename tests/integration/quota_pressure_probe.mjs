import assert from 'node:assert/strict';
const port=Number(process.argv[2]);assert.equal(port,18877);
let origin='http://127.0.0.1:18878';
const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page=targets.find(t=>t.type==='page');assert(page?.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18877/'));
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no;});
let id=0;const pending=new Map();
ws.onmessage=event=>{const m=JSON.parse(event.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);};
const call=(method,params={})=>new Promise((resolve,reject)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);reject(Error(method+' timed out'));},30000);pending.set(seq,{resolve,reject,timer});ws.send(JSON.stringify({id:seq,method,params}));});
async function evaluate(expression){const result=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;}
const samples=[];
try{
  async function navigate() {
  await call('Page.navigate',{url:origin+'/'});
  let ready=false;
  for(let i=0;i<100;i++){try{ready=await evaluate(`location.origin===${JSON.stringify(origin)} && document.readyState==='complete' && typeof ownedQuotaTrial==='function'`);}catch{}if(ready)break;await new Promise(r=>setTimeout(r,100));}
  assert(ready);
  }
  await navigate();
  const trial=async(name,bucket,bytes,pressure)=>{
    const backend=await call('Storage.getUsageAndQuota',{origin});
    const realms={};
    for(const realm of ['window','dedicated']){
      const config={realm,bucket,bytes};
      realms[realm]=await evaluate(realm==='window'?`ownedQuotaTrial(${JSON.stringify(config)})`:
        `new Promise((resolve,reject)=>{const worker=new Worker('/quota-worker.js');const timer=setTimeout(()=>{worker.terminate();reject(Error('Owned quota worker timeout'));},20000);worker.onmessage=e=>{clearTimeout(timer);worker.terminate();e.data.error?reject(Error(e.data.error)):resolve(e.data.result)};worker.onerror=e=>{clearTimeout(timer);worker.terminate();reject(Error(e.message))};worker.postMessage(${JSON.stringify(config)});})`);
    }
    samples.push({name,origin,bucket,bytes,pressure,backend,realms});console.log(JSON.stringify({checkpoint:samples.at(-1)}));
  };
  await trial('normal_small',false,4096,false);
  await trial('normal_large',false,8*1024*1024,false);
  // Fresh origin: do not reuse IndexedDB quota grants cached before an override.
  origin='http://localhost:18878';
  await call('Storage.overrideQuotaForOrigin',{origin,quotaSize:2*1024*1024});
  await navigate();
  await trial('override_pressure',false,8*1024*1024,true);
  await call('Storage.overrideQuotaForOrigin',{origin});
  await trial('override_reset',false,8*1024*1024,false);
  origin='http://127.0.0.1:18878';await navigate();
  await trial('explicit_bucket_small',true,4096,false);
  await trial('explicit_bucket_pressure',true,8*1024*1024,true);
  await evaluate(`navigator.storageBuckets.delete('owned-pressure')`);
  console.log(JSON.stringify({completed:true,samples,scope:'Controlled2MiB fresh-origin DevTools quota and explicit2MiB bucket; bounded8MiB writes. Not physical disk exhaustion or less-than10GiB volume reporting.'}));
}finally{
  await call('Storage.overrideQuotaForOrigin',{origin}).catch(()=>{});
  ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Owned connection closed'));}
}
