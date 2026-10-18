// QA only: attach to a caller-owned, isolated browser's explicit CDP port.
// No external site, real profile, provider or persisted account is used.
import assert from 'node:assert/strict';
const port=Number(process.argv[2]);
assert(Number.isInteger(port)&&port>=18840&&port<=18860);
const origin=process.argv[3];assert(/^http:\/\/127\.0\.0\.1:188\d{2}$/.test(origin));
const version=await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
assert(version.webSocketDebuggerUrl.startsWith(`ws://127.0.0.1:${port}/`));
const ws=new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true})});
let next=0;const pending=new Map();
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(!m.id)return;const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)});
function call(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++next;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP fixture timeout: '+method))},15000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}))})}
let session;
async function evaluate(expression,userGesture=false){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture},session);if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value}
async function wait(check,label){const end=Date.now()+10000;while(Date.now()<end){const value=await check();if(value)return value;await new Promise(r=>setTimeout(r,100))}throw Error(label)}
const snapshot=`(()=>({width:screen.width,height:screen.height,depth:screen.colorDepth,x:screenX,y:screenY,outerWidth,outerHeight,orientation:screen.orientation.type,angle:screen.orientation.angle,cssWidth:matchMedia('(device-width:'+screen.width+'px)').matches,cssHeight:matchMedia('(device-height:'+screen.height+'px)').matches,color8:matchMedia('(color:8)').matches,p3:matchMedia('(color-gamut:p3)').matches,hdr:matchMedia('(dynamic-range:high)').matches,watched:window.__media?.matches,events:window.__events||[]}))()`;
try{
 const {targetInfos}=await call('Target.getTargets');const target=targetInfos.find(t=>t.type==='page');assert(target);
 ({sessionId:session}=await call('Target.attachToTarget',{targetId:target.targetId,flatten:true}));
 await call('Page.enable',{},session);
 const {windowId}=await call('Browser.getWindowForTarget',{targetId:target.targetId});
 await call('Browser.setWindowBounds',{windowId,bounds:{left:120,top:96,width:1100,height:700,windowState:'normal'}});
 await call('Page.navigate',{url:origin+'/display-only'},session);
 await wait(()=>evaluate(`document.readyState==='complete'&&location.href==='${origin}/display-only'&&outerWidth>0&&outerHeight>0`),'native window ready');
 const initial=await evaluate(snapshot);assert.equal(initial.depth,24);assert.equal(initial.x,0);assert.equal(initial.y,24);assert.equal(initial.orientation,'landscape-primary');assert.equal(initial.angle,0);assert(initial.cssWidth&&initial.cssHeight&&initial.color8);assert(!initial.p3&&!initial.hdr);
 await evaluate(`window.__events=[];window.__media=matchMedia('(device-height:'+screen.height+'px)');__media.onchange=e=>__events.push(e.matches);true`);
 await call('Browser.grantPermissions',{origin,permissions:['windowManagement']});
 const detailMatches=await evaluate(`getScreenDetails().then(d=>{window.__details=d;window.__retained=Array.from(d.screens);return d.currentScreen.width===screen.width&&d.currentScreen.height===screen.height})`);assert(detailMatches,'Detailed and basic screen mismatch after native grant');
 const granted=await wait(async()=>{const x=await evaluate(snapshot);return x.x!==0&&x.y!==24&&x.cssWidth&&x.cssHeight?x:null},'native permission grant not reflected');
 assert.notDeepEqual([granted.width,granted.height,granted.x,granted.y],[initial.width,initial.height,initial.x,initial.y]);
 if(granted.height!==initial.height)await wait(()=>evaluate('__media.matches===false&&__events.includes(false)'),'CSS query did not update after grant');
 await call('Browser.resetPermissions');
 const revoked=await wait(async()=>{const x=await evaluate(snapshot);return x.x===0&&x.y===24&&x.orientation==='landscape-primary'&&x.cssWidth&&x.cssHeight&&x.watched?x:null},'permission revocation did not restore virtual display');
 assert.equal(revoked.width,initial.width);assert.equal(revoked.height,initial.height);
 try {
 await wait(()=>evaluate(`__details.screens.length===0&&__details.currentScreen===null&&__retained.length>0&&__retained.every(s=>s.label===''&&!s.isInternal&&s.isPrimary&&!s.isExtended&&s.width===screen.width&&s.height===screen.height&&s.left===0&&s.top===0&&s.colorDepth===24&&s.redPrimaryX===Math.fround(.64)&&s.greenPrimaryY===Math.fround(.60)&&s.highDynamicRangeHeadroom===1)`),'Retained display objects still expose physical metadata after revoke');
 } catch(error) {
  console.error(JSON.stringify(await evaluate(`({empty:__details.screens.length===0,currentNull:__details.currentScreen===null,retained:__retained.map(s=>({labelEmpty:s.label==='',internalHidden:!s.isInternal,primary:s.isPrimary,extendedHidden:!s.isExtended,width:s.width===screen.width,height:s.height===screen.height,left:s.left===0,top:s.top===0,depth:s.colorDepth===24,red:s.redPrimaryX===Math.fround(.64),green:s.greenPrimaryY===Math.fround(.60),hdr:s.highDynamicRangeHeadroom===1,hdrPresent:'redPrimaryX' in s}))})`)));
  throw error;
 }

 await call('Browser.grantPermissions',{origin,permissions:['windowManagement']});
 await wait(()=>evaluate(`__details.screens.length>0&&__details.currentScreen&&__details.currentScreen.width===screen.width&&__details.currentScreen.height===screen.height`),'Observer-only regrant did not refresh retained details');
 assert(await evaluate(`getScreenDetails().then(d=>d===__details)`),'Regrant replaced the retained details object');
 await call('Browser.resetPermissions');
 await wait(()=>evaluate(`__details.screens.length===0&&__details.currentScreen===null&&screenX===0&&screenY===24`),'Second revocation failed');
 if(granted.height!==initial.height)await wait(()=>evaluate('__events.includes(true)'),'CSS query did not update after revocation');
 await call('Browser.setWindowBounds',{windowId,bounds:{left:240,top:180,width:1300,height:800}});
 const moved=await wait(async()=>{const x=await evaluate(snapshot);return x.outerWidth>=1250?x:null},'native resize');
 assert.equal(moved.x,0);assert.equal(moved.y,24);assert(moved.width>=moved.outerWidth&&moved.height-24>=moved.outerHeight);assert(moved.cssWidth&&moved.cssHeight);
 await evaluate(`window.__screenChanges=[];window.__bucketEvents=[];window.__bucketMedia=matchMedia('(device-width:1440px)');__bucketMedia.onchange=e=>__bucketEvents.push(e.matches);screen.onchange=()=>__screenChanges.push({width:screen.width,height:screen.height});true`);
 await evaluate(`new Promise(resolve=>{const f=document.createElement('iframe');f.style.width='100px';f.style.height='100px';window.__childScreenChanges=[];window.addEventListener('message',e=>{if(e.source!==f.contentWindow)return;if(e.data?.ready)resolve();else if(e.data?.screen) __childScreenChanges.push(e.data.screen)});f.srcdoc='<script>screen.onchange=()=>parent.postMessage({screen:{width:screen.width,height:screen.height}},"*");parent.postMessage({ready:true},"*");<'+ '/script>';document.body.append(f)})`);
 await call('Browser.setWindowBounds',{windowId,bounds:{left:120,top:80,width:1300,height:800}});
 await new Promise(r=>setTimeout(r,300));
 assert(await evaluate(`__screenChanges.length===0`),'Hidden physical movement emitted a protected screen event');
 await call('Browser.setWindowBounds',{windowId,bounds:{left:0,top:40,width:1500,height:850}});
 await wait(()=>evaluate(`outerWidth>=1450&&screen.width>=outerWidth&&screen.width>1440&&__screenChanges.some(e=>e.width===screen.width&&e.height===screen.height)&&__childScreenChanges.some(e=>e.width===screen.width)&&__bucketEvents.includes(false)`),'Virtual display growth missing matching screen/CSS/iframe events');
 await call('Browser.setWindowBounds',{windowId,bounds:{left:100,top:80,width:1100,height:700}});
 await wait(()=>evaluate(`screen.width===1440&&__screenChanges.some(e=>e.width===1440)&&__childScreenChanges.some(e=>e.width===1440)&&__bucketEvents.includes(true)`),'Virtual display shrink missing matching screen/CSS/iframe events');
 const voiceCount=await evaluate(`(async()=>{for(let i=0;i<100;i++){window.__voices=speechSynthesis.getVoices();if(__voices.length)return __voices.length;await new Promise(r=>setTimeout(r,50))}return 0})()`);
 let speech='native-voices-unavailable';
 if(voiceCount){
  // v20n: stock voices keep real names/URIs like official Chrome; downloaded
  // quality variants stay hidden and no generic alias or private accessor leaks.
  assert(await evaluate(`__voices.every(v=>v.name&&!/\\((Enhanced|Premium)\\)/.test(v.name)&&!v.name.startsWith('System voice (')&&!v.voiceURI.startsWith('urn:metabrowser:voice:')&&typeof v.NativeName==='undefined')`));
  const spoken=await evaluate(`new Promise(resolve=>{const u=new SpeechSynthesisUtterance('test');u.volume=0;u.voice=__voices[0];u.onend=()=>resolve({ended:true,same:u.voice===__voices[0]});u.onerror=e=>resolve({error:e.error});speechSynthesis.speak(u)})`,true);
  assert(spoken.ended&&spoken.same,'Silent native speech routing failed');speech='passed-native-silent-utterance';
 }
 console.log(JSON.stringify({passed:true,native_window_and_css_display:true,quiet_default_protection:true,actual_permission_grant_respected:true,detail_basic_consistency:true,revocation_restores_protection:true,retained_detailed_objects_revoked:true,regrant_refreshes_native_details:true,css_permission_transition_events:true,resize_and_move_consistency:true,effective_virtual_screen_events:true,virtual_bucket_grow_shrink_css_and_iframe:true,speech,paid_model_calls:0}));
}finally{
 try{await call('Browser.resetPermissions')}finally{ws.close()}
}
