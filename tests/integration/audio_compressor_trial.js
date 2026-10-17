// Functional compressor invariants: lookahead silence and shared stereo gain.
// ratio=1 still has detector startup; ideal delayed signal error is diagnostic only.
(async()=>{
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const rows=[],invalid=[],frames=8192;
 const ctx0=new OfflineAudioContext(2,128,44100),bad=ctx0.createDynamicsCompressor();
 for(const name of ['threshold','knee','ratio','attack','release'])for(const [label,value] of [['nan',NaN],['infinity',Infinity],['negative-infinity',-Infinity]]){
  let error=null;try{bad[name].value=value}catch(e){error=e.name}invalid.push({name,label,error});
 }
 for(const rate of [8000,44100,96000])for(const setting of ['bypass','default','hard','slow','automated'])
 for(const signal of ['silence','dc','ramp','pulses','noise'])for(let repeat=0;repeat<2;repeat++){
  const ctx=new OfflineAudioContext(2,frames,rate),source=ctx.createBufferSource(),buffer=ctx.createBuffer(2,frames,rate),left=buffer.getChannelData(0),right=buffer.getChannelData(1);
  for(let i=0;i<frames;i++){
   let x=signal==='silence'?0:signal==='dc'?.7:signal==='ramp'?.9*i/(frames-1):signal==='pulses'?(i%1024<192?.85:.001):((((i*17)%257)-128)/151);
   left[i]=x;right[i]=Math.fround(left[i]*.25);
  }
  const comp=ctx.createDynamicsCompressor();
  if(setting==='bypass'){comp.ratio.value=1;comp.knee.value=0;comp.threshold.value=-24}
  if(setting==='hard'){comp.ratio.value=20;comp.knee.value=0;comp.threshold.value=-36;comp.attack.value=0;comp.release.value=.05}
  if(setting==='slow'){comp.ratio.value=4;comp.knee.value=40;comp.threshold.value=-18;comp.attack.value=.15;comp.release.value=.8}
  if(setting==='automated'){
   for(const [name,a,b] of [['threshold',-6,-36],['ratio',2,16],['knee',0,24],['attack',.05,.001],['release',.5,.03]]){
    comp[name].setValueAtTime(a,0);comp[name].setValueAtTime(b,frames/3/rate);comp[name].linearRampToValueAtTime(a,frames*.8/rate);
   }
  }
  source.buffer=buffer;source.connect(comp).connect(ctx.destination);source.start();
  let eventBuffer;ctx.oncomplete=e=>{eventBuffer=e.renderedBuffer};
  const rendered=await ctx.startRendering(),a=rendered.getChannelData(0),b=rendered.getChannelData(1),delay=Math.floor(Math.fround(Math.fround(.006)*rate));
  const channels=[];
  for(let ch=0;ch<2;ch++){
   const data=rendered.getChannelData(ch),copy=new Float32Array(frames);rendered.copyFromChannel(copy,ch);
   let idealDelayError=0;for(let i=0;i<frames;i++)idealDelayError=Math.max(idealDelayError,Math.abs(data[i]-(i<delay?0:(ch?right:left)[i-delay])));
   channels.push({sha256:await hash(data),copySha256:await hash(copy),finite:data.every(Number.isFinite),
    peak:Math.max(...data.map(Math.abs)),nonzero:data.reduce((n,x)=>n+(x!==0),0),
    prefixPeak:Math.max(...data.slice(0,delay).map(Math.abs)),idealDelayError:setting==='bypass'?idealDelayError:null,
    segments:Array.from({length:8},(_,s)=>data.slice(s*1024,(s+1)*1024).reduce((n,x)=>n+Math.abs(x),0)/1024)});
  }
  rows.push({rate,setting,signal,repeat,frames,delay,bufferLength:rendered.length,bufferRate:rendered.sampleRate,
   channelCount:rendered.numberOfChannels,eventBufferIdentity:eventBuffer===rendered,
   reduction:comp.reduction,linkedError:Math.max(...b.map((x,i)=>Math.abs(x-a[i]*.25))),channels});
 }
 return {platform:navigator.platform,rows,invalid};
})()
