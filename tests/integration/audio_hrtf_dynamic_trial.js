// Moving source/listener and elevation, with dyadic input-scale controls.
(async()=>{
 const rows=[],frames=8192;
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{let s='';const b=new Uint8Array(a.buffer);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 for(const rate of [22050,44100,96000])for(const motion of ['static','azimuth','elevation','listener'])for(const scale of [1,.5])for(let repeat=0;repeat<2;repeat++){
  const ctx=new OfflineAudioContext(2,frames,rate),source=ctx.createBufferSource(),buffer=ctx.createBuffer(1,frames,rate),data=buffer.getChannelData(0);
  for(let i=0;i<frames;i++)data[i]=Math.fround((((i*17)%257)-128)/640)*scale;
  source.buffer=buffer;const p=ctx.createPanner();p.panningModel='HRTF';p.rolloffFactor=0;p.positionX.value=0;p.positionY.value=0;p.positionZ.value=-1;
  if(motion!=='static'){
   const param=motion==='azimuth'?p.positionX:motion==='elevation'?p.positionY:ctx.listener.positionX;
   const values=motion==='elevation'?[1,-1,0]:[-1,1,0];
   for(let n=0;n<3;n++)param.setValueAtTime(values[n],(2048*(n+1))/rate);
  }
  source.connect(p).connect(ctx.destination);source.start();let eventBuffer;ctx.oncomplete=e=>eventBuffer=e.renderedBuffer;
  const rendered=await ctx.startRendering(),channels=[];
  for(let ch=0;ch<2;ch++){const out=rendered.getChannelData(ch).slice(),copy=new Float32Array(frames);rendered.copyFromChannel(copy,ch);channels.push({float32Base64:encode(out),sha256:await hash(out),copySha256:await hash(copy)})}
  rows.push({rate,motion,scale,repeat,frames,length:rendered.length,bufferRate:rendered.sampleRate,channelCount:rendered.numberOfChannels,eventBufferIdentity:eventBuffer===rendered,model:p.panningModel,rolloff:p.rolloffFactor,channels});
  source.disconnect();p.disconnect();
 }
 return {rows,offlineOnly:true,microphoneRequested:false};
})()
