// Owned default-device metadata trace. Synthetic signal; zero graph output; no capture permission.
(async()=>{
 const rows=[];let closedContexts=0;
 const timeout=async(p,label)=>{let timer;try{return await Promise.race([p,new Promise((_,no)=>{timer=setTimeout(()=>no(Error(label+' timeout')),5000)})])}finally{clearTimeout(timer)}};
 for(const rate of [null,44100,48000])for(const hint of [null,'interactive','balanced','playback',.1])for(let repeat=0;repeat<2;repeat++){
  const options={};if(rate!==null)options.sampleRate=rate;if(hint!==null)options.latencyHint=hint;
  const context=rate===null&&hint===null?new AudioContext():new AudioContext(options),osc=context.createOscillator(),analyser=context.createAnalyser(),gain=context.createGain();
  osc.frequency.value=440;analyser.fftSize=1024;gain.gain.value=0;osc.connect(analyser).connect(gain).connect(context.destination);
  const snapshot=()=>{const t=context.getOutputTimestamp();return {state:context.state,rate:context.sampleRate,baseLatency:context.baseLatency,outputLatency:context.outputLatency,currentTime:context.currentTime,contextTime:t.contextTime,performanceTime:t.performanceTime,performanceNow:performance.now()}};
  const row={requestedRate:rate,requestedHint:hint,repeat,options,initial:snapshot(),samples:[],outputGain:gain.gain.value};
  try{
   osc.start();await timeout(context.resume(),'resume');
   for(let n=0;n<3;n++){
    await new Promise(ok=>setTimeout(ok,60));const data=new Float32Array(1024);analyser.getFloatTimeDomainData(data);
    row.samples.push({...snapshot(),finite:data.every(Number.isFinite),rms:Math.sqrt(data.reduce((s,v)=>s+v*v,0)/1024)});
   }
   await timeout(context.suspend(),'suspend');row.suspended=snapshot();rows.push(row);
  }finally{
   osc.stop();osc.disconnect();analyser.disconnect();gain.disconnect();await timeout(context.close(),'close');row.closedState=context.state;closedContexts++;
  }
 }
 return {platform:navigator.platform,rows,closedContexts,syntheticSignalOnly:true,outputMutedByGraph:true,microphoneRequested:false};
})()
