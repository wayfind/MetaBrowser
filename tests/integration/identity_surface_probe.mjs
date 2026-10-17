import assert from 'node:assert/strict';
const port=Number(process.argv[2]),origin=process.argv[3];assert(port===18860);assert(origin==='http://127.0.0.1:18861');
const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();const page=targets.find(t=>t.type==='page');assert(page);
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});let id=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)};
const call=(method,params={})=>new Promise((resolve,reject)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);reject(Error(method+' timeout'))},60000);pending.set(seq,{resolve,reject,timer});ws.send(JSON.stringify({id:seq,method,params}))});
try {
 await call('Page.navigate',{url:origin+'/'});
 const result=await call('Runtime.evaluate',{expression:`(async()=>{
  const end=Date.now()+15000;while(typeof collectIdentitySurface!=='function'){if(Date.now()>end)throw Error('collector not ready');await new Promise(r=>setTimeout(r,100))}
  const realms={window:await collectIdentitySurface()},errors={};
  async function collect(name,fn){try{realms[name]=await Promise.race([fn(),new Promise((_,no)=>setTimeout(()=>no(Error('realm timeout')),12000))])}catch(e){errors[name]=String(e)}}
  await collect('iframe',()=>new Promise((ok,no)=>{const frame=document.createElement('iframe');function receive(e){if(e.source!==frame.contentWindow||e.origin!==location.origin)return;removeEventListener('message',receive);frame.remove();e.data.error?no(Error(e.data.error)):ok(e.data.result)}addEventListener('message',receive);frame.src='/frame.html';document.body.append(frame)}));
  await collect('dedicated',()=>new Promise((ok,no)=>{const w=new Worker('/dedicated.js');w.onmessage=e=>{w.terminate();e.data.error?no(Error(e.data.error)):ok(e.data.result)};w.onerror=e=>{w.terminate();no(Error(e.message))};w.postMessage(0)}));
  await collect('shared',()=>new Promise((ok,no)=>{const w=new SharedWorker('/shared.js');w.port.onmessage=e=>{w.port.close();e.data.error?no(Error(e.data.error)):ok(e.data.result)};w.onerror=e=>no(Error(e.message));w.port.start();w.port.postMessage(0)}));
  await collect('service',async()=>{const reg=await navigator.serviceWorker.register('/service.js');try{await navigator.serviceWorker.ready;const w=reg.active;if(!w)throw Error('no active service worker');return await new Promise((ok,no)=>{const c=new MessageChannel();c.port1.onmessage=e=>{c.port1.close();e.data.error?no(Error(e.data.error)):ok(e.data.result)};w.postMessage(0,[c.port2])})}finally{await reg.unregister()}});
  const headers=await(await fetch('/echo')).json();return {realms,errors,headers};
 })()`,awaitPromise:true,returnByValue:true});
 assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));assert(result.result?.value);
 const data=result.result.value;
 async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value}
 await evaluate(`(async()=>{
  globalThis.__networkPrivacyEvents=0;globalThis.__batteryPrivacyEvents=0;
  globalThis.__batteryObject=await navigator.getBattery?.();if(__batteryObject)for(const name of ['chargingchange','chargingtimechange','dischargingtimechange','levelchange'])__batteryObject.addEventListener(name,()=>__batteryPrivacyEvents++);
  globalThis.__batteryPromiseIdentity=__batteryObject===(await navigator.getBattery?.());
  globalThis.__signalWorker=new Worker('/dedicated.js');
  await new Promise((ok,no)=>{__signalWorker.onmessage=ok;__signalWorker.onerror=e=>no(Error(e.message));__signalWorker.postMessage(0)});
  navigator.connection?.addEventListener('change',()=>__networkPrivacyEvents++);
  const frame=document.createElement('iframe');frame.src='/frame.html';document.body.append(frame);
  await new Promise((ok,no)=>{frame.onload=ok;frame.onerror=no});
  globalThis.__heldNetwork=frame.contentWindow.navigator.connection;
  globalThis.__heldBattery=await frame.contentWindow.navigator.getBattery?.();frame.remove();return true;
 })()`);
 const sample=`(async()=>{
  const read=n=>n?{effectiveType:n.effectiveType,rtt:n.rtt,downlink:n.downlink,saveData:n.saveData}:null;
  const battery=b=>b?{charging:b.charging,level:b.level,chargingTime:Number.isFinite(b.chargingTime)?b.chargingTime:'Infinity',dischargingTime:Number.isFinite(b.dischargingTime)?b.dischargingTime:'Infinity'}:null;
  const w=__signalWorker;const worker=await new Promise((ok,no)=>{w.onmessage=e=>{e.data.error?no(Error(e.data.error)):ok(e.data.result.connection)};w.onerror=e=>no(Error(e.message));w.postMessage(0)});
  return {window:read(navigator.connection),worker,retained:read(__heldNetwork),battery:battery(await navigator.getBattery?.()),retainedBattery:battery(__heldBattery),events:__networkPrivacyEvents,batteryEvents:__batteryPrivacyEvents,batteryPromiseIdentity:__batteryPromiseIdentity,online:navigator.onLine};
 })()`;
 const networkTrace=[{phase:'before',observed:await evaluate(sample)}];
 for(const [phase,state] of [['slow',{offline:false,latency:750,downloadThroughput:125000,uploadThroughput:62500,connectionType:'cellular2g'}],['fast',{offline:false,latency:20,downloadThroughput:12500000,uploadThroughput:12500000,connectionType:'wifi'}],['offline',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0,connectionType:'none'}]]){
  await call('Network.emulateNetworkConditions',state);await new Promise(r=>setTimeout(r,400));networkTrace.push({phase,observed:await evaluate(sample)});
 }
 await call('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 await evaluate('__signalWorker.terminate();true');data.passiveSignalTrace=networkTrace;console.log(JSON.stringify(data));
} finally {ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('closed'))}}
