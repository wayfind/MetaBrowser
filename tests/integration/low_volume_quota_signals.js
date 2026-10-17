// Read native public quota APIs; no getter replacements or device writes.
async function ownedLowVolumeSignals() {
  async function read() {
    const result={estimate:await navigator.storage.estimate(),legacy:{}};
    for(const name of ['webkitTemporaryStorage','webkitPersistentStorage']) {
      const api=navigator[name];
      if(!api){result.legacy[name]={available:false};continue;}
      result.legacy[name]=await new Promise(resolve=>{
        const timer=setTimeout(()=>resolve({available:true,error:'Timeout'}),2000);
        api.queryUsageAndQuota((usage,quota)=>{clearTimeout(timer);resolve({available:true,usage,quota});},
          error=>{clearTimeout(timer);resolve({available:true,error:error.name});});
      });
    }
    const implicit=await navigator.storageBuckets.open('owned-low-volume-implicit');
    result.implicitBucket=await implicit.estimate();
    const explicit=await navigator.storageBuckets.open('owned-low-volume-explicit',{quota:2*1024*1024});
    result.explicitBucket=await explicit.estimate();
    return result;
  }
  const result={window:await read()};
  const url=URL.createObjectURL(new Blob(['('+read.toString()+')().then(result=>postMessage({result})).catch(error=>postMessage({error:String(error)}));'],{type:'text/javascript'}));
  try {
    result.dedicated=await new Promise((resolve,reject)=>{
      const worker=new Worker(url);
      const timer=setTimeout(()=>{worker.terminate();reject(Error('Owned low-volume worker timeout'));},10000);
      worker.onmessage=e=>{clearTimeout(timer);worker.terminate();e.data.error?reject(Error(e.data.error)):resolve(e.data.result);};
      worker.onerror=e=>{clearTimeout(timer);worker.terminate();reject(Error(e.message));};
    });
  } finally {URL.revokeObjectURL(url);}
  await navigator.storageBuckets.delete('owned-low-volume-implicit');
  await navigator.storageBuckets.delete('owned-low-volume-explicit');
  return result;
}
