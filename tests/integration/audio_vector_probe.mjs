import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const origin='http://127.0.0.1:18861';
const trial=process.argv[2]??'audio_vector_trial.js';
assert(['audio_vector_trial.js','audio_fft_trial.js','audio_oscillator_trial.js','audio_compressor_trial.js','audio_resampler_trial.js','audio_media_trial.js','audio_signature_trial.js','audio_context_trial.js','audio_device_trial.js','audio_clock_long_trial.js','audio_worklet_trial.js','audio_worklet_realtime_trial.js','audio_hrtf_trial.js','audio_hrtf_dynamic_trial.js','audio_biquad_matrix_trial.js','audio_biquad_boundary_trial.js'].includes(trial));
const targets=await(await fetch('http://127.0.0.1:18860/json/list')).json();
const target=targets.find(t=>t.type==='page');assert(target?.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18860/'));
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
let id=0;const pending=new Map(),trace=[];let tracingComplete;
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Tracing.dataCollected'){for(const event of m.params.value)trace.push(event);return}if(m.method==='Tracing.tracingComplete'){tracingComplete?.();return}const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.no(Error(m.error.message)):p.ok(m.result)};
const call=(method,params={})=>new Promise((ok,no)=>{const seq=++id,timer=setTimeout(()=>{pending.delete(seq);no(Error(method+' timeout'))},150000);pending.set(seq,{ok,no,timer});ws.send(JSON.stringify({id:seq,method,params}))});
async function evaluate(expression,userGesture=false){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value}
try{
 await call('Page.enable');await call('Page.navigate',{url:origin+'/'});
 for(let n=0;;n++){if(await evaluate(`location.href===${JSON.stringify(origin+'/')}&&document.readyState==='complete'`))break;assert(n<100);await new Promise(r=>setTimeout(r,50))}
 const hrtfTrace=['audio_hrtf_trial.js','audio_hrtf_dynamic_trial.js'].includes(trial);
 const tracing=trial==='audio_clock_long_trial.js'||hrtfTrace;
 if(tracing)await call('Tracing.start',{categories:'audio',transferMode:'ReportEvents'});
 const observation=await evaluate(readFileSync(new URL('./'+trial,import.meta.url),'utf8'),['audio_media_trial.js','audio_context_trial.js','audio_device_trial.js','audio_clock_long_trial.js','audio_worklet_realtime_trial.js'].includes(trial));
 if(tracing){
  let timeout;const complete=new Promise((ok,no)=>{tracingComplete=ok;timeout=setTimeout(()=>no(Error('Owned trace completion timeout')),10000)});
  try{await call('Tracing.end');await complete}finally{clearTimeout(timeout)}
  if(trial==='audio_clock_long_trial.js')observation.silenceTransitions=trace.filter(e=>e.name?.startsWith('SilentSinkSuspender::TransitionSinks')).map(e=>({name:e.name,ts:e.ts,phase:e.ph}));
  if(hrtfTrace){
   const counts=new Map();
   for(const event of trace.filter(e=>e.name==='MetaBrowser HRTF complex backend')){
    assert(typeof event.args?.portable==='boolean');const key=JSON.stringify([event.args.stage,event.args.portable]);counts.set(key,(counts.get(key)??0)+1);
   }
   observation.complexBackendTrace=Array.from(counts,([key,count])=>{const [stage,portable]=JSON.parse(key);return {stage,portable,count}}).sort((a,b)=>a.stage.localeCompare(b.stage));
  }
 }
 console.log(JSON.stringify(observation));
}finally{ws.close();for(const p of pending.values()){clearTimeout(p.timer);p.no(Error('Owned audio probe closed'))}}
