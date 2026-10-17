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

// The same read runs in native workers, not a simulated page-side result.
async function collectStorageRealms(operation, value) {
  const result = await storageOperation(operation, value);
  result.workers = {};
  const collect = async (name, fn) => {
    try {
      result.workers[name] = await Promise.race([fn(), new Promise((_, reject) =>
        setTimeout(() => reject(Error('Owned worker timeout')), 12000))]);
    } catch (error) { result.workers[name] = {error: error.name}; }
  };
  await Promise.all([collect('dedicated', () => new Promise((resolve, reject) => {
    const worker = new Worker('/storage-worker.js');
    worker.onmessage = event => { worker.terminate(); resolve(event.data.result ?? {error: event.data.error}); };
    worker.onerror = event => { worker.terminate(); reject(Error(event.message)); };
    worker.postMessage(0);
  })), collect('shared', () => new Promise((resolve, reject) => {
    const worker = new SharedWorker('/storage-shared.js', 'owned-storage-read');
    worker.port.onmessage = event => { worker.port.close(); resolve(event.data.result ?? {error: event.data.error}); };
    worker.onerror = event => { worker.port.close(); reject(Error(event.message)); };
    worker.port.start(); worker.port.postMessage(0);
  })), collect('module', () => new Promise((resolve, reject) => {
    const worker = new Worker('/storage-module.js', {type: 'module'});
    worker.onmessage = event => { worker.terminate(); resolve(event.data.result ?? {error: event.data.error}); };
    worker.onerror = event => { worker.terminate(); reject(Error(event.message)); };
    worker.postMessage(0);
  })), collect('nested', () => new Promise((resolve, reject) => {
    const worker = new Worker('/storage-nested.js');
    worker.onmessage = event => { worker.terminate(); resolve(event.data.result ?? {error: event.data.error}); };
    worker.onerror = event => { worker.terminate(); reject(Error(event.message)); };
    worker.postMessage(0);
  })), collect('service', async () => {
    const reg = await navigator.serviceWorker.register('/storage-service.js');
    try {
      await navigator.serviceWorker.ready;
      if (!reg.active) throw Error('No owned active service worker');
      return await new Promise(resolve => {
        const channel = new MessageChannel();
        channel.port1.onmessage = event => { channel.port1.close(); resolve(event.data.result ?? {error: event.data.error}); };
        reg.active.postMessage(0, [channel.port2]);
      });
    } finally { await reg.unregister(); }
  })]);
  return result;
}
