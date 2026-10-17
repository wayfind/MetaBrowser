// Only owned loopback fixtures; no user files or permissions.
async function ownedOpfsTrial(realm,kind,scenario){
 const digest=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');
 const name=`owned-opfs-${realm}-${kind}-${scenario}`;
 const bucket=await navigator.storageBuckets.open(name,{quota:scenario==='delete_inflight'?16*1024**2:2*1024**2});
 const directory=await bucket.getDirectory();
 const file=await directory.getFileHandle('canary.bin',{create:true});
 const initial=await file.createWritable();await initial.write(new Uint8Array(4096).fill(7));await initial.close();
 const writer=await file.createWritable();
 const makePayload=size=>{
  if(kind==='blob')return new Blob([new Uint8Array(size).fill(42)]);
  if(kind==='string')return 'x'.repeat(size);
  if(kind==='arraybuffer')return new Uint8Array(size).fill(42).buffer;
  if(kind==='offset_uint8'||kind==='dataview'){
   const bytes=new Uint8Array(size+64).fill(99);bytes.fill(42,32,32+size);
   return kind==='dataview'?new DataView(bytes.buffer,32,size):bytes.subarray(32,32+size);
  }
  if(kind==='uint8')return new Uint8Array(size).fill(42);
  throw Error('Unknown owned payload');
 };
 let result={realm,kind,scenario,origin:location.origin,secure:isSecureContext,
  actualGlobal:globalThis.constructor.name,actualLocation:location.href,
  topLevel:typeof document==='undefined'?null:parent===globalThis,
  moduleUrl:globalThis.ownedModuleUrl??null,
  serviceScope:globalThis.registration?.scope??null};
 // A successful small write proves that offsets/types are actually usable,
 // rather than treating any rejected payload as quota enforcement.
 const normal=await file.createWritable();await normal.write(makePayload(65536));await normal.close();
 const normalData=await(await file.getFile()).arrayBuffer();
 result.normal={bytes:normalData.byteLength,sha256:await digest(normalData)};
 const reset=await file.createWritable();await reset.write(new Uint8Array(4096).fill(7));await reset.close();
 const payload=makePayload(8*1024**2);
 result.payload={type:typeof payload==='string'?'string':payload.constructor.name,
  bytes:typeof payload==='string'?new TextEncoder().encode(payload).byteLength:payload.size??payload.byteLength,
  byteOffset:payload.byteOffset??0,backingBytes:payload.buffer?.byteLength??payload.byteLength??payload.size??null};
 try{
  if(scenario==='cancel'){
   await writer.write(new Uint8Array(4096).fill(42));await writer.abort('owned-cancel');
   result.cancelled=true;
  }else{
   let stage='write';
   const write=async()=>{try{await writer.write(payload);stage='close';await writer.close();return{completed:true};}catch(e){return{completed:false,error:e.name,message:e.message,stage}}};
   const work=write();
   if(scenario==='delete_inflight')await navigator.storageBuckets.delete(name);
   let timer;
   try{result.write=await Promise.race([work,new Promise((ok,no)=>{timer=setTimeout(()=>no(Error('Owned write did not settle')),10000)})]);}
   finally{clearTimeout(timer);}
   if(!result.write.completed)await writer.abort().catch(()=>{});
  }
  if(scenario!=='delete_inflight'){
   const data=await(await file.getFile()).arrayBuffer();
   result.retained={bytes:data.byteLength,sha256:await digest(data)};
  }
  await navigator.storageBuckets.delete(name);
  const recovered=await navigator.storageBuckets.open(name+'-recovered',{quota:2*1024**2});
  try{
   const dir=await recovered.getDirectory(),handle=await dir.getFileHandle('recovered.bin',{create:true});
   const stream=await handle.createWritable();await stream.write(new Uint8Array(4096).fill(21));await stream.close();
   const data=await(await handle.getFile()).arrayBuffer();result.recovered={bytes:data.byteLength,sha256:await digest(data)};
  }finally{await navigator.storageBuckets.delete(name+'-recovered');}
  result.completed=true;return result;
 }finally{await navigator.storageBuckets.delete(name).catch(()=>{});}
}
