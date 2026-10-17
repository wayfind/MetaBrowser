// Serialized into an owned loopback fixture. Fake devices are enabled only by
// the runner's explicit --extended-media option, never in the user's browser.
export async function extendedMediaProbe(){
 const checks={},details={};
 const check=(value,message)=>{if(!value)throw Error(message)};
 const timeout=async(promise,label,ms=10000)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' timeout')),ms)})])}finally{clearTimeout(timer)}};
 const progress=async(name,phase)=>{await fetch('/progress',{method:'POST',body:JSON.stringify({name,phase,checks}),signal:AbortSignal.timeout(2000)})};
 const test=async(name,fn)=>{globalThis.__mbMediaProgress=name;await progress(name,'start');try{details[name]=await fn();checks[name]=true}catch(error){details[name]={error:String(error)};checks[name]=false}await progress(name,'complete')};
 const stop=stream=>stream?.getTracks().forEach(track=>track.stop());
 const pixels=async frame=>{const bytes=new Uint8Array(frame.allocationSize({format:'RGBA'}));await frame.copyTo(bytes,{format:'RGBA'});return bytes};
 const canvas=(width=32,height=32)=>{const c=document.createElement('canvas');c.width=width;c.height=height;const x=c.getContext('2d');x.fillStyle='#2468ac';x.fillRect(0,0,width,height);return c};
 await test('webgpu_canvas_exports',async()=>{
  const adapter=await navigator.gpu.requestAdapter();check(adapter,'No GPU adapter');const device=await adapter.requestDevice();
  async function read(source,width,height,origin=[0,0]){
   const stride=Math.ceil(width*4/256)*256,texture=device.createTexture({size:[width,height],format:'rgba8unorm',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.COPY_SRC|GPUTextureUsage.RENDER_ATTACHMENT}),buffer=device.createBuffer({size:stride*height,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
   device.pushErrorScope('validation');
   try{device.queue.copyExternalImageToTexture({source,origin},{texture},[width,height]);const encoder=device.createCommandEncoder();encoder.copyTextureToBuffer({texture},{buffer,bytesPerRow:stride},[width,height]);device.queue.submit([encoder.finish()]);await timeout(buffer.mapAsync(GPUMapMode.READ),'canvas GPU map');const bytes=new Uint8Array(buffer.getMappedRange()),packed=new Uint8Array(width*height*4);for(let y=0;y<height;y++)packed.set(bytes.subarray(y*stride,y*stride+width*4),y*width*4);buffer.unmap();return packed}finally{const validation=await timeout(device.popErrorScope(),'GPU validation');texture.destroy();buffer.destroy();check(!validation,validation?.message||'GPU validation error')}
  }
  try{
   for(const c of [canvas(),new OffscreenCanvas(32,32)]){
    const x=c.getContext('2d');for(let i=0;i<32;i++){x.fillStyle=`rgb(${i*7},${255-i*3},${i*5})`;x.fillRect(i,0,1,32)}
    for(const [w,h,origin] of [[32,32,[0,0]],[3,2,[4,5]]]){const expected=x.getImageData(...origin,w,h).data,actual=await read(c,w,h,origin);let mismatch=0;for(let i=0;i<expected.length;i++)mismatch+=actual[i]!==expected[i];check(mismatch===0,'Canvas→GPU exposes different pixels: '+JSON.stringify({mismatch,source:c.constructor.name,origin,expected:[...expected.slice(0,16)],actual:[...actual.slice(0,16)]}))}
   }
   const huge=canvas(2049,2048);try{let refused=false;try{await read(huge,1,1)}catch(error){refused=error.name==='NotSupportedError'}check(refused,'GPU tiny crop bypassed full-image budget')}finally{huge.width=huge.height=1}
   const raw=new Uint8ClampedArray(4*4*4);for(let i=0;i<16;i++)raw.set([i*11,255-i*7,i*3,255],i*4);const uploaded=await read(new ImageData(raw,4,4),4,4);check(uploaded.every((v,i)=>v===raw[i]),'Caller ImageData changed');
   const image=new Image();await timeout(new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src='http://127.0.0.1:18859/taint.svg'}),'taint image');const tainted=canvas(16,16);tainted.getContext('2d').drawImage(image,0,0);let denied=false;try{await read(tainted,16,16)}catch(error){denied=error.name==='SecurityError'}check(denied,'GPU copy laundered tainted canvas');
   return {htmlCanvas:true,offscreenCanvas:true,protectedPixelsMatch:true,cropBeforeUpload:true,budgetRefused:true,taintRefused:true,callerImageDataExact:true};
  }finally{device.destroy()}
 });
 await test('worker_canvas_exports',async()=>{
  const url=URL.createObjectURL(new Blob([`onmessage=async()=>{try{const c=new OffscreenCanvas(32,32),x=c.getContext('2d');x.fillStyle='#2468ac';x.fillRect(0,0,32,32);const expected=x.getImageData(0,0,32,32).data;for(const bitmap of [await createImageBitmap(c),await createImageBitmap(await c.convertToBlob()),c.transferToImageBitmap()]){const f=new VideoFrame(bitmap,{timestamp:0});try{const b=new Uint8Array(f.allocationSize({format:'RGBA'}));await f.copyTo(b,{format:'RGBA'});if(b.length!==expected.length||b.some((v,i)=>v!==expected[i]))throw Error('Worker export pixels differ')}finally{f.close();bitmap.close()}}postMessage({passed:true})}catch(e){postMessage({error:String(e)})}}`],{type:'text/javascript'})),worker=new Worker(url);
  try{const received=new Promise((resolve,reject)=>{worker.onmessage=e=>resolve(e.data);worker.onerror=e=>reject(Error(e.message))});worker.postMessage(0);const value=await timeout(received,'worker canvas export');check(value.passed===true,value.error||'Worker failed');return {bitmap:true,png:true,transfer:true,protectedPixelsMatch:true}}finally{worker.terminate();URL.revokeObjectURL(url)}
 });
 await test('canvas_budget_fail_closed',async()=>{
  const c=canvas(2049,2048),off=new OffscreenCanvas(2049,2048);off.getContext('2d').fillRect(0,0,2049,2048);
  const failures={};
  for(const [name,fn] of Object.entries({read:()=>c.getContext('2d').getImageData(0,0,1,1),frame:()=>new VideoFrame(c,{timestamp:0}),bitmap:()=>createImageBitmap(c),offscreenBlob:()=>off.convertToBlob(),transfer:()=>off.transferToImageBitmap()})){
   try{const value=await fn();value?.close?.();failures[name]=false}catch(error){failures[name]=['NotSupportedError','InvalidStateError','EncodingError','NotReadableError'].includes(error.name)}
  }
  // HTML canvas serialization specifies an empty data URL/null blob on failure.
  failures.dataURL=c.toDataURL()==='data:,';
  failures.blob=(await timeout(new Promise(resolve=>c.toBlob(resolve)),'over-budget blob'))===null;
  c.width=c.height=1;off.width=off.height=1;
  check(Object.values(failures).every(Boolean),'Raw or unexpected over-budget export: '+JSON.stringify(failures));return failures;
 });
 await test('canvas_png_exports',async()=>{
  const c=canvas(),expected=c.getContext('2d').getImageData(0,0,32,32).data;
  const off=new OffscreenCanvas(32,32);off.getContext('2d').fillStyle='#2468ac';off.getContext('2d').fillRect(0,0,32,32);
  for(const blob of [await(await fetch(c.toDataURL())).blob(),await new Promise(resolve=>c.toBlob(resolve)),await off.convertToBlob()]){
   check(blob?.type==='image/png','PNG serialization failed');const bitmap=await createImageBitmap(blob),frame=new VideoFrame(bitmap,{timestamp:0});
   try{const actual=await pixels(frame);check(actual.length===expected.length&&actual.every((v,i)=>v===expected[i]),'PNG exposed different pixels')}finally{frame.close();bitmap.close()}
  }return {htmlDataURL:true,htmlBlob:true,offscreenBlob:true,protectedPixelsMatch:true};
 });
 await test('canvas_alpha_preserved',async()=>{
  const c=canvas(),x=c.getContext('2d');x.clearRect(0,0,32,32);x.fillStyle='rgba(64,128,192,.5)';x.fillRect(8,8,16,16);
  const expected=x.getImageData(0,0,32,32).data,bitmap=await createImageBitmap(c,{premultiplyAlpha:'none'}),frame=new VideoFrame(bitmap,{timestamp:0});
  try{const actual=await pixels(frame);for(let i=3;i<actual.length;i+=4){check(actual[i]===expected[i],'Alpha changed');if(!actual[i])check(actual[i-1]===0&&actual[i-2]===0&&actual[i-3]===0,'Transparent color leaked')}return {alphaExact:true,transparentBlack:true}}finally{frame.close();bitmap.close()}
 });
 await test('canvas_float16_exports',async()=>{
  const off=new OffscreenCanvas(16,16),x=off.getContext('2d',{colorSpace:'display-p3',colorType:'float16'});
  check(x.getContextAttributes().colorType==='float16','Float16 context unavailable');x.fillStyle='color(display-p3 .25 .5 .75)';x.fillRect(0,0,16,16);
  const a=x.getImageData(0,0,16,16,{colorSpace:'display-p3',pixelFormat:'rgba-float16'}),b=x.getImageData(0,0,16,16,{colorSpace:'display-p3',pixelFormat:'rgba-float16'});
  check(a.data instanceof Float16Array&&a.data.every((v,i)=>Number.isFinite(v)&&v===b.data[i]),'Float16 readback unstable');
  const bitmap=off.transferToImageBitmap(),frame=new VideoFrame(bitmap,{timestamp:0});try{check((await pixels(frame)).length===16*16*4,'Float16 transfer failed')}finally{frame.close();bitmap.close()}
  return {colorSpace:a.colorSpace,pixelFormat:a.pixelFormat,stable:true,mediaConversion:true};
 });
 await test('fake_camera_capture',async()=>{
  let stream,reader,frame;try{
   stream=await timeout(navigator.mediaDevices.getUserMedia({video:{width:{exact:320},height:{exact:240}},audio:false}),'fake camera');
   const track=stream.getVideoTracks()[0],settings=track.getSettings();check(settings.width===320&&settings.height===240,'Constraints ignored');
   reader=new MediaStreamTrackProcessor({track}).readable.getReader();const first=await timeout(reader.read(),'camera frame');frame=first.value;
   check(!first.done&&frame?.displayWidth===320&&frame.displayHeight===240,'No actual camera frame');const bytes=await pixels(frame);check(bytes.some((v,i)=>i%4!==3&&v>20),'Empty fake frame');
   await track.applyConstraints({width:{exact:640},height:{exact:480}});check(track.getSettings().width===640,'Constraint update failed');
   const devices=await navigator.mediaDevices.enumerateDevices();check(devices.some(d=>d.kind==='videoinput')&&devices.some(d=>d.kind==='audioinput'),'Missing fake devices');
   // Never persist labels, device IDs, group IDs or raw captured pixels.
   return {actualFrame:true,width:320,height:240,constraintUpdate:true,inputKinds:[...new Set(devices.map(d=>d.kind))].sort()};
  }finally{frame?.close();stop(stream);if(reader)await timeout(reader.cancel(),'camera reader cleanup',2000)}
 });
 await test('camera_clone_lifecycle',async()=>{
  let stream,clone;try{stream=await timeout(navigator.mediaDevices.getUserMedia({video:true}),'clone source');const source=stream.getVideoTracks()[0];clone=source.clone();check(clone.id!==source.id&&clone.readyState==='live','Invalid clone');clone.stop();check(clone.readyState==='ended'&&source.readyState==='live','Clone stop stopped original');source.stop();check(source.readyState==='ended','Source did not end');return {independentClone:true,stopped:true}}finally{clone?.stop();stop(stream)}
 });
 await test('fake_av_recording',async()=>{
  let stream,recorder,video,url;try{
   stream=await timeout(navigator.mediaDevices.getUserMedia({video:{width:320,height:240},audio:true}),'fake AV');check(stream.getAudioTracks().length===1&&stream.getVideoTracks().length===1,'Missing AV tracks');
   const chunks=[];recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});
   const ended=new Promise((resolve,reject)=>{recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.onstop=resolve;recorder.onerror=e=>reject(e.error)});recorder.start();await new Promise(resolve=>setTimeout(resolve,750));recorder.stop();await timeout(ended,'AV recorder');
   const blob=new Blob(chunks,{type:recorder.mimeType});check(blob.size>0,'Empty AV recording');url=URL.createObjectURL(blob);video=document.createElement('video');video.muted=true;
   const loaded=new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=()=>reject(Error('Recorded AV decode failed'))});video.src=url;await timeout(loaded,'AV loaded');
   const presented=new Promise((resolve,reject)=>{video.requestVideoFrameCallback(resolve);video.play().catch(reject)});await timeout(presented,'AV presentation');video.pause();
   const frame=new VideoFrame(video,{timestamp:0});try{check((await pixels(frame)).length>0,'No decoded video')}finally{frame.close()}
   const context=new OfflineAudioContext(1,48000,48000);const audio=await timeout(context.decodeAudioData(await blob.arrayBuffer()),'Recorded audio decode');check(audio.length>0&&audio.getChannelData(0).every(Number.isFinite),'No decoded audio');
   return {videoDecoded:true,audioDecoded:true,bytes:blob.size};
  }finally{if(recorder?.state==='recording')recorder.stop();stop(stream);if(video){video.pause();video.removeAttribute('src');video.load()}if(url)URL.revokeObjectURL(url)}
 });
 await test('media_permissions_policy',async()=>{
  const iframe=document.createElement('iframe');iframe.allow="camera 'none'; microphone 'none'; display-capture 'none'";
  iframe.srcdoc=`<script>onload=async()=>{const results={};for(const kind of ['video','audio']){try{const stream=await navigator.mediaDevices.getUserMedia({[kind]:true});stream.getTracks().forEach(t=>t.stop());results[kind]=false}catch(e){results[kind]=e.name==='NotAllowedError'}}parent.postMessage({ownedMediaPolicy:results},'http://127.0.0.1:18858')}</script>`;
  let listener;try{const result=new Promise(resolve=>{listener=event=>{if(event.origin===location.origin&&event.source===iframe.contentWindow&&event.data?.ownedMediaPolicy)resolve(event.data.ownedMediaPolicy)};addEventListener('message',listener)});document.body.append(iframe);const value=await timeout(result,'permissions policy');check(value.video&&value.audio,'Policy bypassed');return value}finally{removeEventListener('message',listener);iframe.remove()}
 });
 await test('offline_audio_worklet',async()=>{
  async function render(){const context=new OfflineAudioContext(2,1024,48000);const url=URL.createObjectURL(new Blob([`class Constant extends AudioWorkletProcessor{process(i,o){for(const channels of o)for(const channel of channels)channel.fill(.125);return true}}registerProcessor('owned-constant',Constant)`],{type:'text/javascript'}));try{await timeout(context.audioWorklet.addModule(url),'worklet module');const node=new AudioWorkletNode(context,'owned-constant',{outputChannelCount:[2]});node.connect(context.destination);globalThis.__mbMediaProgress='offline_audio_worklet.render';const buffer=await timeout(context.startRendering(),'offline worklet rendering');return [buffer.getChannelData(0).slice(),buffer.getChannelData(1).slice()]}finally{URL.revokeObjectURL(url)}}
  const a=await render(),b=await render();check(a.every((channel,c)=>channel.every((v,i)=>v===b[c][i]&&Math.abs(v-.125)<=1e-7)),'Worklet completion unstable or incorrect');check(a[0].some(v=>v!==.125),'Worklet bypassed offline protection');return {channels:2,frames:1024,stable:true,protected:true};
 });
 await test('realtime_audio_worklet',async()=>{
  const context=new AudioContext({sampleRate:48000}),url=URL.createObjectURL(new Blob([`class Probe extends AudioWorkletProcessor{process(i,o){const data=i[0]?.[0];if(data?.some(v=>v!==0)){this.port.postMessage([...data]);return false}return true}}registerProcessor('owned-probe',Probe)`],{type:'text/javascript'}));
  try{await timeout(context.audioWorklet.addModule(url),'worklet module');const node=new AudioWorkletNode(context,'owned-probe'),source=new ConstantSourceNode(context,{offset:.125}),gain=new GainNode(context,{gain:0});const received=new Promise(resolve=>{node.port.onmessage=e=>resolve(e.data)});source.connect(node);node.connect(gain);gain.connect(context.destination);source.start();await context.resume();const samples=await timeout(received,'realtime worklet');check(samples.length>0&&samples.every(v=>v===.125),'Realtime source altered');source.stop();node.disconnect();return {frames:samples.length,rawSamplesExact:true,audibleOutput:false}}finally{await context.close();URL.revokeObjectURL(url)}
 });
 await test('owned_tab_capture',async()=>{
  let stream,reader,frame;try{
   check(document.title==='Owned GPU and media fixture','Wrong capture target');
   stream=await timeout(navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'browser'},audio:false,preferCurrentTab:true,selfBrowserSurface:'include',monitorTypeSurfaces:'exclude'}),'owned tab capture');
   const track=stream.getVideoTracks()[0];check(track.getSettings().displaySurface==='browser','Capture is not the owned browser tab');reader=new MediaStreamTrackProcessor({track}).readable.getReader();const first=await timeout(reader.read(),'tab frame');frame=first.value;check(frame&&frame.displayWidth>0&&frame.displayHeight>0,'Missing tab frame');return {surface:'browser',actualFrame:true,desktopCaptured:false};
  }finally{frame?.close();stop(stream);if(reader)await timeout(reader.cancel(),'tab reader cleanup',2000)}
 });
 await test('clearkey_actual_decryption',async()=>{
  const encode=value=>new TextEncoder().encode(JSON.stringify(value));
  const b64=hex=>btoa(String.fromCharCode(...hex.match(/../g).map(b=>parseInt(b,16)))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
  const kid=b64('112233445566778899aabbccddeeff00'),key=b64('00112233445566778899aabbccddeeff');
  const access=await timeout(navigator.requestMediaKeySystemAccess('org.w3.clearkey',[{initDataTypes:['keyids'],videoCapabilities:[{contentType:'video/mp4; codecs="avc1.42c01e"'}],distinctiveIdentifier:'not-allowed',persistentState:'not-allowed',sessionTypes:['temporary']}]),'ClearKey access');
  const keys=await access.createMediaKeys(),session=keys.createSession(),video=document.createElement('video'),media=new MediaSource(),mediaURL=URL.createObjectURL(media);video.muted=true;video.style.cssText='width:160px;height:96px';document.body.append(video);
  try{await video.setMediaKeys(keys);const updated=new Promise((resolve,reject)=>{session.onmessage=()=>{session.update(encode({keys:[{kty:'oct',kid,k:key}],type:'temporary'})).then(resolve,reject)}});await session.generateRequest('keyids',encode({kids:[kid]}));await timeout(updated,'ClearKey update');
   const opened=new Promise(resolve=>{media.onsourceopen=resolve});video.src=mediaURL;await timeout(opened,'CENC MSE open');const bytes=await(await fetch('/media-avc-clearkey.mp4')).arrayBuffer();const buffer=media.addSourceBuffer('video/mp4; codecs="avc1.42c01e"');const appended=new Promise((resolve,reject)=>{buffer.onupdateend=resolve;buffer.onerror=()=>reject(Error('CENC MSE append failed'))});buffer.appendBuffer(bytes);await timeout(appended,'CENC MSE append');media.endOfStream();
   const presented=new Promise((resolve,reject)=>{let first;const frame=(now,meta)=>{if(first===undefined)first=meta.mediaTime;if(meta.mediaTime-first>=.19)resolve();else video.requestVideoFrameCallback(frame)};video.requestVideoFrameCallback(frame);video.onerror=()=>reject(Error('CENC decode failed: '+video.error?.code));video.play().catch(reject)});try{await timeout(presented,'CENC frame presentation')}catch(error){throw Error(String(error)+' '+JSON.stringify({time:video.currentTime,ready:video.readyState,error:video.error?.code,keys:[...session.keyStatuses.values()],frames:video.getVideoPlaybackQuality().totalVideoFrames}))}video.pause();check(video.videoWidth===160&&video.videoHeight===96,'CENC decoded dimensions invalid');
   // A CDM may intentionally prohibit pixel readback even after presentation.
   // Keep that restriction: successful frame callbacks prove actual playback.
   let readbackDenied=false;try{const frame=new VideoFrame(video,{timestamp:0});try{const bytes=await pixels(frame);check(bytes.some((v,i)=>i%4!==3&&v>20),'CENC frame empty')}finally{frame.close()}}catch(error){if(!['SecurityError','InvalidStateError'].includes(error.name))throw error;readbackDenied=true}
   check(video.readyState>=HTMLMediaElement.HAVE_CURRENT_DATA&&session.keyStatuses.size>0,'Encrypted source not ready');check(readbackDenied,'Protected CDM pixels became script-readable');
   return {keySystem:'org.w3.clearkey',temporarySession:true,distinctiveIdentifier:false,actualDecryption:true,readbackDenied,externalLicenseRequests:0};
  }finally{video.pause();video.removeAttribute('src');video.load();await session.close();await video.setMediaKeys(null);video.remove();URL.revokeObjectURL(mediaURL)}
 });
 return {checks,details};
}
