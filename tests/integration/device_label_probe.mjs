export async function deviceLabelProbe(){
 const checks={},details={};
 const demand=(value,message)=>{if(!value)throw Error(message)};
 const bounded=async(promise,label)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' timeout')),10000)})])}finally{clearTimeout(timer)}};
 async function test(name,fn){await fetch('/progress',{method:'POST',body:JSON.stringify({name,phase:'start',checks}),signal:AbortSignal.timeout(2000)});try{details[name]=await fn();checks[name]=true}catch(error){details[name]={error:String(error)};checks[name]=false}}
 const expected=d=>`${d.kind==='videoinput'?'Camera':d.kind==='audioinput'?'Microphone':'Speaker'}${d.deviceId?' '+d.deviceId.slice(0,8):''}`;
 const stop=stream=>stream?.getTracks().forEach(track=>track.stop());
 await test('media_device_aliases',async()=>{
  const prior=await navigator.mediaDevices.enumerateDevices();let stream;
  try{stream=await bounded(navigator.mediaDevices.getUserMedia({audio:true,video:true}),'alias capture');
   const first=await navigator.mediaDevices.enumerateDevices(),second=await navigator.mediaDevices.enumerateDevices();
   demand(first.length===second.length,'Enumeration changed without device change');
   for(const d of first){if(d.label)demand(d.label===expected(d),'Device name not minimized for '+d.kind);demand(d.toJSON().label===d.label,'JSON reopened native label');const again=second.find(x=>x.kind===d.kind&&x.deviceId===d.deviceId);demand(again?.label===d.label,'Alias unstable')}
   const saved=[];for(const track of stream.getTracks()){
    const id=track.getSettings().deviceId,device=first.find(d=>d.deviceId===id&&d.kind===(track.kind==='video'?'videoinput':'audioinput'));
    demand(device&&track.label===device.label,'Track/device aliases disagree for '+track.kind);const clone=track.clone();saved.push({track,clone,label:track.label});demand(clone.label===track.label,'Clone reopened label');clone.stop();demand(clone.label===track.label,'Stopped clone reopened label');
   }
   stop(stream);for(const item of saved)demand(item.track.label===item.label&&item.clone.label===item.label,'Stopped track reopened label');
   const camera=first.find(d=>d.kind==='videoinput'&&d.label);demand(camera,'No authorized camera');const selected=await bounded(navigator.mediaDevices.getUserMedia({video:{deviceId:{exact:camera.deviceId}},audio:false}),'ID routing');
   try{demand(selected.getVideoTracks()[0].getSettings().deviceId===camera.deviceId,'ID routing changed');demand(selected.getVideoTracks()[0].label===camera.label,'Selected device alias changed')}finally{stop(selected)}
   return {deviceJSONAndTrackParity:true,stableEnumeration:true,cloneAndStopStable:true,exactIdRouting:true,priorHiddenLabels:prior.filter(d=>!d.label).length};
  }finally{stop(stream)}
 });
 await test('media_labels_retained',async()=>{
  const iframe=document.createElement('iframe');let listener;delete globalThis.__mbRetainedDevices;
  iframe.srcdoc=`<script>onload=async()=>{try{const stream=await navigator.mediaDevices.getUserMedia({video:true}),devices=await navigator.mediaDevices.enumerateDevices(),track=stream.getVideoTracks()[0];parent.__mbRetainedDevices={stream,track,clone:track.clone(),devices};parent.postMessage({ownedDeviceRetention:true},'http://127.0.0.1:18858')}catch(e){parent.postMessage({ownedDeviceRetention:false},'http://127.0.0.1:18858')}}</script>`;
  try{const ready=new Promise((resolve,reject)=>{listener=event=>{if(event.source===iframe.contentWindow&&event.origin===location.origin&&typeof event.data?.ownedDeviceRetention==='boolean')event.data.ownedDeviceRetention?resolve():reject(Error('Owned frame capture failed'))};addEventListener('message',listener)});document.body.append(iframe);await bounded(ready,'retained device frame');
   const retained=globalThis.__mbRetainedDevices,label=retained.track.label,id=retained.track.getSettings().deviceId,device=retained.devices.find(d=>d.kind==='videoinput'&&d.deviceId===id);demand(device&&label===expected(device)&&retained.clone.label===label,'Initial frame aliases wrong');
   stop(retained.stream);retained.clone.stop();iframe.remove();await new Promise(resolve=>setTimeout(resolve,50));demand(retained.track.label===label&&retained.clone.label===label&&device.label===label&&device.toJSON().label===label,'Detached owner reopened physical labels');
   return {afterStop:true,afterOwnerDetach:true,retainedDeviceJSON:true,retainedClone:true};
  }finally{removeEventListener('message',listener);const retained=globalThis.__mbRetainedDevices;stop(retained?.stream);retained?.clone.stop();delete globalThis.__mbRetainedDevices;iframe.remove()}
 });
 await test('drm_identifier_policy',async()=>{
  const config={initDataTypes:['keyids'],videoCapabilities:[{contentType:'video/mp4; codecs="avc1.42c01e"'}],distinctiveIdentifier:'required',persistentState:'required',sessionTypes:['persistent-license']};let denied=false;
  try{await bounded(navigator.requestMediaKeySystemAccess('org.w3.clearkey',[config]),'distinctive DRM identifier')}catch(error){denied=error.name==='NotSupportedError'}
  demand(denied,'ClearKey advertised persistent device identity');
  return {distinctiveIdentifierRejected:true,persistentLicenseRejected:true,temporaryClearKeyPlaybackCoveredBy:'clearkey_actual_decryption',commercialCDMNotClaimed:true};
 });
 return {checks,details};
}
