// Actual HTMLMediaElement -> WebAudio -> analyser -> zero-gain output.
(async()=>{
 const rows=[];let closedContexts=0;
 function wav(rate){
  const frames=32768,b=new ArrayBuffer(44+frames*4),v=new DataView(b),word=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i))};
  word(0,'RIFF');v.setUint32(4,b.byteLength-8,true);word(8,'WAVE');word(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,2,true);v.setUint32(24,rate,true);v.setUint32(28,rate*4,true);v.setUint16(32,4,true);v.setUint16(34,16,true);word(36,'data');v.setUint32(40,frames*4,true);
  for(let i=0;i<frames;i++)for(let ch=0;ch<2;ch++)v.setInt16(44+i*4+ch*2,Math.round((ch?.125:.25)*32768*Math.sin(2*Math.PI*i/128)),true);
  return b;
 }
 const timeout=async(promise,label)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' timeout')),5000)})])}finally{clearTimeout(timer)}};
 for(const sourceRate of [8000,22050,44100,96000])for(const destRate of [44100,48000])for(let repeat=0;repeat<2;repeat++){
  const context=new AudioContext({sampleRate:destRate,latencyHint:'interactive'}),audio=new Audio(),url=URL.createObjectURL(new Blob([wav(sourceRate)],{type:'audio/wav'}));
  let source,analyser,gain;
  try{
   audio.src=url;audio.loop=true;audio.preload='auto';source=context.createMediaElementSource(audio);analyser=context.createAnalyser();analyser.fftSize=2048;
   gain=context.createGain();gain.gain.value=0;source.connect(analyser).connect(gain).connect(context.destination);
   await timeout(context.resume(),'resume');await timeout(audio.play(),'play');await new Promise(ok=>setTimeout(ok,240));
   const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);
   const crossings=[];for(let i=1;i<data.length;i++)if(data[i-1]<=0&&data[i]>0)crossings.push(i-1-data[i-1]/(data[i]-data[i-1]));
   const observedFrequency=crossings.length>1?(crossings.length-1)*context.sampleRate/(crossings.at(-1)-crossings[0]):null;
   rows.push({float32Base64:btoa(String.fromCharCode(...new Uint8Array(data.buffer))),sourceRate,destRate,repeat,contextRate:context.sampleRate,contextState:context.state,
    playbackTime:audio.currentTime,paused:audio.paused,readyState:audio.readyState,mediaError:audio.error?.code??null,
    outputGain:gain.gain.value,finite:data.every(Number.isFinite),peak:Math.max(...data.map(Math.abs)),
    rms:Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length),crossings:crossings.length,observedFrequency,
    expectedFrequency:sourceRate/128,hadUserActivation:navigator.userActivation.hasBeenActive});
  }finally{
   audio.pause();audio.removeAttribute('src');audio.load();source?.disconnect();analyser?.disconnect();gain?.disconnect();await context.close();closedContexts++;URL.revokeObjectURL(url);
  }
 }
 return {platform:navigator.platform,rows,closedContexts,outputMutedByGraph:true,real_microphone_requested:false};
})()
