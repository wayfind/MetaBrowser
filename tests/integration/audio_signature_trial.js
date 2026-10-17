// Exact original identity collector and original P8 audio graph configurations.
(async()=>{
 const rows=[];
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{const b=new Uint8Array(a.buffer);let s='';for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s)};
 for(const variant of ['identity-default','checklist-p8'])for(let repeat=0;repeat<3;repeat++){
  const frames=variant==='identity-default'?44100:5000,context=new OfflineAudioContext(1,frames,44100),osc=context.createOscillator(),compressor=context.createDynamicsCompressor();
  osc.type='triangle';osc.frequency.value=10000;
  if(variant==='checklist-p8'){compressor.threshold.value=-50;compressor.knee.value=40;compressor.ratio.value=12;compressor.attack.value=0;compressor.release.value=.25}
  const parameters=Object.fromEntries(['threshold','knee','ratio','attack','release'].map(n=>[n,compressor[n].value]));
  osc.connect(compressor);compressor.connect(context.destination);osc.start(0);
  let eventBuffer;context.oncomplete=e=>{eventBuffer=e.renderedBuffer};const buffer=await context.startRendering(),data=buffer.getChannelData(0).slice(),copy=new Float32Array(frames);buffer.copyFromChannel(copy,0);const data2=buffer.getChannelData(0).slice(),copy2=new Float32Array(frames);buffer.copyFromChannel(copy2,0);
  rows.push({variant,repeat,frames,rate:buffer.sampleRate,length:buffer.length,channelCount:buffer.numberOfChannels,duration:buffer.duration,parameters,
   oscillatorType:osc.type,frequency:osc.frequency.value,eventBufferIdentity:eventBuffer===buffer,finite:data.every(Number.isFinite),
   sha256:await hash(data),copySha256:await hash(copy),repeatGetSha256:await hash(data2),repeatCopySha256:await hash(copy2),float32Base64:encode(data),
   sample4500to4510:Array.from(data.slice(4500,4510)),sumAbsolute4500to4510:data.slice(4500,4510).reduce((s,v)=>s+Math.abs(v),0),
   sumAbsolute4500to5000:data.slice(4500,5000).reduce((s,v)=>s+Math.abs(v),0),peak:Math.max(...data.map(Math.abs)),nonzero:data.reduce((s,v)=>s+(v!==0),0)});
 }
 return {platform:navigator.platform,rows};
})()
