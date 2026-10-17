// Actual k-rate, a-rate frequency and a-rate detune paths; independent sine reference.
(async()=>{
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const rows=[],frames=4096;
 for(const rate of [22050,44100,96000])for(const mode of ['constant','frequency-a-rate','detune-a-rate'])
 for(const variant of ['zero','low','positive','negative','octave','fractional'])for(let repeat=0;repeat<2;repeat++){
  const ctx=new OfflineAudioContext(1,frames,rate),osc=ctx.createOscillator();osc.type='sine';
  const base=variant==='zero'?0:variant==='low'?1:rate/256*(variant==='negative'?-1:1);
  const detune=variant==='octave'?1200:variant==='fractional'?37:0;
  let frequencies=new Float32Array(frames).fill(base),detunes=new Float32Array(frames).fill(detune);
  function control(param,values){const s=ctx.createBufferSource(),b=ctx.createBuffer(1,frames,rate);b.copyToChannel(values,0);s.buffer=b;param.value=0;s.connect(param);s.start()}
  if(mode==='frequency-a-rate'){
   frequencies=Float32Array.from({length:frames},(_,i)=>base*(1+(i%17)/32));control(osc.frequency,frequencies);osc.detune.value=detune;
  }else if(mode==='detune-a-rate'){
   detunes=Float32Array.from({length:frames},(_,i)=>detune+(i%3-1)*1200);control(osc.detune,detunes);osc.frequency.value=base;
  }else{osc.frequency.value=base;osc.detune.value=detune}
  osc.connect(ctx.destination);osc.start();let eventBuffer;ctx.oncomplete=e=>{eventBuffer=e.renderedBuffer};
  const rendered=await ctx.startRendering(),data=rendered.getChannelData(0),copy=new Float32Array(frames);rendered.copyFromChannel(copy,0);
  // Non-integer detune has explicitly bounded float conversion error; exact octaves separately checked.
  let phase=0,maxError=0,rmsError=0;
  for(let i=0;i<frames;i++){
   const error=Math.abs(data[i]-Math.sin(2*Math.PI*phase));maxError=Math.max(maxError,error);rmsError+=error*error;
   phase+=frequencies[i]*Math.pow(2,detunes[i]/1200)/rate;phase-=Math.floor(phase);
  }
  rows.push({rate,mode,variant,repeat,frames,bufferLength:rendered.length,bufferRate:rendered.sampleRate,
   sha256:await hash(data),copySha256:await hash(copy),eventBufferIdentity:eventBuffer===rendered,
   finite:data.every(Number.isFinite),nonzero:data.reduce((n,x)=>n+(x!==0),0),maxError,rmsError:Math.sqrt(rmsError/frames),peak:Math.max(...data.map(Math.abs))});
 }
 return {platform:navigator.platform,rows};
})()
