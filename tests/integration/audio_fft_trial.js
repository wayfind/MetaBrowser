// FFT pipelines, independent direct-DFT/impulse/Fourier-series references.
(async()=>{
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const rows=[],rate=44100;
 const input=i=>Math.fround((((i*17)%257)-128)/137);
 const badContext=new OfflineAudioContext(1,128,rate),bad=badContext.createAnalyser(),invalid=[];
 for(const [label,value] of [['zero',0],['below',16],['31',31],['33',33],['above',32769],['65536',65536],['negative',-1],['fraction',1.5],['nan',NaN],['infinity',Infinity]]){
  let error=null;try{bad.fftSize=value}catch(e){error=e.name}
  invalid.push({label,error,retained:bad.fftSize});
 }
 for(let size=32;size<=32768;size*=2)for(let repeat=0;repeat<2;repeat++){
  const frames=Math.max(4096,size*2),context=new OfflineAudioContext(1,frames,rate);
  const source=context.createBufferSource(),buffer=context.createBuffer(1,frames,rate),samples=buffer.getChannelData(0);
  for(let i=0;i<frames;i++)samples[i]=input(i);
  const analyser=context.createAnalyser();analyser.fftSize=size;analyser.smoothingTimeConstant=0;
  analyser.minDecibels=-140;analyser.maxDecibels=0;
  source.buffer=buffer;source.connect(analyser).connect(context.destination);source.start();
  const rendered=await context.startRendering();
  const time=new Float32Array(size),freq=new Float32Array(size/2),bytes=new Uint8Array(size/2);
  analyser.getFloatTimeDomainData(time);analyser.getFloatFrequencyData(freq);analyser.getByteFrequencyData(bytes);
  const expected=Float32Array.from({length:size},(_,i)=>input(frames-size+i));
  const windowed=expected.map((x,i)=>Math.fround(x*Math.fround(.42-.5*Math.cos(2*Math.PI*i/size)+.08*Math.cos(4*Math.PI*i/size))));
  const picks=[];
  for(const bin of [0,1,7,size/8,size/4,size/2-1]){
   let real=0,imag=0;
   for(let i=0;i<size;i++){const angle=2*Math.PI*bin*i/size;real+=windowed[i]*Math.cos(angle);imag-=windowed[i]*Math.sin(angle)}
   const db=20*Math.log10(Math.hypot(real,imag)/size);
   picks.push({bin,expected:db,observed:freq[bin],error:Math.abs(freq[bin]-db)});
  }
  const maxByteError=Math.max(...bytes.map((x,i)=>Math.abs(x-Math.floor(Math.max(0,Math.min(255,255*(freq[i]+140)/140))))));
  rows.push({kind:'analyser',size,repeat,frames,bufferLength:rendered.length,rate:rendered.sampleRate,
   binCount:analyser.frequencyBinCount,timeHash:await hash(time),frequencyHash:await hash(freq),
   byteHash:await hash(bytes),timeError:Math.max(...time.map((x,i)=>Math.abs(x-expected[i]))),
   finiteFrequency:freq.every(Number.isFinite),
   nanFrequencyBins:freq.reduce((n,x)=>n+Number.isNaN(x),0),
   positiveInfiniteFrequencyBins:freq.reduce((n,x)=>n+(x===Infinity),0),
   zeroMagnitudeBins:freq.reduce((n,x)=>n+(x===-Infinity),0),maxByteError,picks});
 }
 for(const sampleRate of [44100,48000])for(const kind of ['long-convolution','periodic-wave'])for(let repeat=0;repeat<2;repeat++){
  const frames=8192,context=new OfflineAudioContext(1,frames,sampleRate);let expected;
  if(kind==='long-convolution'){
   const source=context.createBufferSource(),buffer=context.createBuffer(1,frames,sampleRate),samples=buffer.getChannelData(0);
   for(let i=0;i<frames;i++)samples[i]=input(i);
   const convolver=context.createConvolver(),impulse=context.createBuffer(1,4096,sampleRate),kernel=impulse.getChannelData(0);
   const positions=[0,127,128,129,255,256,511,512,1023,2047,2048,4095];
   for(let j=0;j<positions.length;j++)kernel[positions[j]]=Math.fround((j%2?-1:1)/(3+j*7));
   expected=Float32Array.from({length:frames},(_,i)=>positions.reduce((sum,p)=>sum+(i>=p?samples[i-p]*kernel[p]:0),0));
   convolver.normalize=false;convolver.buffer=impulse;source.buffer=buffer;
   source.connect(convolver).connect(context.destination);source.start();
  }else{
   const real=new Float32Array(32),imag=new Float32Array(32);real[1]=.5;imag[3]=.25;real[17]=-.125;
   const wave=context.createPeriodicWave(real,imag,{disableNormalization:true}),osc=context.createOscillator();
   osc.setPeriodicWave(wave);osc.frequency.value=sampleRate/1024;osc.connect(context.destination);osc.start();
   expected=Float32Array.from({length:frames},(_,i)=>.5*Math.cos(2*Math.PI*i/1024)+.25*Math.sin(6*Math.PI*i/1024)-.125*Math.cos(34*Math.PI*i/1024));
  }
  let eventBuffer;context.oncomplete=e=>{eventBuffer=e.renderedBuffer};
  const rendered=await context.startRendering(),data=rendered.getChannelData(0),copied=new Float32Array(frames);rendered.copyFromChannel(copied,0);
  rows.push({kind,rate:sampleRate,repeat,frames,bufferLength:rendered.length,bufferRate:rendered.sampleRate,
   eventBufferIdentity:rendered===eventBuffer,sha256:await hash(data),copySha256:await hash(copied),
   finite:data.every(Number.isFinite),nonzero:data.reduce((s,x)=>s+(x!==0),0),peak:Math.max(...data.map(Math.abs)),
   maxError:Math.max(...data.map((x,i)=>Math.abs(x-expected[i]))),samples:Array.from(data.slice(450,470))});
 }
 return {platform:navigator.platform,rows,invalid};
})()
