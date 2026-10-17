// Owned capability/lifecycle probe. No input device access, graph output muted.
(async()=>{
 const rows=[],invalid=[];let closedContexts=0;
 const timeout=async(p)=>{let t;try{return await Promise.race([p,new Promise((_,no)=>{t=setTimeout(()=>no(Error('device lifecycle timeout')),5000)})])}finally{clearTimeout(t)}};
 for(const silent of [false,true])for(const hint of [-1,0,.1,1e300]){
  const options={latencyHint:hint};if(silent)options.sinkId={type:'none'};
  const context=new AudioContext(options);let oscillator,gain;
  try{
   const row={silent,requestedHint:hint,rate:context.sampleRate,maxChannelCount:context.destination.maxChannelCount,baseLatency:context.baseLatency};
   context.destination.channelCount=1;row.mono=context.destination.channelCount;
   context.destination.channelCount=2;row.stereo=context.destination.channelCount;
   try{context.destination.channelCount=3;row.excessChannels='accepted'}catch(e){row.excessChannels=e.name}
   oscillator=context.createOscillator();gain=context.createGain();gain.gain.value=0;oscillator.connect(gain).connect(context.destination);oscillator.start();
   await timeout(context.resume());await new Promise(r=>setTimeout(r,35));row.running=context.state;
   await timeout(context.suspend());const frozen=context.currentTime;await new Promise(r=>setTimeout(r,35));row.suspended=context.state;row.frozen=context.currentTime===frozen;
   await timeout(context.resume());row.resumed=context.state;row.outputGain=gain.gain.value;
   rows.push(row);
  }finally{oscillator?.stop();oscillator?.disconnect();gain?.disconnect();await timeout(context.close());closedContexts++;}
 }
 for(const value of [NaN,Infinity,-Infinity]){
  let context;try{context=new AudioContext({latencyHint:value});invalid.push({value:String(value),result:'accepted'})}catch(e){invalid.push({value:String(value),result:e.name})}finally{if(context){await timeout(context.close());closedContexts++;}}
 }
 return {rows,invalid,closedContexts,microphoneRequested:false,outputMutedByGraph:true};
})()
