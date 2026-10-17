import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const port=18860,origin='http://127.0.0.1:18861';
const collect=spawnSync(process.execPath,[fileURLToPath(new URL('./identity_surface_probe.mjs',import.meta.url)),String(port),origin],{encoding:'utf8',timeout:150000});
assert.equal(collect.status,0,collect.stderr);
const data=JSON.parse(collect.stdout);
const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target=targets.find(t=>t.type==='page');assert(target?.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18860/'));
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let id=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
const call=(method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error(method+' timeout'))},20000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value};
try{
 data.extraRealms={};
 async function mini(){
  const n=navigator,u=n.userAgentData;
  let p=Object.getPrototypeOf(n);while(p&&!Object.getOwnPropertyDescriptor(p,'platform'))p=Object.getPrototypeOf(p);
  return {userAgent:n.userAgent,appVersion:n.appVersion,platform:n.platform,
   hardwareConcurrency:n.hardwareConcurrency,deviceMemory:n.deviceMemory,
   uaData:u?{brands:u.brands,mobile:u.mobile,platform:u.platform,high:await u.getHighEntropyValues(['platformVersion','architecture','bitness','model','uaFullVersion','fullVersionList','wow64','formFactors'])}:null,
   actualGlobal:globalThis.constructor.name,location:location.href,moduleUrl:globalThis.ownedModuleUrl??null,
   platformNative:!!p&&Function.prototype.toString.call(Object.getOwnPropertyDescriptor(p,'platform').get).includes('[native code]')};
 }
 for(const realm of ['module','nested']){
  const child=`onmessage=async()=>{try{postMessage({result:await (${mini.toString()})()})}catch(e){postMessage({error:String(e)})}}`;
  const source=realm==='module'?`globalThis.ownedModuleUrl=import.meta.url;${child}`:
   `onmessage=()=>{const u=URL.createObjectURL(new Blob([${JSON.stringify(child)}],{type:'text/javascript'}));const w=new Worker(u);w.onmessage=e=>{if(e.data.result){e.data.result.nestedParentGlobal=globalThis.constructor.name;e.data.result.nestedParentLocation=location.href}postMessage(e.data);w.terminate();URL.revokeObjectURL(u)};w.onerror=e=>{postMessage({error:e.message});w.terminate();URL.revokeObjectURL(u)};w.postMessage(0)}`;
  data.extraRealms[realm]=await evaluate(`new Promise((ok,no)=>{const u=URL.createObjectURL(new Blob([${JSON.stringify(source)}],{type:'text/javascript'}));const w=new Worker(u,${realm==='module'?"{type:'module'}":"{}"});const t=setTimeout(()=>{w.terminate();URL.revokeObjectURL(u);no(Error('Owned extra realm timeout'))},15000);w.onmessage=e=>{clearTimeout(t);w.terminate();URL.revokeObjectURL(u);e.data.error?no(Error(e.data.error)):ok(e.data.result)};w.onerror=e=>{clearTimeout(t);w.terminate();URL.revokeObjectURL(u);no(Error(e.message))};w.postMessage(0)})`);
 }
 data.cpuTrace=[];
 for(const cores of [8,4,1,8]){
  await call('Emulation.setHardwareConcurrencyOverride',{hardwareConcurrency:cores});
  data.cpuTrace.push({requested:cores,observed:await evaluate(`(async()=>{
   const read=n=>({cores:n.hardwareConcurrency,tier:'cpuPerformance'in n?n.cpuPerformance:null,platform:n.platform,memory:n.deviceMemory});
   const frame=document.createElement('iframe');frame.src='/';document.body.append(frame);
   await new Promise((ok,no)=>{frame.onload=ok;frame.onerror=no});
   const n=frame.contentWindow.navigator;const before=read(n);frame.remove();
   return {window:read(navigator),iframe:before,retained:read(n)};
  })()`) });
 }
 data.nativePersonaGetters=await evaluate(`Object.fromEntries(['platform','hardwareConcurrency','deviceMemory'].map(name=>{let p=Navigator.prototype;while(p&&!Object.getOwnPropertyDescriptor(p,name))p=Object.getPrototypeOf(p);const get=p&&Object.getOwnPropertyDescriptor(p,name).get;return[name,typeof get==='function'&&Function.prototype.toString.call(get).includes('[native code]')]}))`);
 // Protected pages deliberately lack WEBGL_debug_renderer_info. Verify the
 // real backend through the owned browser process, not a fabricated JS value.
 const version=await(await fetch(`http://127.0.0.1:${port}/json/version`)).json();
 assert(version.webSocketDebuggerUrl.startsWith(`ws://127.0.0.1:${port}/devtools/browser/`));
 const browser=new WebSocket(version.webSocketDebuggerUrl);
 try {
  await new Promise((ok,no)=>{browser.onopen=ok;browser.onerror=no});
  data.nativeGpuInfo=await new Promise((ok,no)=>{
   const timer=setTimeout(()=>no(Error('Owned SystemInfo timeout')),15000);
   browser.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==1)return;clearTimeout(timer);m.error?no(Error(m.error.message)):ok(m.result.gpu)};
   browser.send(JSON.stringify({id:1,method:'SystemInfo.getInfo'}));
  });
 } finally {browser.close()}
 console.log(JSON.stringify(data));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned persona probe closed'))}}
