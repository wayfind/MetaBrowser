// Caller-owned loopback CDP only. Never attach to the user's normal profile.
import assert from 'node:assert/strict';
import {extendedMediaProbe} from './media_lifecycle_probe.mjs';
import {gpuPolicyProbe} from './gpu_policy_probe.mjs';
import {deviceLabelProbe} from './device_label_probe.mjs';
import {hardwarePolicyControl} from './hardware_policy_control.mjs';
const port=Number(process.argv[2]);assert(port>=18850&&port<=18859);
const targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target=targets.find(t=>t.type==='page');assert(target);
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let seq=0;const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)};
function call(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timeout'))},process.argv[3]==='extended'?150000:45000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))})}
async function probe(){
 const checks={};const details={};
 async function test(name,fn){await fetch('/progress',{method:'POST',body:JSON.stringify({name,phase:'start',checks}),signal:AbortSignal.timeout(2000)});try{details[name]=await fn();checks[name]=true}catch(e){checks[name]=false;details[name]={error:String(e)}}}
 const canvas=()=>{const c=document.createElement('canvas');c.width=64;c.height=64;const x=c.getContext('2d');x.fillStyle='#2468ac';x.fillRect(0,0,64,64);x.fillStyle='#fa83c0';x.font='17px serif';x.fillText('GPU privacy',0,30);return c};
 const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const pixels=frame=>{const bytes=new Uint8Array(frame.allocationSize({format:'RGBA'}));return frame.copyTo(bytes,{format:'RGBA'}).then(()=>bytes)};
 await test('webgl',async()=>{
  const result={};for(const kind of ['webgl','webgl2']){
   const c=document.createElement('canvas'),g=c.getContext(kind);if(!g)throw Error(kind+' unavailable');
   g.clearColor(.25,.5,.75,1);g.clear(g.COLOR_BUFFER_BIT);const p=new Uint8Array(4);g.readPixels(0,0,1,1,g.RGBA,g.UNSIGNED_BYTE,p);
   if(Math.abs(p[0]-64)>1||Math.abs(p[1]-128)>1||Math.abs(p[2]-191)>1||p[3]!==255)throw Error('incorrect clear/readback');
   const program=g.createProgram();for(const [type,code] of [[g.VERTEX_SHADER,'attribute vec2 pos;void main(){gl_Position=vec4(pos,0.,1.);}'],[g.FRAGMENT_SHADER,'precision mediump float;void main(){gl_FragColor=vec4(.25,.5,.75,1.);}']]){const shader=g.createShader(type);g.shaderSource(shader,code);g.compileShader(shader);if(!g.getShaderParameter(shader,g.COMPILE_STATUS))throw Error(g.getShaderInfoLog(shader));g.attachShader(program,shader)}
   g.linkProgram(program);if(!g.getProgramParameter(program,g.LINK_STATUS))throw Error('link failed');g.useProgram(program);g.bindBuffer(g.ARRAY_BUFFER,g.createBuffer());g.bufferData(g.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),g.STATIC_DRAW);const loc=g.getAttribLocation(program,'pos');g.enableVertexAttribArray(loc);g.vertexAttribPointer(loc,2,g.FLOAT,false,0,0);g.drawArrays(g.TRIANGLES,0,3);const draw=new Uint8Array(4);g.readPixels(0,0,1,1,g.RGBA,g.UNSIGNED_BYTE,draw);
   if(draw.some((v,i)=>Math.abs(v-[64,128,191,255][i])>(i===3?0:1)))throw Error('raster shader incorrect');
   const debug=g.getExtension('WEBGL_debug_renderer_info');result[kind]={renderer:g.getParameter(g.RENDERER),debugRenderer:debug?g.getParameter(debug.UNMASKED_RENDERER_WEBGL):null,pixel:[...p],rasterPixel:[...draw],maxTexture:g.getParameter(g.MAX_TEXTURE_SIZE)};
  }return result;
 });
 await test('webgpu',async()=>{
  const adapter=await navigator.gpu?.requestAdapter();if(!adapter)throw Error('adapter unavailable');
  const device=await adapter.requestDevice();const data=device.createBuffer({size:16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
  const read=device.createBuffer({size:16,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
  const pipeline=device.createComputePipeline({layout:'auto',compute:{module:device.createShaderModule({code:'@group(0) @binding(0) var<storage,read_write> a:array<u32>; @compute @workgroup_size(4) fn main(@builtin(global_invocation_id) i:vec3<u32>){a[i.x]=7u+i.x*i.x;}'}),entryPoint:'main'}});
  const group=device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:data}}]});
  const enc=device.createCommandEncoder(),pass=enc.beginComputePass();pass.setPipeline(pipeline);pass.setBindGroup(0,group);pass.dispatchWorkgroups(1);pass.end();enc.copyBufferToBuffer(data,0,read,0,16);device.queue.submit([enc.finish()]);await read.mapAsync(GPUMapMode.READ);
  const values=[...new Uint32Array(read.getMappedRange())];read.unmap();if(JSON.stringify(values)!=='[7,8,11,16]')throw Error('compute incorrect');
  const texture=device.createTexture({size:[1,1],format:'rgba8unorm',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC});const raster=device.createBuffer({size:256,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});const render=device.createCommandEncoder();const rp=render.beginRenderPass({colorAttachments:[{view:texture.createView(),clearValue:[.25,.5,.75,1],loadOp:'clear',storeOp:'store'}]});rp.end();render.copyTextureToBuffer({texture},{buffer:raster,bytesPerRow:256},[1,1]);device.queue.submit([render.finish()]);await raster.mapAsync(GPUMapMode.READ);const renderPixel=[...new Uint8Array(raster.getMappedRange(),0,4)];raster.unmap();if(renderPixel.some((v,i)=>Math.abs(v-[64,128,191,255][i])>1))throw Error('WebGPU render target incorrect');
  device.pushErrorScope('validation');device.createBuffer({size:16,usage:0});const validation=await device.popErrorScope();if(!validation)throw Error('WebGPU validation disabled');
  const info=adapter.info;const result={vendor:info.vendor,architecture:info.architecture,device:info.device,description:info.description,isFallbackAdapter:info.isFallbackAdapter,values,renderPixel,validationRetained:true,features:[...adapter.features].sort()};device.destroy();return result;
 });
 await test('worker_gpu',async()=>{
  const source=`onmessage=async()=>{try{const c=new OffscreenCanvas(8,8),g=c.getContext('webgl2');const a=await navigator.gpu?.requestAdapter();postMessage({webgl2:!!g,webgpu:!!a,fallback:a?.info.isFallbackAdapter})}catch(e){postMessage({error:String(e)})}}`;
  const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));const worker=new Worker(url);
  try{return await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('worker timeout')),15000);worker.onmessage=e=>{clearTimeout(timer);e.data.webgl2&&e.data.webgpu?resolve(e.data):reject(Error(JSON.stringify(e.data)))};worker.postMessage(0)})}finally{worker.terminate();URL.revokeObjectURL(url)};
 });
 await test('canvas_videoframe_roundtrip',async()=>{
  const c=canvas(),f=new VideoFrame(c,{timestamp:1234});try{const bytes=await pixels(f);const clone=f.clone();try{const b=await pixels(clone);if(await digest(bytes)!==await digest(b))throw Error('clone changed pixels')}finally{clone.close()}
   const dest=document.createElement('canvas');dest.width=64;dest.height=64;dest.getContext('2d').drawImage(f,0,0);return {width:f.displayWidth,height:f.displayHeight,timestamp:f.timestamp,frameHash:await digest(bytes),canvasHash:await digest(c.getContext('2d').getImageData(0,0,64,64).data),roundtripHash:await digest(dest.getContext('2d').getImageData(0,0,64,64).data)};
  }finally{f.close()}
 });
 await test('imagebitmap_transfer',async()=>{
  const c=canvas(),bitmap=await createImageBitmap(c);const off=new OffscreenCanvas(64,64);off.getContext('bitmaprenderer').transferFromImageBitmap(bitmap);
  const frame=new VideoFrame(off,{timestamp:1});try{return {hash:await digest(await pixels(frame))}}finally{frame.close();bitmap.close()}
 });
 await test('protected_canvas_handoffs',async()=>{
  const c=canvas(),expected=await digest(c.getContext('2d').getImageData(0,0,64,64).data);
  const f=new VideoFrame(c,{timestamp:0});let direct;try{direct=await digest(await pixels(f))}finally{f.close()}
  const bitmap=await createImageBitmap(c),b=new VideoFrame(bitmap,{timestamp:0});let viaBitmap;try{viaBitmap=await digest(await pixels(b))}finally{b.close();bitmap.close()}
  const off=new OffscreenCanvas(64,64),x=off.getContext('2d');x.fillStyle='#2468ac';x.fillRect(0,0,64,64);x.fillStyle='#fa83c0';x.font='17px serif';x.fillText('GPU privacy',0,30);
  const offExpected=await digest(x.getImageData(0,0,64,64).data),transfer=off.transferToImageBitmap(),t=new VideoFrame(transfer,{timestamp:0});let viaTransfer;try{viaTransfer=await digest(await pixels(t))}finally{t.close();transfer.close()}
  if(direct!==expected||viaBitmap!==expected||viaTransfer!==offExpected)throw Error(JSON.stringify({directMatches:direct===expected,bitmapMatches:viaBitmap===expected,transferMatches:viaTransfer===offExpected}));
  return {directMatches:true,bitmapMatches:true,transferMatches:true};
 });
 await test('taint_preserved',async()=>{
  const img=new Image();await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('cross-origin fixture failed'));img.src='http://127.0.0.1:18859/taint.svg'});
  const c=document.createElement('canvas');c.width=c.height=16;c.getContext('2d').drawImage(img,0,0);
  const bitmap=await createImageBitmap(c),off=new OffscreenCanvas(16,16);off.getContext('2d').drawImage(img,0,0);const transferred=off.transferToImageBitmap();
  const results=[];try{for(const source of [c,bitmap,transferred]){try{const f=new VideoFrame(source,{timestamp:0});f.close();results.push(false)}catch(e){results.push(e.name==='SecurityError')}}}finally{bitmap.close();transferred.close()}
  if(!results.every(Boolean))throw Error('Tainted canvas media became origin-clean');return {direct:true,bitmap:true,transfer:true};
 });
 await test('worker_media_transfer',async()=>{
  const c=canvas(),expected=await digest(c.getContext('2d').getImageData(0,0,64,64).data),bitmap=await createImageBitmap(c);
  const code=`onmessage=async e=>{try{const b=e.data;const f=new VideoFrame(b,{timestamp:123});b.close();const clone=f.clone();f.close();postMessage(clone,[clone])}catch(e){postMessage({error:String(e)})}}`;
  const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'})),worker=new Worker(url);
  try{const received=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('worker transfer timeout')),10000);worker.onmessage=e=>{clearTimeout(timer);e.data.error?reject(Error(e.data.error)):resolve(e.data)};worker.postMessage(bitmap,[bitmap])});try{if(received.timestamp!==123||await digest(await pixels(received))!==expected)throw Error('worker clone/transfer lost protection');return {protectedAcrossWorker:true,timestamp:123}}finally{received.close()}}finally{worker.terminate();URL.revokeObjectURL(url);bitmap.close()}
 });
 await test('raw_rgba_frame_preserved',async()=>{
  const data=new Uint8Array(16*16*4);for(let i=0;i<data.length;i++)data[i]=i%256;
  const frame=new VideoFrame(data,{format:'RGBA',codedWidth:16,codedHeight:16,timestamp:42});try{const copy=await pixels(frame);if(copy.some((v,i)=>v!==data[i]))throw Error('Caller supplied pixels changed');return {exact:true,timestamp:frame.timestamp}}finally{frame.close()}
 });
 await test('canvas_rgb_bounds_and_crops',async()=>{
  const c=document.createElement('canvas');c.width=c.height=16;const x=c.getContext('2d'),original=new Uint8ClampedArray(16*16*4);
  for(let i=0;i<256;i++){original[i*4]=i;original[i*4+1]=255-i;original[i*4+2]=(i*71)%256;original[i*4+3]=255}x.putImageData(new ImageData(original,16,16),0,0);
  const full=x.getImageData(0,0,16,16).data,again=x.getImageData(0,0,16,16).data,crop=x.getImageData(4,5,3,2).data;
  if(!full.some((v,i)=>v!==original[i])||full.some((v,i)=>Math.abs(v-original[i])>(i%4===3?0:3))||full.some((v,i)=>v!==again[i]))throw Error('RGB error bounds, alpha or determinism failed');
  for(let y=0;y<2;y++)for(let xx=0;xx<3;xx++)for(let channel=0;channel<4;channel++)if(crop[(y*3+xx)*4+channel]!==full[((y+5)*16+xx+4)*4+channel])throw Error('Tiled read mismatch');
  const bitmap=await createImageBitmap(c,4,5,3,2),f=new VideoFrame(bitmap,{timestamp:0});try{const b=await pixels(f);if(b.some((v,i)=>v!==crop[i]))throw Error('ImageBitmap cropped before protection')}finally{f.close();bitmap.close()}
  return {maxRGBDelta:3,alphaExact:true,repeatStable:true,cropMatches:true,imageBitmapCropMatches:true};
 });
 await test('media_performance_1080p',async()=>{
  const off=new OffscreenCanvas(1920,1080),x=off.getContext('2d');x.fillStyle='#2468ac';x.fillRect(0,0,1920,1080);x.fillText('1080p synthetic export',4,40);
  const start=performance.now(),frame=new VideoFrame(off,{timestamp:0});try{const bytes=await pixels(frame);return {width:1920,height:1080,bytes:bytes.byteLength,milliseconds:Math.round((performance.now()-start)*10)/10}}finally{frame.close()}
 });
 await test('video_encoder_decoder',async()=>{
  const config={codec:'vp8',width:64,height:64,bitrate:100000,framerate:5};if(!(await VideoEncoder.isConfigSupported(config)).supported)throw Error('VP8 encoder unsupported');
  const chunks=[],errors=[];let decoderConfig;
  const encoder=new VideoEncoder({output:(chunk,meta)=>{const b=new Uint8Array(chunk.byteLength);chunk.copyTo(b);chunks.push({type:chunk.type,timestamp:chunk.timestamp,data:b});if(meta.decoderConfig)decoderConfig=meta.decoderConfig},error:e=>errors.push(String(e))});
  encoder.configure(config);const c=canvas();for(let i=0;i<3;i++){const f=new VideoFrame(c,{timestamp:i*200000});encoder.encode(f,{keyFrame:i===0});f.close()}await encoder.flush();encoder.close();
  const outputs=[];const decoder=new VideoDecoder({output:f=>{outputs.push({time:f.timestamp,width:f.displayWidth,height:f.displayHeight});f.close()},error:e=>errors.push(String(e))});decoder.configure(decoderConfig||{codec:'vp8'});for(const chunk of chunks)decoder.decode(new EncodedVideoChunk(chunk));await decoder.flush();decoder.close();
  if(errors.length||outputs.length!==3)throw Error(JSON.stringify({errors,outputs}));return {encoded:chunks.length,decoded:outputs};
 });
 await test('canvas_capture_recorder_playback',async()=>{
  const c=canvas(),stream=c.captureStream(10),chunks=[];const recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
  const blob=await new Promise((resolve,reject)=>{recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.onerror=e=>reject(Error(e.error));recorder.onstop=()=>resolve(new Blob(chunks,{type:recorder.mimeType}));recorder.start();let i=0;const timer=setInterval(()=>{c.getContext('2d').fillRect(i++,0,2,2);if(i===5){clearInterval(timer);recorder.stop()}},100)});
  stream.getTracks().forEach(t=>t.stop());if(!blob.size)throw Error('empty capture');const url=URL.createObjectURL(blob),video=document.createElement('video');video.muted=true;video.loop=true;
  try{await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('playback timeout')),8000);video.onloadeddata=()=>{clearTimeout(timer);resolve()};video.onerror=()=>{clearTimeout(timer);reject(Error('decode failed'))};video.src=url});
   await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('frame presentation timeout')),8000);video.requestVideoFrameCallback(()=>{clearTimeout(timer);video.pause();resolve()});video.play().catch(reject)});
   const frame=new VideoFrame(video,{timestamp:0});try{return {bytes:blob.size,width:video.videoWidth,height:video.videoHeight,decodedHash:await digest(await pixels(frame))}}finally{frame.close()}}
  finally{video.pause();video.removeAttribute('src');video.load();URL.revokeObjectURL(url)};
 });
 await test('webrtc_local_canvas_roundtrip',async()=>{
  // No STUN/TURN servers or remote peers; never report SDP or ICE addresses.
  const c=canvas(),stream=c.captureStream(10),a=new RTCPeerConnection({iceServers:[]}),b=new RTCPeerConnection({iceServers:[]}),qa=[],qb=[];let reader,received;const errors=[];
  const forward=(peer,queue,event)=>{if(!event.candidate)return;if(peer.remoteDescription)peer.addIceCandidate(event.candidate).catch(e=>errors.push(e.name));else queue.push(event.candidate)};
  a.onicecandidate=e=>forward(b,qb,e);b.onicecandidate=e=>forward(a,qa,e);
  const frames=new Promise((resolve,reject)=>{b.ontrack=e=>{if(e.track.kind!=='video')return;try{reader=new MediaStreamTrackProcessor({track:e.track}).readable.getReader();reader.read().then(resolve,reject)}catch(error){reject(error)}}});
  const timer=setInterval(()=>{c.getContext('2d').fillStyle='#fa83c0';c.getContext('2d').fillRect(1,1,3,3)},100);
  let timeout;
  try{for(const track of stream.getTracks())a.addTrack(track,stream);await a.setLocalDescription(await a.createOffer());await b.setRemoteDescription(a.localDescription);for(const candidate of qb.splice(0))await b.addIceCandidate(candidate);await b.setLocalDescription(await b.createAnswer());await a.setRemoteDescription(b.localDescription);for(const candidate of qa.splice(0))await a.addIceCandidate(candidate);
   const result=await Promise.race([frames,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('Local RTP receive timeout')),15000)})]);received=result.value;if(!received||received.displayWidth!==64||received.displayHeight!==64)throw Error('RTP frame invalid');
   const bytes=await pixels(received);if(!bytes.some((v,i)=>i%4!==3&&v>20)||errors.length)throw Error('RTP pixels or ICE failed');const stats=await b.getStats();let decoded=0;for(const stat of stats.values())if(stat.type==='inbound-rtp'&&stat.kind==='video')decoded+=stat.framesDecoded||0;if(decoded<1)throw Error('No actual decoded RTP frames');return {width:64,height:64,decodedFrames:decoded,externalServers:0};
  }finally{clearInterval(timer);clearTimeout(timeout);received?.close();reader?.cancel().catch(()=>{});a.close();b.close();stream.getTracks().forEach(t=>t.stop())}
 });
 await test('audio_data_clone',async()=>{
  const data=new Float32Array(480);for(let i=0;i<data.length;i++)data[i]=Math.sin(i/17)*.1;
  const a=new AudioData({format:'f32',sampleRate:48000,numberOfFrames:480,numberOfChannels:1,timestamp:0,data});const b=a.clone(),copy=new Float32Array(480);
  try{b.copyTo(copy,{planeIndex:0});if(copy.some((v,i)=>v!==data[i]))throw Error('PCM data altered');return {frames:a.numberOfFrames,rate:a.sampleRate,exact:true}}finally{a.close();b.close()}
 });
 await test('opus_audio_encoder_decoder',async()=>{
  const config={codec:'opus',sampleRate:48000,numberOfChannels:1,bitrate:64000};if(!(await AudioEncoder.isConfigSupported(config)).supported)throw Error('Opus encoder unsupported');
  const chunks=[],errors=[];let decoderConfig;const enc=new AudioEncoder({output:(chunk,meta)=>{const data=new Uint8Array(chunk.byteLength);chunk.copyTo(data);chunks.push({type:chunk.type,timestamp:chunk.timestamp,data});if(meta.decoderConfig)decoderConfig=meta.decoderConfig},error:e=>errors.push(String(e))});enc.configure(config);
  const data=new Float32Array(4800);for(let i=0;i<data.length;i++)data[i]=.1*Math.sin(i/17);const audio=new AudioData({format:'f32',sampleRate:48000,numberOfFrames:4800,numberOfChannels:1,timestamp:0,data});enc.encode(audio);audio.close();await enc.flush();enc.close();
  let frames=0;const dec=new AudioDecoder({output:a=>{frames+=a.numberOfFrames;if(a.numberOfChannels!==1||a.sampleRate!==48000)errors.push('Wrong audio format');a.close()},error:e=>errors.push(String(e))});dec.configure(decoderConfig||config);for(const chunk of chunks)dec.decode(new EncodedAudioChunk(chunk));await dec.flush();dec.close();if(errors.length||!frames)throw Error(JSON.stringify({errors,frames}));return {chunks:chunks.length,decodedFrames:frames,sampleRate:48000};
 });
 await test('avc_mse_decode_playback',async()=>{
  const type='video/mp4; codecs="avc1.42c01e"';if(!MediaSource.isTypeSupported(type))throw Error('AVC MSE unsupported');
  const bytes=await (await fetch('/media-avc-fragmented.mp4')).arrayBuffer(),media=new MediaSource(),url=URL.createObjectURL(media),v=document.createElement('video');v.muted=true;
  try{await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('MSE open timeout')),8000);media.onsourceopen=()=>{clearTimeout(timer);resolve()};v.src=url});
   await new Promise((resolve,reject)=>{const buffer=media.addSourceBuffer(type);buffer.onupdateend=()=>resolve();buffer.onerror=()=>reject(Error('MSE append failed'));buffer.appendBuffer(bytes)});media.endOfStream();
   let firstTime;await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('AVC playback timeout')),8000);const frame=(time,meta)=>{if(firstTime===undefined)firstTime=meta.mediaTime;if(meta.mediaTime-firstTime>=.19){clearTimeout(timer);v.pause();resolve()}else v.requestVideoFrameCallback(frame)};v.requestVideoFrameCallback(frame);v.play().catch(reject)});
   const f=new VideoFrame(v,{timestamp:0});try{return {width:v.videoWidth,height:v.videoHeight,playedSeconds:v.currentTime,decodedHash:await digest(await pixels(f))}}finally{f.close()}
  }finally{v.pause();v.removeAttribute('src');v.load();URL.revokeObjectURL(url)}
 });
 await test('aac_actual_decode',async()=>{
  const bytes=await (await fetch('/media-aac.m4a')).arrayBuffer(),context=new OfflineAudioContext(1,48000,48000),audio=await context.decodeAudioData(bytes);
  const pcm=audio.getChannelData(0);if(audio.numberOfChannels!==1||audio.sampleRate!==48000||audio.duration<.9||audio.duration>1.1||!pcm.some(v=>Math.abs(v)>.01)||!pcm.every(Number.isFinite))throw Error('AAC decode invalid');
  return {channels:audio.numberOfChannels,sampleRate:audio.sampleRate,duration:audio.duration,finite:true};
 });
 return {checks,details,passed:Object.values(checks).every(Boolean),paid_model_calls:0};
}
try{
 await call('Page.navigate',{url:'http://127.0.0.1:18858/'});
 let ready=false;for(let i=0;i<100;i++){const r=await call('Runtime.evaluate',{expression:"location.origin==='http://127.0.0.1:18858'&&document.readyState==='complete'",returnByValue:true});if(r.result.value){ready=true;break}await new Promise(r=>setTimeout(r,100))}assert(ready);
 const control=process.argv[3]==='control';
 if(control||process.argv[3]==='extended'){
  // The fake capture UI flag alone does not grant device-label enumeration.
  // This grants only this loopback origin in the caller-owned test profile.
  for(const name of ['camera','microphone'])await call('Browser.setPermission',{permission:{name},setting:'granted',origin:'http://127.0.0.1:18858'});
 }
 const fn=control?hardwarePolicyControl:probe;
 const options={protectedContext:process.argv[4]?.endsWith('_balanced')||process.argv[4]?.endsWith('_developer')};
 const result=await call('Runtime.evaluate',{expression:`(${fn.toString()})(${JSON.stringify(options)})`,awaitPromise:true,returnByValue:true,userGesture:true});assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));
 const value=result.result.value;
 if(process.argv[3]==='extended'){
  const labels=await call('Runtime.evaluate',{expression:`(${deviceLabelProbe.toString()})()`,awaitPromise:true,returnByValue:true,userGesture:true});
  assert(!labels.exceptionDetails,JSON.stringify(labels.exceptionDetails));
  Object.assign(value.checks,labels.result.value.checks);Object.assign(value.details,labels.result.value.details);
  const extra=await call('Runtime.evaluate',{expression:`(${extendedMediaProbe.toString()})()`,awaitPromise:true,returnByValue:true,userGesture:true});
  assert(!extra.exceptionDetails,JSON.stringify(extra.exceptionDetails));
  Object.assign(value.checks,extra.result.value.checks);Object.assign(value.details,extra.result.value.details);
  const policy=await call('Runtime.evaluate',{expression:`(${gpuPolicyProbe.toString()})(${JSON.stringify({software:process.argv[4]==='swiftshader'})})`,awaitPromise:true,returnByValue:true,userGesture:true});
  assert(!policy.exceptionDetails,JSON.stringify(policy.exceptionDetails));
  Object.assign(value.checks,policy.result.value.checks);Object.assign(value.details,policy.result.value.details);
  value.passed=Object.values(value.checks).every(v=>v===true);
 }
 console.log(JSON.stringify(value,null,2));
}finally{ws.close()}
