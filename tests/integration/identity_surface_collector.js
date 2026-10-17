// Runs in native Window/Worker realms. No overrides, permission grants or sites.
async function collectIdentitySurface() {
  const n = navigator, out = {secureContext:isSecureContext};
  for (const k of ['userAgent','appVersion','platform','vendor','product','productSub','language','hardwareConcurrency','deviceMemory','maxTouchPoints','webdriver','pdfViewerEnabled'])
    out[k] = k in n ? n[k] : {absent:true};
  out.languages = [...n.languages];
  out.uaData = n.userAgentData ? {brands:n.userAgentData.brands, mobile:n.userAgentData.mobile, platform:n.userAgentData.platform,
    high:await n.userAgentData.getHighEntropyValues(['architecture','bitness','model','platformVersion','uaFullVersion','fullVersionList','wow64','formFactors'])} : {absent:true};
  out.connection = n.connection ? Object.fromEntries(['effectiveType','type','rtt','downlink','saveData'].map(k=>[k,k in n.connection ? n.connection[k] : {absent:true}])) : {absent:true};
  out.api = Object.fromEntries(['usb','hid','bluetooth','serial','geolocation','credentials','getBattery','permissions','storage','gpu','mediaDevices','serviceWorker','locks'].map(k=>[k,k in n]));
  out.globals = Object.fromEntries(['HTMLDetailsElement','HTMLDialogElement','SerialPort','Bluetooth','USB','GamepadEvent','SharedWorker','WebSocket','RTCPeerConnection','WebAssembly','MutationObserver','AudioContext','OfflineAudioContext','OffscreenCanvas','VideoFrame','ImageDecoder','WebTransport','SharedArrayBuffer','DeviceMotionEvent','DeviceOrientationEvent','Sensor','Accelerometer','Gyroscope','Magnetometer','AmbientLightSensor','process'].map(k=>[k,k in globalThis]));
  out.globalKeys = Object.keys(globalThis).sort();
  out.time = {zone:Intl.DateTimeFormat().resolvedOptions().timeZone, locale:Intl.DateTimeFormat().resolvedOptions().locale,
    // Fixed winter/summer dates separate timezone rules from current time.
    offsets:[new Date('2026-01-15T12:00:00Z').getTimezoneOffset(),new Date('2026-07-15T12:00:00Z').getTimezoneOffset()]};
  out.math = {sin:Math.sin(1e100),cos:Math.cos(1e100),tan:Math.tan(1e100),exp:Math.expm1(1),log:Math.log1p(1),hypot:Math.hypot(1e100,1e100)};
  out.nativeBindings = {};
  for (const k of ['userAgent','platform','hardwareConcurrency','deviceMemory','languages','maxTouchPoints','webdriver']) {
    let p=n, descriptor; while(p && !descriptor){descriptor=Object.getOwnPropertyDescriptor(p,k);p=Object.getPrototypeOf(p)}
    out.nativeBindings[k] = descriptor?.get ? Function.prototype.toString.call(descriptor.get) : null;
  }
  out.permissions = {};
  for (const name of ['geolocation','notifications','camera','microphone','midi','clipboard-read','clipboard-write','background-sync','persistent-storage','accelerometer','gyroscope','magnetometer','ambient-light-sensor','local-fonts','window-management','speaker-selection','storage-access','top-level-storage-access']) {
    try {out.permissions[name]={state:(await n.permissions.query({name})).state}} catch(e){out.permissions[name]={error:e.name}}
  }
  try {const s=await n.storage.estimate();out.storage={quota:s.quota,usage:s.usage,persisted:await n.storage.persisted()}}catch(e){out.storage={error:e.name}}
  if (n.getBattery) {
    try {out.battery=await Promise.race([n.getBattery().then(b=>({charging:b.charging,level:b.level,chargingTime:Number.isFinite(b.chargingTime)?b.chargingTime:'Infinity',dischargingTime:Number.isFinite(b.dischargingTime)?b.dischargingTime:'Infinity'})),new Promise((_,reject)=>setTimeout(()=>reject(Error('timeout')),3000))])}catch(e){out.battery={error:e.name}}
  } else out.battery={absent:true};
  if ('document' in globalThis) {
    const digest=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data))).map(x=>x.toString(16).padStart(2,'0')).join('');
    const c=document.createElement('canvas');c.width=240;c.height=60;const x=c.getContext('2d');
    x.fillStyle='#e9d380';x.fillRect(0,0,240,60);x.fillStyle='#273b83';x.font='17px Arial';x.fillText('MetaBrowser 指纹 0123456789',3,29);x.fillStyle='rgba(180,20,90,.43)';x.fillRect(20,11,88,23);
    out.rendering={canvas:await digest(x.getImageData(0,0,240,60).data.buffer),metrics:['Arial','serif','monospace','sans-serif'].map(font=>{x.font='17px '+font;const m=x.measureText('MetaBrowser 指纹 0123456789');return {font,width:m.width,left:m.actualBoundingBoxLeft,right:m.actualBoundingBoxRight}})};
    const audio=new OfflineAudioContext(1,44100,44100),osc=audio.createOscillator(),compressor=audio.createDynamicsCompressor();osc.type='triangle';osc.frequency.value=10000;osc.connect(compressor);compressor.connect(audio.destination);osc.start(0);
    const buffer=await audio.startRendering(),samples=buffer.getChannelData(0);out.rendering.audio={hash:await digest(samples.buffer),sample:Array.from(samples.slice(4500,4510))};
    out.rendering.webgl={};
    for(const version of ['webgl','webgl2']){
      const canvas=document.createElement('canvas');canvas.width=32;canvas.height=24;const gl=canvas.getContext(version);if(!gl)throw Error(version+' missing');
      gl.clearColor(.25,.5,.75,1);gl.clear(gl.COLOR_BUFFER_BIT);const pixels=new Uint8Array(32*24*4);gl.readPixels(0,0,32,24,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
      const parameters={};for(const key of ['VENDOR','RENDERER','VERSION','SHADING_LANGUAGE_VERSION','MAX_TEXTURE_SIZE','MAX_CUBE_MAP_TEXTURE_SIZE','MAX_RENDERBUFFER_SIZE','MAX_VERTEX_ATTRIBS','MAX_VERTEX_UNIFORM_VECTORS','MAX_VARYING_VECTORS','MAX_FRAGMENT_UNIFORM_VECTORS','MAX_VERTEX_TEXTURE_IMAGE_UNITS','MAX_TEXTURE_IMAGE_UNITS','MAX_COMBINED_TEXTURE_IMAGE_UNITS','RED_BITS','GREEN_BITS','BLUE_BITS','ALPHA_BITS','DEPTH_BITS','STENCIL_BITS','SUBPIXEL_BITS','ALIASED_LINE_WIDTH_RANGE','ALIASED_POINT_SIZE_RANGE','MAX_VIEWPORT_DIMS']){const value=gl.getParameter(gl[key]);parameters[key]=ArrayBuffer.isView(value)?Array.from(value):value}
      const debug=gl.getExtension('WEBGL_debug_renderer_info');if(debug){parameters.unmaskedVendor=gl.getParameter(debug.UNMASKED_VENDOR_WEBGL);parameters.unmaskedRenderer=gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)}
      const precision={};for(const stage of ['VERTEX_SHADER','FRAGMENT_SHADER'])for(const type of ['LOW_FLOAT','MEDIUM_FLOAT','HIGH_FLOAT','LOW_INT','MEDIUM_INT','HIGH_INT']){const value=gl.getShaderPrecisionFormat(gl[stage],gl[type]);precision[stage+':'+type]={rangeMin:value.rangeMin,rangeMax:value.rangeMax,precision:value.precision}}
      out.rendering.webgl[version]={hash:await digest(pixels.buffer),parameters,precision,extensions:gl.getSupportedExtensions(),noError:gl.getError()===gl.NO_ERROR};gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
    out.plugins=[...n.plugins].map(p=>({name:p.name,filename:p.filename,description:p.description,mimes:[...p].map(m=>m.type)}));
    out.mimeTypes=[...n.mimeTypes].map(m=>({type:m.type,suffixes:m.suffixes,plugin:m.enabledPlugin?.name}));
    out.display=Object.fromEntries(['width','height','availWidth','availHeight','availLeft','availTop','colorDepth','pixelDepth'].map(k=>[k,screen[k]]));
    out.window={dpr:devicePixelRatio,innerWidth,innerHeight,outerWidth,outerHeight};
    out.mediaQueries=Object.fromEntries(['(pointer: coarse)','(pointer: fine)','(hover: hover)','(any-pointer: coarse)','(prefers-color-scheme: dark)','(color-gamut: p3)','(dynamic-range: high)'].map(q=>[q,matchMedia(q).matches]));
  }
  return out;
}
