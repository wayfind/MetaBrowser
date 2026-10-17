(async()=>{
 const rows=[],frames=1024;
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>btoa(String.fromCharCode(...new Uint8Array(a.buffer)));
 for(const rate of [22050,44100,96000])for(const type of ['lowpass','highpass','bandpass','lowshelf','highshelf','peaking','notch','allpass'])for(const boundary of ['frequency-zero','frequency-nyquist','q-zero','gain-zero'])for(let repeat=0;repeat<2;repeat++){
  const context=new OfflineAudioContext(1,frames,rate),filter=context.createBiquadFilter();filter.type=type;
  filter.frequency.value=boundary==='frequency-zero'?0:boundary==='frequency-nyquist'?rate/2:rate/32;
  filter.detune.value=0;filter.Q.value=boundary==='q-zero'?0:1;filter.gain.value=boundary==='gain-zero'?0:6;
  const parameters=[filter.frequency.value,filter.detune.value,filter.Q.value,filter.gain.value];
  const input=context.createBuffer(1,frames,rate),data=input.getChannelData(0);
  for(let i=0;i<frames;i++)data[i]=(((i*17)%257)-128)/640;
  const source=context.createBufferSource();source.buffer=input;source.connect(filter);filter.connect(context.destination);source.start();
  let eventBuffer;context.oncomplete=e=>eventBuffer=e.renderedBuffer;
  const rendered=await context.startRendering(),dataOut=rendered.getChannelData(0).slice(),copy=new Float32Array(frames);rendered.copyFromChannel(copy,0);
  rows.push({rate,type,boundary,repeat,parameters,frames,length:rendered.length,bufferRate:rendered.sampleRate,eventBufferIdentity:eventBuffer===rendered,
   channels:[{sha256:await hash(dataOut),copySha256:await hash(copy),float32Base64:encode(dataOut)}]});
  source.disconnect();filter.disconnect();
 }
 return {rows,offlineOnly:true,microphoneRequested:false};
})()
