import assert from 'node:assert/strict';
import {createECDH} from 'node:crypto';
const port=Number(process.argv[2]),permission=process.argv[3];
const persisted=process.argv[4]==='persisted',keep=process.argv[5]==='keep',restore=process.argv[6]==='restore';
assert.equal(port,18905);assert(['denied','granted'].includes(permission));
const origin='http://127.0.0.1:18906';
const version=await(await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page=targets.find(x=>x.type==='page');assert(page);
const sockets=[];
async function connect(url){
 assert(url.startsWith('ws://127.0.0.1:18905/'));
 const ws=new WebSocket(url);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});sockets.push(ws);
 let id=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
 return (method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error(method+' timeout'))},105000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
}
try{
 const browser=await connect(version.webSocketDebuggerUrl),call=await connect(page.webSocketDebuggerUrl);
 if(!persisted)await browser('Browser.setPermission',{permission:{name:'notifications'},setting:permission,origin});
 await call('Page.navigate',{url:origin+'/'});
 async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value}
 for(let i=0;i<100;i++){
  if(await evaluate(`location.origin===${JSON.stringify(origin)}&&document.readyState==='complete'`))break;
  if(i===99)throw Error('Owned push page not ready');await new Promise(r=>setTimeout(r,100));
 }
 const key=Array.from(createECDH('prime256v1').generateKeys());
 const wallStarted=performance.now();
 const result=await evaluate(`(async()=>{
  const registration=await navigator.serviceWorker.register('/sw.js');await navigator.serviceWorker.ready;
  const existing=await registration.pushManager.getSubscription();
  const options={userVisibleOnly:true,applicationServerKey:existing?.options.applicationServerKey||new Uint8Array(${JSON.stringify(key)})};
  const before={notification:Notification.permission,query:(await navigator.permissions.query({name:'notifications'})).state,push:await registration.pushManager.permissionState(options)};
  async function describe(s){const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');return {kind:'subscription',endpoint:s.endpoint,hasP256DH:!!s.getKey('p256dh'),hasAuth:!!s.getKey('auth'),p256dh_sha256:await hash(s.getKey('p256dh')),auth_sha256:await hash(s.getKey('auth'))}}
  const outcome=await Promise.race([
   ${restore?'existing?describe(existing):Promise.resolve({kind:"missing_saved_subscription"})':'registration.pushManager.subscribe(options).then(describe,e=>({kind:"error",name:e.name,message:e.message}))'},
   new Promise(resolve=>setTimeout(()=>resolve({kind:'pending_after_90s'}),90000))
  ]);
  let unsubscribe=null;
  if(outcome.kind==='subscription'&&!${keep}){const subscription=await registration.pushManager.getSubscription();unsubscribe=subscription?await subscription.unsubscribe():false}
  return {origin:location.origin,secure:isSecureContext,before,outcome,was_existing:!!existing,unsubscribe,remainingSubscription:!!(await registration.pushManager.getSubscription()),notificationsSent:0};
 })()`);
 console.log(JSON.stringify({completed:true,permission,result,wall_elapsed_ms:performance.now()-wallStarted,permission_control:persisted?'owned persisted native notification setting, not an OS consent prompt':'native Browser.setPermission override, not an OS consent prompt',messages_sent:0}));
 await browser('Browser.resetPermissions');
}finally{for(const ws of sockets)ws.close()}
