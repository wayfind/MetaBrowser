"""HRTF verifier rejects coherent fake fallback and invalid spatial/linear graphs."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_hrtf_acceptance import verify,verify_trace
report=json.loads(Path(sys.argv[1]).read_text());original=report['observations'];verify(original)
mutations=[('missing-graph',lambda o:o['rows'].pop()),('model',lambda o:o['rows'][0].update(model='equalpower')),('position',lambda o:o['rows'][4].update(position=[0,0,-1])),('event',lambda o:o['rows'][0].update(eventBufferIdentity=False)),('rate',lambda o:o['rows'][0].update(bufferRate=48000)),('digest',lambda o:o['rows'][0]['channels'][0].update(sha256='0'*64))]
for label,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad)
 except AssertionError:continue
 raise AssertionError(label)
for fake in ('zero','equalpower'):
 bad=copy.deepcopy(original)
 for row in bad['rows']:
  values=[0.]*4096
  if fake=='equalpower':
   values[0]=.5
   if row['signal']=='pair':values[1024]=-.25
  raw=struct.pack('<4096f',*values);digest=hashlib.sha256(raw).hexdigest()
  for channel in row['channels']:channel.update(float32Base64=base64.b64encode(raw).decode(),sha256=digest,copySha256=digest)
 try:verify(bad)
 except AssertionError:continue
 raise AssertionError('Coherent fake '+fake+' accepted')
bad=copy.deepcopy(original)
for row in bad['rows']:
 if row['direction']!='front':row['channels'].reverse()
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Opposite directional ears accepted')
bad=copy.deepcopy(original)
for row in bad['rows']:
 if row['direction']!='left' or row['signal']!='pair':continue
 for channel in row['channels']:
  samples=list(struct.unpack('<4096f',base64.b64decode(channel['float32Base64'])));samples[100]+=.001
  raw=struct.pack('<4096f',*samples);digest=hashlib.sha256(raw).hexdigest()
  channel.update(float32Base64=base64.b64encode(raw).decode(),sha256=digest,copySha256=digest)
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Coherent repeat-aligned nonlinear pair accepted')
trace_negatives=0
if 'complexBackendTrace' in original:
 expected=report['persona']=='linux-x86_64-software-v1';verify_trace(original,expected)
 trace_mutations=[('wrong-backend',lambda o:[e.update(portable=not expected) for e in o['complexBackendTrace']]),('missing-stage',lambda o:o['complexBackendTrace'].pop()),('zero-calls',lambda o:o['complexBackendTrace'][0].update(count=0)),('duplicate-stage',lambda o:o['complexBackendTrace'].append(dict(o['complexBackendTrace'][0])))]
 for label,mutate in trace_mutations:
  bad=copy.deepcopy(original);mutate(bad)
  try:verify_trace(bad,expected)
  except AssertionError:trace_negatives+=1;continue
  raise AssertionError(label)
print(json.dumps({'invalid_variants_rejected':len(mutations)+4+trace_negatives,'coherent_zero_and_equalpower_fallback_rejected':True,'full_scope_complete':False}))
