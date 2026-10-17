// Actual realtime Worklet flow through the public clock. Output gain is zero.
(async()=>{
 const rows=[];let closedContexts=0;
 const encode=a=>{let s='';const b=new Uint8Array(a.buffer);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const timeout=async(p)=>{let t;try{return await Promise.race([p,new Promise((_,no)=>{t=setTimeout(()=>no(Error('realtime Worklet timeout')),5000)})])}finally{clearTimeout(t)}};
 const module=`class OwnedRealtime extends AudioWorkletProcessor {
  static get parameterDescriptors(){return [{name:'gain',defaultValue:1,automationRate:'a-rate'}]}
  process(inputs,outputs,parameters){const input=inputs[0][0],output=outputs[0][0],gain=parameters.gain;
   for(let i=0;i<output.length;i++)output[i]=(input?.[i]??0)*gain[gain.length===1?0:i];
   this.port.postMessage({frame:currentFrame,time:currentTime,rate:sampleRate,frames:output.length});return true;}
 };registerProcessor('owned-realtime',OwnedRealtime);`;
 for(const requestedRate of [null,44100,96000])for(const mode of ['constant','gain-a-rate']){
  const context=requestedRate===null?new AudioContext():new AudioContext({sampleRate:requestedRate}),url=URL.createObjectURL(new Blob([module],{type:'application/javascript'}));
  const sources=[];let processor,analyser,mute;
  try{
   try{await context.audioWorklet.addModule(url)}finally{URL.revokeObjectURL(url)}
   const rate=context.sampleRate,messages=[];let processedMessages=0;
   processor=new AudioWorkletNode(context,'owned-realtime',{outputChannelCount:[1],channelCount:1,channelCountMode:'explicit'});
   processor.port.onmessage=e=>{processedMessages++;if(messages.length<64)messages.push(e.data)};
   analyser=context.createAnalyser();analyser.fftSize=2048;mute=context.createGain();mute.gain.value=0;processor.connect(analyser).connect(mute).connect(context.destination);
   const when=(Math.ceil(context.currentTime*rate/128)+32)*128/rate;
   const buffer=context.createBuffer(1,257,rate);for(let i=0;i<257;i++)buffer.getChannelData(0)[i]=((i*17)%257-128)/640;
   const source=context.createBufferSource();source.buffer=buffer;source.loop=true;source.connect(processor);source.start(when);sources.push(source);
   if(mode==='gain-a-rate'){
    const b=context.createBuffer(1,257,rate);for(let i=0;i<257;i++)b.getChannelData(0)[i]=.25+(i%13)/32;
    const control=context.createBufferSource();control.buffer=b;control.loop=true;processor.parameters.get('gain').value=0;control.connect(processor.parameters.get('gain'));control.start(when);sources.push(control);
   }
   await timeout(context.resume());await new Promise(r=>setTimeout(r,4096/rate*1000+250));
   const data=new Float32Array(2048);analyser.getFloatTimeDomainData(data);
   const before=context.currentTime;await timeout(context.suspend());const suspended=context.currentTime;await new Promise(r=>setTimeout(r,25));const frozen=context.currentTime===suspended;
   await timeout(context.resume());await new Promise(r=>setTimeout(r,30));
   rows.push({requestedRate,rate,mode,messages,processedMessages,frames:2048,float32Base64:encode(data),sha256:await hash(data),before,suspended,frozen,resumed:context.state,after:context.currentTime,outputGain:mute.gain.value});
  }finally{for(const source of sources){source.stop();source.disconnect()}processor?.port.close();processor?.disconnect();analyser?.disconnect();mute?.disconnect();await timeout(context.close());closedContexts++;}
 }
 return {rows,closedContexts,microphoneRequested:false,outputMutedByGraph:true};
})()
