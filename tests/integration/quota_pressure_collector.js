// Bounded owned data only: at most 8 MiB per write, removed after each trial.
async function ownedQuotaTrial(config) {
  const bytes = config.bytes;
  if (![4096, 8 * 1024 * 1024].includes(bytes)) throw Error('Invalid owned write size');
  const bucket = config.bucket ? await navigator.storageBuckets.open('owned-pressure', {quota:2*1024*1024}) : null;
  const factory = bucket ? bucket.indexedDB : indexedDB;
  const cacheStorage = bucket ? bucket.caches : caches;
  const directory = bucket ? await bucket.getDirectory() : await navigator.storage.getDirectory();
  const result = {realm:config.realm, origin:location.origin, bytes, bucket:!!bucket,
    estimate:await navigator.storage.estimate(), bucketEstimate:bucket ? await bucket.estimate() : null, stores:{}};
  const payload = new Uint8Array(bytes).fill(42);
  const digest=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');
  const collect = async (name, run) => {
    try {result.stores[name] = await run();}
    catch(error) {result.stores[name] = {unexpectedError:error.name, message:String(error)};}
  };
  await collect('opfs', async () => {
    const file = await directory.getFileHandle('owned-pressure.bin', {create:true});
    const initial = await file.createWritable(); await initial.write(new Uint8Array(4096).fill(7)); await initial.close();
    let writer, write, stage='createWritable';
    try {writer=await file.createWritable();stage='write';await writer.write(payload);stage='close';await writer.close();write={completed:true};}
    catch(error) {write={completed:false,error:error.name,message:error.message,stage};if(writer)await writer.abort().catch(()=>{});}
    const data=await (await file.getFile()).arrayBuffer();
    await directory.removeEntry('owned-pressure.bin');
    return {write, size:data.byteLength, first:new Uint8Array(data)[0], sha256:await digest(data), deleted:true};
  });
  await collect('indexedDB', async () => {
    const db=await new Promise((resolve,reject)=>{
      const request=factory.open('owned-pressure',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('canary');
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
    const transaction = (kind, value) => new Promise((resolve,reject)=>{
      const tx=db.transaction('canary',kind==='read'?'readonly':'readwrite');const store=tx.objectStore('canary');let observed;
      if(kind==='write')store.put(value,'key');
      if(kind==='delete')store.delete('key');
      if(kind==='read'){const r=store.get('key');r.onsuccess=()=>{observed=r.result;};}
      tx.oncomplete=()=>resolve(observed);tx.onabort=()=>reject(tx.error || Error('Owned transaction aborted'));
      // Keep the native abort default when a quota error bubbles.
    });
    try {
      await transaction('write',new Uint8Array(4096).fill(7));
      let write;try{await transaction('write',payload);write={completed:true};}
      catch(error){write={completed:false,error:error.name};}
      const data=await transaction('read');await transaction('delete');
      return {write,size:data.byteLength,first:data[0],sha256:await digest(data),deleted:true};
    } finally {db.close();}
  });
  await collect('cacheStorage', async () => {
    const cache=await cacheStorage.open('owned-pressure');const key=location.origin+'/owned-pressure-data';
    await cache.put(key,new Response(new Uint8Array(4096).fill(7)));
    let write;try{await cache.put(key,new Response(payload));write={completed:true};}
    catch(error){write={completed:false,error:error.name};}
    const data=await (await cache.match(key)).arrayBuffer();await cache.delete(key);
    return {write,size:data.byteLength,first:new Uint8Array(data)[0],sha256:await digest(data),deleted:true};
  });
  result.afterEstimate=await navigator.storage.estimate();
  return result;
}
