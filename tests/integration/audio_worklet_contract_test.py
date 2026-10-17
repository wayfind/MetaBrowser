"""Independent Worklet verifier rejects coherent signal and realm metadata faults."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_worklet_acceptance import verify
original=json.loads(Path(sys.argv[1]).read_text())['observations'];verify(original)
mutations=[('missing-graph',lambda o:o['rows'].pop()),('scope-rate',lambda o:o['rows'][0]['messages'][0].update(rate=48000)),('scope-frame',lambda o:o['rows'][0]['messages'][2].update(frame=0)),('scope-time',lambda o:o['rows'][0]['messages'][2].update(time=0)),('param-transport',lambda o:o['rows'][2]['messages'][0].update(gainFirst=0)),('filter-param',lambda o:o['rows'][4]['settings'].update(detune=0)),('spatial-param',lambda o:o['rows'][6]['settings'].update(rolloff=1)),('event-buffer',lambda o:o['rows'][0].update(eventBufferIdentity=False))]
for label,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad)
 except (AssertionError,KeyError,ValueError):continue
 raise AssertionError(label)
# Keep both read hashes and full payload coherent, but replace actual output.
bad=copy.deepcopy(original)
for row in bad['rows']:
 for channel in row['channels']:
  raw=struct.pack('<2048f',*([.125]*2048));digest=hashlib.sha256(raw).hexdigest()
  channel.update(sha256=digest,copySha256=digest,float32Base64=base64.b64encode(raw).decode())
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Coherent fake Worklet output accepted')
# A small, coherent spatial bias must not disappear inside a broad DSP budget.
bad=copy.deepcopy(original)
for row in bad['rows']:
 if row['kind']!='spatial':continue
 for channel in row['channels']:
  values=struct.unpack('<2048f',base64.b64decode(channel['float32Base64']))
  raw=struct.pack('<2048f',*[v+5e-7 for v in values]);digest=hashlib.sha256(raw).hexdigest()
  channel.update(sha256=digest,copySha256=digest,float32Base64=base64.b64encode(raw).decode())
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Coherent spatial bias accepted')
print(json.dumps({'invalid_variants_rejected':len(mutations)+2,'coherent_payload_and_both_hashes_rejected':True,'full_scope_complete':False}))
