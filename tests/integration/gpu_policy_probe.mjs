// Runs only in a caller-owned loopback fixture, never the normal user profile.
export async function gpuPolicyProbe({software=false}={}){
 const checks={},details={};
 const demand=(value,message)=>{if(!value)throw Error(message)};
 async function test(name,fn){await fetch('/progress',{method:'POST',body:JSON.stringify({name,phase:'start',checks}),signal:AbortSignal.timeout(2000)});try{details[name]=await fn();checks[name]=true}catch(error){details[name]={error:String(error)};checks[name]=false}}
 const blocked=['timestamp-query','subgroups','chromium-experimental-timestamp-query-inside-passes','chromium-experimental-subgroup-matrix'];
 await test('gpu_optional_privacy',async()=>{
  const adapter=await navigator.gpu.requestAdapter();demand(adapter,'No adapter');
  const features=[...adapter.features],visible=blocked.filter(f=>features.includes(f)||adapter.features.has(f));
  demand(!visible.length,'Privacy-sensitive optional features visible: '+visible.join(','));
  demand(adapter.info.subgroupMinSize===0&&adapter.info.subgroupMaxSize===0,'Subgroup widths disclosed');
  for(const feature of blocked){const fresh=await navigator.gpu.requestAdapter();let rejected=false;try{const device=await fresh.requestDevice({requiredFeatures:[feature]});device.destroy()}catch(error){rejected=error.name==='TypeError'}demand(rejected,'Hidden feature request succeeded: '+feature)}
  const fresh=await navigator.gpu.requestAdapter(),device=await fresh.requestDevice();
  try{demand(device.adapterInfo.subgroupMinSize===0&&device.adapterInfo.subgroupMaxSize===0,'Device reopened subgroup info');demand(blocked.every(f=>!device.features.has(f)),'Device reopened features');device.pushErrorScope('validation');let rejected=false;try{device.createQuerySet({type:'timestamp',count:2})}catch(error){rejected=error.name==='TypeError'}const validation=await device.popErrorScope();demand(rejected||validation,'Timestamp query worked without feature')}finally{device.destroy()}
  const code=`onmessage=async()=>{try{const a=await navigator.gpu.requestAdapter();postMessage({features:[...a.features],min:a.info.subgroupMinSize,max:a.info.subgroupMaxSize})}catch(e){postMessage({error:String(e)})}}`;
  const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'})),worker=new Worker(url);let timer;
  try{const value=await new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(Error('GPU Worker timeout')),10000);worker.onmessage=e=>resolve(e.data);worker.onerror=e=>reject(Error(e.message));worker.postMessage(0)});demand(!value.error&&blocked.every(f=>!value.features.includes(f))&&value.min===0&&value.max===0,'Worker reopened optional features/info')}finally{clearTimeout(timer);worker.terminate();URL.revokeObjectURL(url)}
  return {adapterAndDevice:true,worker:true,requiredFeaturesRejected:true,timestampQueryValidation:true,subgroupWidthsHidden:true,blocked};
 });
 await test('gpu_limit_negotiation',async()=>{
  const adapter=await navigator.gpu.requestAdapter();demand(adapter,'No adapter');
  const maximums=['maxTextureDimension2D','maxBufferSize','maxStorageBufferBindingSize','maxComputeWorkgroupStorageSize','maxComputeInvocationsPerWorkgroup'];
  const tested=[];
  for(const name of maximums){const limit=adapter.limits[name];demand(Number.isSafeInteger(limit)&&limit>0,'Invalid published limit: '+name);const fresh=await navigator.gpu.requestAdapter();let rejected=false;try{const device=await fresh.requestDevice({requiredLimits:{[name]:limit+1}});device.destroy()}catch(error){rejected=error.name==='OperationError'}demand(rejected,'Required limit bypassed published maximum: '+name);tested.push(name)}
  for(const name of ['minUniformBufferOffsetAlignment','minStorageBufferOffsetAlignment']){const limit=adapter.limits[name];demand(Number.isSafeInteger(limit)&&limit>0,'Invalid alignment');if(limit>1){const fresh=await navigator.gpu.requestAdapter();let rejected=false;try{const device=await fresh.requestDevice({requiredLimits:{[name]:limit/2}});device.destroy()}catch(error){rejected=error.name==='OperationError'}demand(rejected,'Required alignment bypassed published limit: '+name);tested.push(name)}}
  const fresh=await navigator.gpu.requestAdapter(),limit=fresh.limits.maxTextureDimension2D,device=await fresh.requestDevice({requiredLimits:{maxTextureDimension2D:limit}});
  try{demand(device.limits.maxTextureDimension2D===limit,'Valid published limit not honored')}finally{device.destroy()}
  return {excessiveRequestsRejected:tested,validRequestHonored:true};
 });
 await test('gpu_codec_capabilities',async()=>{
  const decode={codec:'avc1.42c01e',codedWidth:160,codedHeight:96};
  const encode={codec:'avc1.42001e',width:160,height:96,bitrate:100000,framerate:10};
  const hardwareDecode=await VideoDecoder.isConfigSupported({...decode,hardwareAcceleration:'prefer-hardware'});
  const hardwareEncode=await VideoEncoder.isConfigSupported({...encode,hardwareAcceleration:'prefer-hardware'});
  const softwareDecode=await VideoDecoder.isConfigSupported({...decode,hardwareAcceleration:'prefer-software'});
  demand(softwareDecode.supported===true,'Real software AVC decoder unavailable');
  const capabilities=await navigator.mediaCapabilities.decodingInfo({type:'media-source',video:{contentType:'video/mp4; codecs="avc1.42c01e"',width:160,height:96,bitrate:100000,framerate:10}});
  demand(capabilities.supported===true,'AVC MSE capability unavailable');
  if(software){demand(hardwareDecode.supported===false,'Software profile reopened hardware decoder');demand(hardwareEncode.supported===false,'Software profile reopened hardware encoder');demand(capabilities.powerEfficient===false,'Software profile advertises hardware-efficient decode')}
  return {softwareProfile:software,softwareAVCDecode:true,hardwareDecode:hardwareDecode.supported,hardwareEncode:hardwareEncode.supported,powerEfficient:capabilities.powerEfficient,actualMSEPlaybackCoveredBy:'avc_mse_decode_playback'};
 });
 return {checks,details};
}
