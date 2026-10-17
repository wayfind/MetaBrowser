// Owned, browser-muted long lifecycle test crossing the 30s silence transition.
(async()=>{
 const context=new AudioContext(),oscillator=context.createOscillator(),gain=context.createGain(),analyser=context.createAnalyser();
 const rows=[];let timer;
 const timeout=async(p)=>{let t;try{return await Promise.race([p,new Promise((_,no)=>{t=setTimeout(()=>no(Error('long clock lifecycle timeout')),5000)})])}finally{clearTimeout(t)}};
 const snapshot=phase=>{const a=new Float32Array(1024);analyser.getFloatTimeDomainData(a);const t=context.getOutputTimestamp();rows.push({phase,state:context.state,currentTime:context.currentTime,contextTime:t.contextTime,performanceTime:t.performanceTime,performanceNow:performance.now(),baseLatency:context.baseLatency,outputLatency:context.outputLatency,rms:Math.sqrt(a.reduce((s,v)=>s+v*v,0)/a.length)})};
 try{
  analyser.fftSize=1024;gain.gain.value=0;oscillator.connect(gain).connect(analyser).connect(context.destination);oscillator.start();
  await timeout(context.resume());snapshot('start');
  for(let n=0;n<33;n++){await new Promise(r=>setTimeout(r,1000));snapshot('silent')}
  // The launcher MUST mute the owned browser. Nonzero graph output is needed
  // to make SilentSinkSuspender transition back to the real output path.
  gain.gain.value=.2;await new Promise(r=>setTimeout(r,150));snapshot('signal');
  await timeout(context.suspend());const time=context.currentTime;await new Promise(r=>setTimeout(r,50));const frozen=context.currentTime===time;
  await timeout(context.resume());await new Promise(r=>setTimeout(r,100));snapshot('resumed');
  return {rows,frozen,closedContexts:1,browserMuteRequired:true,microphoneRequested:false};
 }finally{oscillator.stop();oscillator.disconnect();gain.disconnect();analyser.disconnect();await timeout(context.close())}
})()
