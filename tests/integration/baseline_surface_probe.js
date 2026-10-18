// Same-version baseline surface collector. Runs unmodified in Window, iframe and
// Dedicated/Shared/Service Worker realms; never overrides, grants permissions or
// contacts other origins. Every section records its own error instead of failing.
async function collectBaselineSurface() {
  const out = {realm: globalThis.constructor.name, errors: {}};
  const section = async (name, fn) => {
    try { out[name] = await fn(); } catch (e) { out.errors[name] = String(e && e.name || e); }
  };
  const isWindow = 'document' in globalThis;
  const primitive = v => v === null || ['string', 'number', 'boolean', 'undefined'].includes(typeof v);
  const names = object => object ? Object.getOwnPropertyNames(object).sort() : null;
  const sha = async text => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
    typeof text === 'string' ? new TextEncoder().encode(text) : text))).map(x => x.toString(16).padStart(2, '0')).join('');
  const timeout = (promise, ms) => Promise.race([promise, new Promise((_, no) => setTimeout(() => no(Error('timeout')), ms))]);

  await section('navigator', async () => {
    const result = {};
    for (let p = Object.getPrototypeOf(navigator); p && p !== Object.prototype; p = Object.getPrototypeOf(p))
      for (const key of Object.getOwnPropertyNames(p)) {
        if (key === 'constructor' || key in result) continue;
        let value; try { value = navigator[key]; } catch (e) { result[key] = {error: e.name}; continue; }
        result[key] = typeof value === 'function' ? 'function' : primitive(value) ? value
          : Array.isArray(value) || key === 'languages' ? [...value] : value === null ? null : 'object:' + Object.prototype.toString.call(value);
      }
    return result;
  });
  await section('uaData', async () => navigator.userAgentData ? {
    brands: navigator.userAgentData.brands, mobile: navigator.userAgentData.mobile, platform: navigator.userAgentData.platform,
    high: await navigator.userAgentData.getHighEntropyValues(['architecture', 'bitness', 'brands', 'formFactors',
      'fullVersionList', 'model', 'platform', 'platformVersion', 'uaFullVersion', 'wow64'])} : {absent: true});
  await section('globals', async () => names(globalThis));
  await section('interfaces', async () => {
    const result = {};
    for (const name of ['Navigator', 'WorkerNavigator', 'NavigatorUAData', 'Screen', 'Window', 'Document', 'Element', 'HTMLElement',
      'HTMLCanvasElement', 'OffscreenCanvas', 'CanvasRenderingContext2D', 'OffscreenCanvasRenderingContext2D',
      'WebGLRenderingContext', 'WebGL2RenderingContext', 'GPU', 'GPUAdapter', 'GPUDevice', 'AudioContext', 'BaseAudioContext',
      'OfflineAudioContext', 'AnalyserNode', 'MediaDevices', 'MediaStreamTrack', 'RTCPeerConnection', 'HTMLMediaElement',
      'MediaSource', 'MediaCapabilities', 'Permissions', 'StorageManager', 'ServiceWorkerContainer', 'Performance',
      'PerformanceTiming', 'Intl', 'FontFaceSet', 'Clipboard', 'NetworkInformation', 'BatteryManager', 'XRSystem', 'HID',
      'USB', 'Serial', 'Bluetooth', 'Gamepad', 'PaymentRequest', 'CredentialsContainer', 'PublicKeyCredential',
      'WebTransport', 'Scheduler', 'NavigatorManagedData', 'Keyboard', 'WakeLock', 'LockManager', 'IdleDetector',
      'SpeechSynthesis', 'Notification', 'Worker', 'SharedWorker', 'WorkerGlobalScope', 'DedicatedWorkerGlobalScope',
      'SharedWorkerGlobalScope', 'ServiceWorkerGlobalScope'])
      result[name] = name === 'Intl' ? names(Intl) : typeof globalThis[name] === 'function' ? names(globalThis[name].prototype) : null;
    return result;
  });
  await section('javascript', async () => {
    const proto = Object.getPrototypeOf(Int8Array.prototype);
    const builtins = {Object: names(Object), ObjectPrototype: names(Object.prototype), Array: names(Array),
      ArrayPrototype: names(Array.prototype), String: names(String), StringPrototype: names(String.prototype),
      Number: names(Number), NumberPrototype: names(Number.prototype), Math: names(Math), JSON: names(JSON),
      Reflect: names(Reflect), Atomics: names(globalThis.Atomics), Promise: names(Promise), PromisePrototype: names(Promise.prototype),
      RegExpPrototype: names(RegExp.prototype), SetPrototype: names(Set.prototype), MapPrototype: names(Map.prototype),
      Iterator: names(globalThis.Iterator), IteratorPrototype: globalThis.Iterator ? names(Iterator.prototype) : null,
      ArrayBufferPrototype: names(ArrayBuffer.prototype), TypedArrayPrototype: names(proto), Error: names(Error),
      FunctionPrototype: names(Function.prototype), Symbol: names(Symbol), WebAssembly: names(globalThis.WebAssembly),
      Temporal: globalThis.Temporal ? names(Temporal) : null};
    let typeError = null, stack = null;
    try { null.f(); } catch (e) { typeError = e.message; }
    try { throw new RangeError('probe'); } catch (e) { stack = String(e.stack).split('\n')[0]; }
    const math = {};
    for (const [fn, args] of [['sin', [1e100]], ['cos', [1e100]], ['tan', [-1e300]], ['exp', [1]], ['expm1', [1]], ['log', [10]],
      ['log1p', [1]], ['log10', [7]], ['log2', [7]], ['atan', [2]], ['atan2', [0.5, 0.25]], ['asinh', [1]], ['acosh', [1e300]],
      ['atanh', [0.5]], ['sinh', [1]], ['cosh', [10]], ['tanh', [1e-300]], ['cbrt', [100]], ['pow', [Math.PI, -100]],
      ['hypot', [1e100, 1e100]], ['sqrt', [2]], ['fround', [5.5]]])
      math[fn + '(' + args.join(',') + ')'] = Math[fn](...args);
    return {builtins, typeError, stack, stackTraceLimit: Error.stackTraceLimit, math,
      nativeToString: Function.prototype.toString.call(Math.max), numberFormat: (1234567.891).toLocaleString(),
      dateString: new Date(Date.UTC(2026, 0, 15, 12)).toString(), dateLocale: new Date(Date.UTC(2026, 6, 15, 12)).toLocaleString(),
      dtf: Intl.DateTimeFormat().resolvedOptions(), nf: Intl.NumberFormat().resolvedOptions(), collator: Intl.Collator().resolvedOptions(),
      supportedValues: Object.fromEntries(await Promise.all(['calendar', 'collation', 'currency', 'numberingSystem', 'timeZone', 'unit']
        .map(async key => { const values = Intl.supportedValuesOf(key); return [key, {count: values.length, sha256: await sha(values.join(','))}]; })))};
  });
  await section('hardware', async () => ({hardwareConcurrency: navigator.hardwareConcurrency, deviceMemory: navigator.deviceMemory,
    jsHeapSizeLimit: globalThis.performance?.memory?.jsHeapSizeLimit ?? null,
    connection: navigator.connection ? Object.fromEntries(['effectiveType', 'type', 'rtt', 'downlink', 'saveData'].map(k => [k, navigator.connection[k] ?? null])) : null}));
  await section('permissions', async () => {
    const result = {};
    for (const name of ['geolocation', 'notifications', 'camera', 'microphone', 'midi', 'clipboard-read', 'clipboard-write',
      'background-sync', 'persistent-storage', 'accelerometer', 'gyroscope', 'magnetometer', 'local-fonts', 'window-management',
      'storage-access', 'top-level-storage-access', 'payment-handler', 'idle-detection', 'screen-wake-lock', 'display-capture'])
      try { result[name] = (await navigator.permissions.query({name})).state; } catch (e) { result[name] = 'error:' + e.name; }
    return result;
  });
  await section('storage', async () => { const e = await navigator.storage.estimate(); return {quota: e.quota, persisted: isWindow ? await navigator.storage.persisted() : null}; });
  await section('webgpu', async () => {
    if (!navigator.gpu) return {absent: true};
    const adapter = await timeout(navigator.gpu.requestAdapter(), 5000);
    if (!adapter) return {adapter: null, preferredFormat: navigator.gpu.getPreferredCanvasFormat?.()};
    const limits = {}; for (const key in adapter.limits) limits[key] = adapter.limits[key];
    const info = adapter.info ? Object.fromEntries(['vendor', 'architecture', 'device', 'description', 'subgroupMinSize', 'subgroupMaxSize', 'isFallbackAdapter'].map(k => [k, adapter.info[k] ?? null])) : null;
    return {info, features: [...adapter.features].sort(), limits, preferredFormat: navigator.gpu.getPreferredCanvasFormat?.(),
      wgslLanguageFeatures: navigator.gpu.wgslLanguageFeatures ? [...navigator.gpu.wgslLanguageFeatures].sort() : null};
  });
  await section('media', async () => {
    const types = ['video/mp4; codecs="avc1.42E01E"', 'video/mp4; codecs="avc1.640028"', 'video/mp4; codecs="hvc1.1.6.L93.B0"',
      'video/mp4; codecs="hev1.1.6.L93.B0"', 'video/mp4; codecs="av01.0.05M.08"', 'video/mp4; codecs="vp09.00.10.08"',
      'video/webm; codecs="vp8"', 'video/webm; codecs="vp9"', 'video/webm; codecs="av01.0.05M.08"', 'video/ogg; codecs="theora"',
      'audio/mp4; codecs="mp4a.40.2"', 'audio/mp4; codecs="mp4a.40.5"', 'audio/mp4; codecs="ac-3"', 'audio/mp4; codecs="ec-3"',
      'audio/mp4; codecs="flac"', 'audio/mp4; codecs="opus"', 'audio/mpeg', 'audio/aac', 'audio/flac', 'audio/wav', 'audio/x-m4a',
      'audio/webm; codecs="opus"', 'audio/webm; codecs="vorbis"', 'audio/ogg; codecs="opus"', 'application/vnd.apple.mpegurl',
      'application/x-mpegURL', 'video/mp2t; codecs="avc1.42E01E,mp4a.40.2"', 'video/x-matroska', 'video/quicktime'];
    const result = {mediaSource: {}, mediaRecorder: {}, decodingInfo: {}};
    if (isWindow) { const video = document.createElement('video'); result.canPlayType = Object.fromEntries(types.map(t => [t, video.canPlayType(t)])); }
    for (const t of types) {
      if (globalThis.MediaSource) result.mediaSource[t] = MediaSource.isTypeSupported(t);
      if (globalThis.MediaRecorder) result.mediaRecorder[t] = MediaRecorder.isTypeSupported(t);
    }
    if (navigator.mediaCapabilities) for (const contentType of ['video/mp4; codecs="avc1.640028"', 'video/webm; codecs="vp09.00.10.08"',
      'video/mp4; codecs="av01.0.05M.08"', 'video/mp4; codecs="hvc1.1.6.L93.B0"']) {
      try { const r = await navigator.mediaCapabilities.decodingInfo({type: 'file', video: {contentType, width: 1920, height: 1080, bitrate: 4e6, framerate: 30}});
        result.decodingInfo[contentType] = {supported: r.supported, smooth: r.smooth, powerEfficient: r.powerEfficient}; }
      catch (e) { result.decodingInfo[contentType] = 'error:' + e.name; }
    }
    if (globalThis.RTCRtpSender) for (const kind of ['audio', 'video'])
      result['rtp_' + kind] = (RTCRtpSender.getCapabilities(kind)?.codecs || []).map(c => c.mimeType + ' ' + (c.sdpFmtpLine || '')).sort();
    if (isWindow && navigator.mediaDevices?.enumerateDevices) result.devices = (await navigator.mediaDevices.enumerateDevices()).map(d => d.kind + (d.label ? ':labelled' : '')).sort();
    if (isWindow && globalThis.speechSynthesis) {
      let voices = speechSynthesis.getVoices();
      if (!voices.length) voices = await timeout(new Promise(ok => speechSynthesis.addEventListener('voiceschanged', () => ok(speechSynthesis.getVoices()), {once: true})), 3000).catch(() => []);
      result.voices = {count: voices.length, sha256: await sha(voices.map(v => v.name + '|' + v.lang + '|' + v.localService).sort().join('\n'))};
    }
    return result;
  });
  if (isWindow) {
    await section('fonts', async () => {
      const families = ['Arial', 'Helvetica', 'Helvetica Neue', 'Times New Roman', 'Times', 'Courier New', 'Courier', 'Verdana', 'Georgia',
        'Palatino', 'Garamond', 'Bookman', 'Trebuchet MS', 'Impact', 'Comic Sans MS', 'Tahoma', 'Lucida Grande', 'Menlo', 'Monaco',
        'SF Pro Text', 'SF Mono', 'Avenir', 'Avenir Next', 'Futura', 'Gill Sans', 'Optima', 'Baskerville', 'Didot', 'American Typewriter',
        'Apple Color Emoji', 'PingFang SC', 'PingFang TC', 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Heiti SC', 'Songti SC',
        'STHeiti', 'Apple SD Gothic Neo', 'Segoe UI', 'Calibri', 'Cambria', 'Consolas', 'Microsoft YaHei', 'SimSun', 'MS Gothic',
        'Ubuntu', 'DejaVu Sans', 'Liberation Sans', 'Noto Sans', 'Noto Sans CJK SC', 'Roboto', 'Droid Sans', 'Cantarell', 'Arimo'];
      await document.fonts.ready;
      const canvas = document.createElement('canvas').getContext('2d'), text = 'mmmmmmmmmmlli 指纹 0123456789 WwQq';
      const width = font => { canvas.font = '32px ' + font; return canvas.measureText(text).width; };
      // Compare against a missing family in the same list: a bare "monospace" gets a different
      // default size than "X, monospace", so bare generic widths would flag every family.
      const bases = ['monospace', 'serif', 'sans-serif'];
      const fallback = Object.fromEntries(bases.map(base => [base, width('"metabrowser-no-such-font",' + base)]));
      return Object.fromEntries(families.map(f => [f, bases.some(base => width('"' + f + '",' + base) !== fallback[base])]));
    });
    await section('display', async () => ({screen: Object.fromEntries(['width', 'height', 'availWidth', 'availHeight', 'availLeft', 'availTop',
      'colorDepth', 'pixelDepth', 'isExtended'].map(k => [k, screen[k] ?? null])), orientation: screen.orientation?.type ?? null,
      dpr: devicePixelRatio, outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight],
      mediaQueries: Object.fromEntries(['(pointer: coarse)', '(pointer: fine)', '(hover: hover)', '(any-hover: hover)', '(any-pointer: coarse)',
        '(prefers-color-scheme: dark)', '(prefers-reduced-motion: reduce)', '(prefers-contrast: more)', '(forced-colors: active)',
        '(inverted-colors: inverted)', '(color-gamut: srgb)', '(color-gamut: p3)', '(color-gamut: rec2020)', '(dynamic-range: high)',
        '(video-dynamic-range: high)', '(monochrome)', '(update: fast)', '(scripting: enabled)', '(display-mode: browser)',
        '(prefers-reduced-transparency: reduce)'].map(q => [q, matchMedia(q).matches]))}));
    await section('plugins', async () => ({pdfViewerEnabled: navigator.pdfViewerEnabled,
      plugins: [...navigator.plugins].map(p => ({name: p.name, filename: p.filename, description: p.description, mimes: [...p].map(m => m.type)})),
      mimeTypes: [...navigator.mimeTypes].map(m => ({type: m.type, suffixes: m.suffixes, plugin: m.enabledPlugin?.name}))}));
    await section('rendering', async () => {
      const c = document.createElement('canvas'); c.width = 240; c.height = 60; const x = c.getContext('2d');
      x.fillStyle = '#e9d380'; x.fillRect(0, 0, 240, 60); x.fillStyle = '#273b83'; x.font = '17px Arial';
      x.fillText('MetaBrowser 指纹 0123456789', 3, 29); x.fillStyle = 'rgba(180,20,90,.43)'; x.fillRect(20, 11, 88, 23);
      const result = {canvas: await sha(x.getImageData(0, 0, 240, 60).data.buffer), webgl: {}};
      const audio = new OfflineAudioContext(1, 44100, 44100), osc = audio.createOscillator(), compressor = audio.createDynamicsCompressor();
      osc.type = 'triangle'; osc.frequency.value = 10000; osc.connect(compressor); compressor.connect(audio.destination); osc.start(0);
      result.audio = await sha((await audio.startRendering()).getChannelData(0).buffer);
      result.audioContext = (() => { const ctx = new AudioContext(); const r = {sampleRate: ctx.sampleRate, baseLatency: ctx.baseLatency,
        maxChannelCount: ctx.destination.maxChannelCount}; ctx.close(); return r; })();
      for (const version of ['webgl', 'webgl2']) {
        const gl = document.createElement('canvas').getContext(version); if (!gl) { result.webgl[version] = null; continue; }
        const parameters = {};
        for (const key of ['VENDOR', 'RENDERER', 'VERSION', 'SHADING_LANGUAGE_VERSION', 'MAX_TEXTURE_SIZE', 'MAX_CUBE_MAP_TEXTURE_SIZE',
          'MAX_RENDERBUFFER_SIZE', 'MAX_VERTEX_ATTRIBS', 'MAX_VERTEX_UNIFORM_VECTORS', 'MAX_VARYING_VECTORS', 'MAX_FRAGMENT_UNIFORM_VECTORS',
          'MAX_VERTEX_TEXTURE_IMAGE_UNITS', 'MAX_TEXTURE_IMAGE_UNITS', 'MAX_COMBINED_TEXTURE_IMAGE_UNITS', 'MAX_SAMPLES',
          'MAX_3D_TEXTURE_SIZE', 'MAX_ARRAY_TEXTURE_LAYERS', 'MAX_DRAW_BUFFERS', 'MAX_COLOR_ATTACHMENTS', 'MAX_UNIFORM_BUFFER_BINDINGS']) {
          if (gl[key] === undefined) continue;
          const value = gl.getParameter(gl[key]); parameters[key] = primitive(value) ? value : Array.from(value);
        }
        for (const key of ['ALIASED_LINE_WIDTH_RANGE', 'ALIASED_POINT_SIZE_RANGE', 'MAX_VIEWPORT_DIMS']) parameters[key] = Array.from(gl.getParameter(gl[key]));
        const debug = gl.getExtension('WEBGL_debug_renderer_info');
        if (debug) { parameters.UNMASKED_VENDOR = gl.getParameter(debug.UNMASKED_VENDOR_WEBGL); parameters.UNMASKED_RENDERER = gl.getParameter(debug.UNMASKED_RENDERER_WEBGL); }
        const precision = {};
        for (const stage of ['VERTEX_SHADER', 'FRAGMENT_SHADER']) for (const type of ['LOW_FLOAT', 'MEDIUM_FLOAT', 'HIGH_FLOAT', 'LOW_INT', 'MEDIUM_INT', 'HIGH_INT']) {
          const f = gl.getShaderPrecisionFormat(gl[stage], gl[type]); precision[stage + ':' + type] = [f.rangeMin, f.rangeMax, f.precision];
        }
        const attributes = gl.getContextAttributes();
        result.webgl[version] = {parameters, precision, extensions: (gl.getSupportedExtensions() || []).sort(), attributes};
        gl.getExtension('WEBGL_lose_context')?.loseContext();
      }
      return result;
    });
  }
  return out;
}
