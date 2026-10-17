// Owned loopback fixture. Never reads credentials or visits an external origin.
const DB_NAME = 'metabrowser-owned-isolation';
const CACHE_NAME = 'metabrowser-owned-isolation';
const FILE_NAME = 'metabrowser-owned-isolation.txt';

async function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('values');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(Error('Owned IndexedDB is blocked'));
  });
}

async function idb(value) {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction('values', value === undefined ? 'readonly' : 'readwrite');
      const store = transaction.objectStore('values');
      const request = value === undefined ? store.get('marker') : store.put(value, 'marker');
      let result = null;
      request.onsuccess = () => { result = request.result === undefined ? null : request.result; };
      transaction.oncomplete = () => resolve(value === undefined ? result : value);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || Error('Owned transaction aborted'));
    });
  } finally { db.close(); }
}

async function stores(value) {
  const result = {indexedDB: await idb(value)};
  const cache = await caches.open(CACHE_NAME);
  if (value !== undefined) await cache.put('/owned-cache-entry', new Response(value));
  const response = await cache.match('/owned-cache-entry');
  result.cache = response ? await response.text() : null;
  const directory = await navigator.storage.getDirectory();
  let file;
  try { file = await directory.getFileHandle(FILE_NAME, {create: value !== undefined}); }
  catch (error) { if (error.name !== 'NotFoundError') throw error; }
  if (value !== undefined) {
    const writable = await file.createWritable();
    await writable.write(value);
    await writable.close();
  }
  result.opfs = file ? await (await file.getFile()).text() : null;
  return result;
}

async function workerState() {
  return {kind: globalThis.constructor.name, stores: await stores()};
}

if (typeof window === 'undefined') {
  if (globalThis.constructor.name === 'ServiceWorkerGlobalScope') {
    oninstall = event => event.waitUntil(skipWaiting());
    onactivate = event => event.waitUntil(clients.claim());
    onmessage = event => event.waitUntil(workerState().then(
      value => event.ports[0].postMessage(value),
      error => event.ports[0].postMessage({error: String(error)})));
  } else if (globalThis.constructor.name === 'SharedWorkerGlobalScope') {
    let marker = null;
    onconnect = event => {
      const port = event.ports[0];
      port.onmessage = async event => {
        try {
          const result = await workerState();
          result.memory_before = marker;
          marker = event.data;
          port.postMessage(result);
        } catch (error) { port.postMessage({error: String(error)}); }
      };
      port.start();
    };
  } else {
    onmessage = () => workerState().then(
      value => postMessage(value), error => postMessage({error: String(error)}));
  }
} else {
  const parameters = new URL(location.href).searchParams;
  const run = parameters.get('run');
  const token = parameters.get('token');
  const bounded = promise => Promise.race([promise,
    new Promise((_, reject) => setTimeout(() => reject(Error('Owned probe timed out')), 15000))]);
  function channel(target) {
    return bounded(new Promise(resolve => {
      const pipe = new MessageChannel();
      pipe.port1.onmessage = event => { pipe.port1.close(); resolve(event.data); };
      target.postMessage(token, [pipe.port2]);
    }));
  }
  async function snapshot() {
    const result = await stores();
    result.localStorage = localStorage.getItem(DB_NAME);
    const response = await fetch('/cookie/read', {cache: 'no-store'});
    if (!response.ok) throw Error('Cookie capture failed');
    result.cookie = (await response.json()).marker;
    return result;
  }
  async function collect() {
    if (!/^[a-f0-9]{32}$/.test(token)) throw Error('Owned marker required');
    const before = await snapshot();
    const registrationsBefore = (await navigator.serviceWorker.getRegistrations()).map(item => item.scope);
    await stores(token);
    localStorage.setItem(DB_NAME, token);
    const response = await fetch('/cookie/set?token=' + token, {cache: 'no-store'});
    if (!response.ok) throw Error('Cookie write failed');
    const after = await snapshot();
    const dedicated = new Worker('/probe.js');
    let dedicatedResult;
    try {
      dedicatedResult = await bounded(new Promise((resolve, reject) => {
        dedicated.onmessage = event => resolve(event.data);
        dedicated.onerror = event => reject(Error(event.message));
        dedicated.postMessage(token);
      }));
    } finally { dedicated.terminate(); }
    // Keep the port alive until navigation/quit, so B must not join A's worker.
    const shared = new SharedWorker('/probe.js', {name: 'metabrowser-owned-isolation'});
    const sharedResult = await bounded(new Promise((resolve, reject) => {
      shared.onerror = event => reject(Error(event.message));
      shared.port.onmessage = event => resolve(event.data);
      shared.port.start(); shared.port.postMessage(token);
    }));
    globalThis.ownedSharedWorker = shared;
    await navigator.serviceWorker.register('/probe.js', {scope: '/'});
    const registration = await bounded(navigator.serviceWorker.ready);
    const serviceResult = await channel(registration.active);
    const canvas = document.createElement('canvas');
    canvas.width = 240; canvas.height = 60;
    const context = canvas.getContext('2d');
    context.fillStyle = '#f3ecfb'; context.fillRect(0, 0, 240, 60);
    context.font = '19px sans-serif'; context.fillStyle = '#8a4ed1';
    context.fillText('Identity isolation 0123456789', 3, 35);
    const bytes = context.getImageData(0, 0, 240, 60).data;
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
      .map(value => value.toString(16).padStart(2, '0')).join('');
    return {run, token, origin: location.origin, before, after,
      registrations_before: registrationsBefore, http_cache: globalThis.ownedHttpCache,
      workers: {dedicated: dedicatedResult, shared: sharedResult, service: serviceResult},
      canvas: hash, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      languages: [...navigator.languages], platform: navigator.platform};
  }
  bounded(collect()).then(report => submit({run, report}), error => submit({run, error: String(error)}));
  async function submit(value) {
    document.querySelector('pre').textContent = JSON.stringify(value, null, 2);
    await fetch('/report', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(value)});
  }
}
