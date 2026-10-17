// Metadata only. Large quota values do not allocate files or reserve disk space.
async function ownedLowVolumeSignals() {
  async function read(realm) {
    const result={realm,largeQuotas:[],estimate:await navigator.storage.estimate()};
    for(const quota of [1048576,67108864,1073741824,21474836480,1099511627776,Number.MAX_SAFE_INTEGER]) {
      const name='owned-large-'+realm;
      try {
        const bucket=await navigator.storageBuckets.open(name,{quota});
        result.largeQuotas.push({requested:quota,opened:true,estimate:await bucket.estimate()});
      }catch(error){result.largeQuotas.push({requested:quota,opened:false,error:error.name});}
      finally{await navigator.storageBuckets.delete(name);}
    }
    const name='owned-reopen-'+realm;
    try {
      const first=await navigator.storageBuckets.open(name,{quota:2097152});
      const initial=await first.estimate();
      const second=await navigator.storageBuckets.open(name,{quota:8388608});
      result.reopen={initial,firstAfterReopen:await first.estimate(),second:await second.estimate()};
    }finally{await navigator.storageBuckets.delete(name);}
    const before=(await navigator.storageBuckets.keys()).sort();
    const created=[],failures=[];let error=null;
    try {
      for(let i=0;i<600;i+=16) {
        const batch=Array.from({length:Math.min(16,600-i)},(_,offset)=>'owned-count-'+realm+'-'+(i+offset));
        const rows=await Promise.all(batch.map(async key=>{
          try{await navigator.storageBuckets.open(key);return {key,opened:true};}
          catch(e){return {key,opened:false,error:e.name};}
        }));
        for(const row of rows)row.opened?created.push(row.key):failures.push(row);
        if(failures.length){error=failures[0].error;break;}
      }
      result.count={before,created:[...created],failures,batchSize:16,error,
                    keysAtLimit:(await navigator.storageBuckets.keys()).sort()};
    } finally {
      for(let i=0;i<created.length;i+=16)
        await Promise.all(created.slice(i,i+16).map(key=>navigator.storageBuckets.delete(key)));
    }
    result.count.afterCleanup=(await navigator.storageBuckets.keys()).sort();
    const recovered='owned-recover-'+realm;
    try{await navigator.storageBuckets.open(recovered);result.count.creationRecovers=true;}
    finally{await navigator.storageBuckets.delete(recovered);}
    return result;
  }
  const result={window:await read('window')};
  const url=URL.createObjectURL(new Blob(['('+read.toString()+')('+'"dedicated"'+').then(result=>postMessage({result})).catch(error=>postMessage({error:String(error)}));'],{type:'text/javascript'}));
  try {
    result.dedicated=await new Promise((resolve,reject)=>{
      const worker=new Worker(url);
      const timer=setTimeout(()=>{worker.terminate();reject(Error('Owned bucket worker timeout'));},60000);
      worker.onmessage=e=>{clearTimeout(timer);worker.terminate();e.data.error?reject(Error(e.data.error)):resolve(e.data.result);};
      worker.onerror=e=>{clearTimeout(timer);worker.terminate();reject(Error(e.message));};
    });
  } finally {URL.revokeObjectURL(url);}
  return result;
}
