// decodeAudioData PCM16 WAV exercises AudioBus -> media::SincResampler.
(async()=>{
 const hash=async a=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a.buffer??a))).map(x=>x.toString(16).padStart(2,'0')).join('');
 const encode=a=>{const bytes=new Uint8Array(a.buffer,a.byteOffset,a.byteLength);let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(binary)};
 const pairs=[[8000,44100],[44100,48000],[48000,44100],[96000,44100],[44100,96000],[22050,48000],[48000,48000],[8000,48000]],rows=[],invalid=[];
 const contexts=new Map(),ctx=rate=>{if(!contexts.has(rate))contexts.set(rate,new OfflineAudioContext(2,128,rate));return contexts.get(rate)};
 function wav(rate,frames,signal){
  const bytes=new ArrayBuffer(44+frames*4),v=new DataView(bytes),word=(offset,s)=>{for(let i=0;i<s.length;i++)v.setUint8(offset+i,s.charCodeAt(i))};
  word(0,'RIFF');v.setUint32(4,bytes.byteLength-8,true);word(8,'WAVE');word(12,'fmt ');v.setUint32(16,16,true);
  v.setUint16(20,1,true);v.setUint16(22,2,true);v.setUint32(24,rate,true);v.setUint32(28,rate*4,true);v.setUint16(32,4,true);v.setUint16(34,16,true);word(36,'data');v.setUint32(40,frames*4,true);
  for(let i=0;i<frames;i++)for(let ch=0;ch<2;ch++){
   const value=signal==='dc'?.25:signal==='sine'?.5*Math.sin(2*Math.PI*i/128):(i===Math.floor(frames/2)?.5:0);
   v.setInt16(44+i*4+ch*2,Math.round(value*(ch?-.5:1)*32768),true);
  }
  return bytes;
 }
 for(const [sourceRate,destRate] of pairs)for(const frames of [37,96,97,257,4097])for(const signal of ['dc','sine','impulse'])for(let repeat=0;repeat<2;repeat++){
  const bytes=wav(sourceRate,frames,signal),inputSha256=await hash(bytes);let callbackBuffer=null,errorCallback=null;
  const buffer=await ctx(destRate).decodeAudioData(bytes,b=>{callbackBuffer=b},e=>{errorCallback=e.name});
  const channels=[],guard=Math.ceil(32*destRate/sourceRate);
  for(let ch=0;ch<2;ch++){
   const data=buffer.getChannelData(ch),copy=new Float32Array(buffer.length);buffer.copyFromChannel(copy,ch);
   let peak=0,peakFrame=0,sum=0,referenceError=0,referenceSamples=0;
   for(let i=0;i<data.length;i++){
    sum+=data[i];if(Math.abs(data[i])>peak){peak=Math.abs(data[i]);peakFrame=i}
    if(signal!=='impulse'&&i>=guard&&i<data.length-guard){
     const value=signal==='dc'?.25:.5*Math.sin(2*Math.PI*i*sourceRate/destRate/128);
     referenceError=Math.max(referenceError,Math.abs(data[i]-value*(ch?-.5:1)));referenceSamples++;
    }
   }
   channels.push({float32Base64:encode(data),sha256:await hash(data),copySha256:await hash(copy),finite:data.every(Number.isFinite),
    peak,peakFrame,sum,referenceError:referenceSamples?referenceError:null,referenceSamples,
    nonzero:data.reduce((n,x)=>n+(x!==0),0)});
  }
  rows.push({sourceRate,destRate,frames,signal,repeat,inputSha256,inputDetached:bytes.byteLength===0,
   length:buffer.length,rate:buffer.sampleRate,channelCount:buffer.numberOfChannels,duration:buffer.duration,
   callbackBufferIdentity:callbackBuffer===buffer,errorCallback,channels});
 }
 for(const [label,bytes] of [['empty',new ArrayBuffer(0)],['junk',new Uint8Array([1,2,3,4]).buffer],['header-only',wav(44100,37,'dc').slice(0,12)]]){
  let error=null;try{await ctx(48000).decodeAudioData(bytes)}catch(e){error=e.name}invalid.push({label,error});
 }
 return {platform:navigator.platform,rows,invalid};
})()
