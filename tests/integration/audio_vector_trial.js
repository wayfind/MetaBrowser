// Actual graph computation. No getters, graph outputs or samples are replaced.
(async()=>{
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(b=>b.toString(16).padStart(2,'0')).join('');
 const rows=[],frames=2048;
 for(const rate of [8000,44100,48000,96000])for(const kind of ['gain','mix','convolution','compressor'])for(let repeat=0;repeat<2;repeat++){
  const context=new OfflineAudioContext(2,frames,rate),inputs=[];
  function source(phase){
   const buffer=context.createBuffer(2,frames,rate);
   for(let ch=0;ch<2;ch++)for(let i=0;i<frames;i++)buffer.getChannelData(ch)[i]=(((i*17+phase+ch*13)%257)-128)/137;
   inputs.push([buffer.getChannelData(0).slice(),buffer.getChannelData(1).slice()]);
   const node=context.createBufferSource();node.buffer=buffer;return node;
  }
  const first=source(0);let expected=null;
  if(kind==='gain'){
   const gain=context.createGain();gain.gain.value=.5;first.connect(gain).connect(context.destination);first.start();
   expected=inputs[0].map(a=>a.map(x=>x*.5));
  }else if(kind==='mix'){
   const second=source(7),ga=context.createGain(),gb=context.createGain();ga.gain.value=.3;gb.gain.value=-.7;
   first.connect(ga).connect(context.destination);second.connect(gb).connect(context.destination);first.start();second.start();
   expected=inputs[0].map((a,ch)=>a.map((x,i)=>Math.fround(Math.fround(x*Math.fround(.3))+Math.fround(inputs[1][ch][i]*Math.fround(-.7)))));
  }else if(kind==='convolution'){
   const convolver=context.createConvolver(),impulse=context.createBuffer(1,128,rate);
   const kernel=impulse.getChannelData(0);for(let i=0;i<kernel.length;i++)kernel[i]=(((i*17)%31)-15)/503;
   convolver.normalize=false;convolver.buffer=impulse;
   first.connect(convolver).connect(context.destination);first.start();
   expected=inputs[0].map(a=>a.map((_,i)=>kernel.reduce((sum,v,j)=>sum+(i>=j?a[i-j]*v:0),0)));
  }else{
   // Oscillator construction exercises FFT-generated periodic waves as well;
   // this row intentionally does not pretend FFT is already portable.
   const osc=context.createOscillator(),compressor=context.createDynamicsCompressor();
   osc.type='triangle';osc.frequency.value=Math.min(rate/4,10000);osc.connect(compressor).connect(context.destination);osc.start();
  }
  let eventBuffer;context.oncomplete=e=>{eventBuffer=e.renderedBuffer};
  const buffer=await context.startRendering();
  const channels=[];
  for(let ch=0;ch<2;ch++){
   const data=buffer.getChannelData(ch).slice(),copy=new Float32Array(frames);buffer.copyFromChannel(copy,ch);
   channels.push({sha256:await hash(data),copySha256:await hash(copy),finite:data.every(Number.isFinite),
    maxError:expected?Math.max(...data.map((v,i)=>Math.abs(v-expected[ch][i]))):null,
    nonzero:data.reduce((n,v)=>n+(v!==0),0),samples:Array.from(data.slice(450,470)),
    peak:Math.max(...data.map(Math.abs))});
  }
  rows.push({rate,kind,repeat,frames,channelCount:buffer.numberOfChannels,duration:buffer.duration,
    bufferRate:buffer.sampleRate,eventBufferIdentity:buffer===eventBuffer,channels});
 }
 return {platform:navigator.platform,cores:navigator.hardwareConcurrency,memory:navigator.deviceMemory,
   ua:navigator.userAgent,rows};
})()
