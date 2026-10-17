// All eight real Biquad types, fixed and scheduled coefficient changes.
(async()=>{
 const rows=[],frames=4096,changeFrame=2048;
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{let s='';const b=new Uint8Array(a.buffer);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 for(const rate of [22050,44100,96000])for(const type of ['lowpass','highpass','bandpass','lowshelf','highshelf','peaking','notch','allpass'])for(const automation of ['fixed','step'])for(let repeat=0;repeat<2;repeat++){
  const context=new OfflineAudioContext(1,frames,rate),filter=context.createBiquadFilter();filter.type=type;
  filter.frequency.value=rate/32;filter.detune.value=37;filter.Q.value=1;filter.gain.value=6;
  const frequencies=new Float32Array([0,rate/128,rate/32,rate/8,rate/3,rate/2,-1,rate]),magnitude=new Float32Array(8),phase=new Float32Array(8);
  filter.getFrequencyResponse(frequencies,magnitude,phase);
  const initial={frequency:filter.frequency.value,detune:filter.detune.value,q:filter.Q.value,gain:filter.gain.value};
  if(automation==='step'){
   const at=changeFrame/rate;
   filter.frequency.setValueAtTime(rate/16,at);filter.detune.setValueAtTime(-19,at);filter.Q.setValueAtTime(2,at);filter.gain.setValueAtTime(-3,at);
  }
  const input=context.createBuffer(1,frames,rate),data=input.getChannelData(0);
  for(let i=0;i<frames;i++)data[i]=(((i*17)%257)-128)/640;
  const source=context.createBufferSource();source.buffer=input;source.connect(filter);filter.connect(context.destination);source.start();
  let eventBuffer;context.oncomplete=e=>eventBuffer=e.renderedBuffer;
  const rendered=await context.startRendering(),a=rendered.getChannelData(0).slice(),copy=new Float32Array(frames);rendered.copyFromChannel(copy,0);
  rows.push({rate,type,automation,repeat,frames,changeFrame,initial,length:rendered.length,bufferRate:rendered.sampleRate,eventBufferIdentity:eventBuffer===rendered,
   response:{frequencies:Array.from(frequencies),magnitude:Array.from(magnitude),phase:Array.from(phase),magnitudeFloat32Base64:encode(magnitude),phaseFloat32Base64:encode(phase)},
   channels:[{sha256:await hash(a),copySha256:await hash(copy),float32Base64:encode(a)}]});
  source.disconnect();filter.disconnect();
 }
 return {rows,offlineOnly:true,microphoneRequested:false};
})()
