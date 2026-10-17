// HRTF impulse and linear-superposition captures; never connected to hardware.
(async()=>{
 const rows=[],frames=4096;
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{let s='';const b=new Uint8Array(a.buffer);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 for(const rate of [22050,44100,96000])for(const direction of ['front','left','right'])for(const signal of ['impulse','pair'])for(let repeat=0;repeat<2;repeat++){
  const context=new OfflineAudioContext(2,frames,rate),source=context.createBufferSource(),buffer=context.createBuffer(1,frames,rate);
  buffer.getChannelData(0)[0]=1;if(signal==='pair')buffer.getChannelData(0)[1024]=-.5;
  source.buffer=buffer;const panner=context.createPanner();panner.panningModel='HRTF';panner.rolloffFactor=0;
  panner.positionX.value=direction==='left'?-1:direction==='right'?1:0;panner.positionY.value=0;panner.positionZ.value=-1;
  source.connect(panner).connect(context.destination);source.start();let eventBuffer;context.oncomplete=e=>eventBuffer=e.renderedBuffer;
  const rendered=await context.startRendering(),channels=[];
  for(let ch=0;ch<2;ch++){const data=rendered.getChannelData(ch).slice(),copy=new Float32Array(frames);rendered.copyFromChannel(copy,ch);channels.push({float32Base64:encode(data),sha256:await hash(data),copySha256:await hash(copy)})}
  rows.push({rate,direction,signal,repeat,frames,bufferRate:rendered.sampleRate,length:rendered.length,channelCount:rendered.numberOfChannels,eventBufferIdentity:eventBuffer===rendered,model:panner.panningModel,position:[panner.positionX.value,panner.positionY.value,panner.positionZ.value],rolloff:panner.rolloffFactor,channels});
  source.disconnect();panner.disconnect();
 }
 return {rows,offlineOnly:true,microphoneRequested:false};
})()
