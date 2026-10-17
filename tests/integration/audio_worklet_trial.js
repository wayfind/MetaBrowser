// Real AudioWorklet processing, parameter transport, filter and spatial graphs.
(async()=>{
 const rows=[],frames=2048;
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{let s='';const b=new Uint8Array(a.buffer);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 const module=`class OwnedProcessor extends AudioWorkletProcessor {
  static get parameterDescriptors(){return [{name:'gain',defaultValue:1,automationRate:'a-rate'}]}
  process(inputs,outputs,parameters){
   const output=outputs[0][0],input=inputs[0][0],gain=parameters.gain;
   for(let i=0;i<output.length;i++)output[i]=(input?.[i]??0)*gain[gain.length===1?0:i];
   this.port.postMessage({frame:currentFrame,time:currentTime,rate:sampleRate,frames:output.length,inputChannels:inputs[0].length,gainValues:gain.length,gainFirst:gain[0],gainLast:gain[gain.length-1]});return true;
  }
 };registerProcessor('owned-processor',OwnedProcessor);`;
 for(const rate of [22050,44100,96000])for(const kind of ['identity','gain-a-rate','biquad-detune','spatial'])for(let repeat=0;repeat<2;repeat++){
  const context=new OfflineAudioContext(2,frames,rate),url=URL.createObjectURL(new Blob([module],{type:'application/javascript'}));
  try{await context.audioWorklet.addModule(url)}finally{URL.revokeObjectURL(url)}
  const processor=new AudioWorkletNode(context,'owned-processor',{outputChannelCount:[1],channelCount:1,channelCountMode:'explicit'}),messages=[];
  processor.port.onmessage=e=>messages.push(e.data);
  const buffer=context.createBuffer(1,frames,rate),input=buffer.getChannelData(0);
  for(let i=0;i<frames;i++)input[i]=(((i*17)%257)-128)/640;
  const source=context.createBufferSource();source.buffer=buffer;source.connect(processor);let tail=processor,settings=null;
  if(kind==='gain-a-rate'){
   const control=context.createBufferSource(),b=context.createBuffer(1,frames,rate),d=b.getChannelData(0);
   for(let i=0;i<frames;i++)d[i]=.25+(i%13)/32;
   control.buffer=b;processor.parameters.get('gain').value=0;control.connect(processor.parameters.get('gain'));control.start();
  }else if(kind==='biquad-detune'){
   const filter=context.createBiquadFilter();filter.type='allpass';filter.frequency.value=rate/32;filter.detune.value=37;filter.Q.value=1;
   processor.connect(filter);tail=filter;settings={type:filter.type,frequency:filter.frequency.value,detune:filter.detune.value,q:filter.Q.value};
  }else if(kind==='spatial'){
   const panner=context.createPanner();panner.panningModel='equalpower';panner.rolloffFactor=0;panner.positionX.value=-1;panner.positionY.value=0;panner.positionZ.value=-1;
   processor.connect(panner);tail=panner;settings={model:panner.panningModel,rolloff:panner.rolloffFactor,position:[panner.positionX.value,panner.positionY.value,panner.positionZ.value]};
  }
  tail.connect(context.destination);source.start();let eventBuffer;context.oncomplete=e=>{eventBuffer=e.renderedBuffer};const rendered=await context.startRendering();
  for(let n=0;messages.length<frames/128 && n<100;n++)await new Promise(r=>setTimeout(r,5));
  const channels=[];for(let ch=0;ch<2;ch++){const data=rendered.getChannelData(ch).slice(),copy=new Float32Array(frames);rendered.copyFromChannel(copy,ch);channels.push({sha256:await hash(data),copySha256:await hash(copy),float32Base64:encode(data)})}
  rows.push({rate,kind,repeat,frames,length:rendered.length,bufferRate:rendered.sampleRate,channelCount:rendered.numberOfChannels,eventBufferIdentity:eventBuffer===rendered,messages,settings,channels});
  processor.port.close();source.disconnect();processor.disconnect();if(tail!==processor)tail.disconnect();
 }
 return {rows,platform:navigator.platform,offlineOnly:true,microphoneRequested:false};
})()
