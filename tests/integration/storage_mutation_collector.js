// Owned loopback canaries only; no file pickers, user files or device access.
async function storageOperation(operation, value = null) {
  const result = {origin: location.origin, secureContext: isSecureContext,
    operation, stores: {}, estimate: null, persisted: null};
  const database = async (factory, action, marker) => {
    const db = await new Promise((resolve, reject) => {
      const request = factory.open('metabrowser-storage-canary', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('values');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(Error('Owned database blocked'));
    });
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('values', action === 'read' ? 'readonly' : 'readwrite');
        const store = tx.objectStore('values');
        let observed = null;
        if (action === 'write') store.put(marker, 'canary');
        if (action === 'delete') store.delete('canary');
        if (action === 'read') {
          const read = store.get('canary');
          read.onsuccess = () => { observed = read.result ?? null; };
        }
        tx.oncomplete = () => resolve(observed);
        tx.onabort = tx.onerror = () => reject(tx.error ?? Error('Owned transaction failed'));
      });
    } finally { db.close(); }
  };
  const collect = async (name, fn) => {
    try { result.stores[name] = {completed: true, value: await fn()}; }
    catch (error) { result.stores[name] = {completed: false, error: error.name}; }
  };
  await collect('indexedDB', async () => {
    await database(indexedDB, operation, value);
    return database(indexedDB, 'read', null);
  });
  await collect('cacheStorage', async () => {
    const cache = await caches.open('metabrowser-storage-canary');
    const key = location.origin + '/owned-storage-canary';
    if (operation === 'write') await cache.put(key, new Response(value));
    if (operation === 'delete') await cache.delete(key);
    const response = await cache.match(key);
    return response ? response.text() : null;
  });
  await collect('opfs', async () => {
    const directory = await navigator.storage.getDirectory();
    const name = 'metabrowser-storage-canary.txt';
    if (operation === 'write') {
      const file = await directory.getFileHandle(name, {create: true});
      const writer = await file.createWritable();
      await writer.write(value); await writer.close();
    }
    if (operation === 'delete') {
      try { await directory.removeEntry(name); }
      catch (error) { if (error.name !== 'NotFoundError') throw error; }
    }
    try { return (await (await directory.getFileHandle(name)).getFile()).text(); }
    catch (error) { if (error.name === 'NotFoundError') return null; throw error; }
  });
  await collect('bucketIndexedDB', async () => {
    if (!navigator.storageBuckets) throw new DOMException('No buckets', 'NotSupportedError');
    const bucket = await navigator.storageBuckets.open('metabrowser-canary', {quota: 524288});
    await database(bucket.indexedDB, operation, value);
    const observed = await database(bucket.indexedDB, 'read', null);
    result.bucketEstimate = await bucket.estimate();
    result.bucketPersisted = await bucket.persisted();
    return observed;
  });
  try {
    result.estimate = await navigator.storage.estimate();
    result.persisted = await navigator.storage.persisted();
    result.persistentStoragePermission = (await navigator.permissions.query({name: 'persistent-storage'})).state;
  } catch (error) { result.estimateError = error.name; }
  return result;
}

// Each write/delete is performed in the named native worker, then observed
// independently by its owning window. Realm order is serial to avoid races.
async function collectStorageRealms(operation, value) {
  const result = await storageOperation(operation, value);
  result.workers = {};
  result.mutationTrace = {};
  async function invoke(realm, operation, value) {
    const message = {operation, value};
    let dispose = () => {};
    let timer;
    try {
      return await Promise.race([new Promise(async (resolve, reject) => {
        try {
          const receive = event => event.data.error ? reject(Error(event.data.error)) : resolve(event.data.result);
          if (realm === 'service') {
            const reg = await navigator.serviceWorker.register('/storage-service.js');
            dispose = () => reg.unregister();
            await navigator.serviceWorker.ready;
            if (!reg.active) throw Error('No active owned service worker');
            const channel = new MessageChannel();
            const unregister = dispose;
            dispose = async () => {channel.port1.close(); await unregister();};
            channel.port1.onmessage = receive;
            reg.active.postMessage(message, [channel.port2]);
          } else if (realm === 'shared') {
            const worker = new SharedWorker('/storage-shared.js', 'owned-storage-mutation');
            dispose = () => worker.port.close();
            worker.port.onmessage = receive;
            worker.onerror = event => reject(Error(event.message));
            worker.port.start(); worker.port.postMessage(message);
          } else {
            const path = realm === 'module' ? '/storage-module.js' : realm === 'nested' ? '/storage-nested.js' : '/storage-worker.js';
            const worker = new Worker(path, realm === 'module' ? {type: 'module'} : {});
            dispose = () => worker.terminate();
            worker.onmessage = receive;
            worker.onerror = event => reject(Error(event.message));
            worker.postMessage(message);
          }
        } catch(error) {reject(error);}
      }), new Promise((_, reject) => {timer = setTimeout(() => reject(Error('Owned mutation timeout')),12000);})]);
    } finally {clearTimeout(timer); await dispose();}
  }
  for (const realm of ['dedicated', 'module', 'nested', 'shared', 'service']) {
    try {
      // Initial worker read must precede mutations so isolation bugs remain visible.
      result.workers[realm] = await invoke(realm, 'read', null);
      const trace = result.mutationTrace[realm] = {};
      trace.write = await invoke(realm, 'write', value + ':' + realm);
      trace.windowAfterWrite = await storageOperation('read');
      trace.delete = await invoke(realm, 'delete', null);
      trace.windowAfterDelete = await storageOperation('read');
      // Restore the lifecycle sample, including the genuinely empty cases.
      if (result.stores.indexedDB.value !== null)
        await storageOperation('write', result.stores.indexedDB.value);
    } catch(error) {result.mutationTrace[realm] = {error: String(error)};}
  }
  return result;
}
