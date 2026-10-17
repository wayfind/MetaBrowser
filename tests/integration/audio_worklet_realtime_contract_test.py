"""Reject realm-clock, lifecycle and coherent realtime sample faults."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_worklet_realtime_acceptance import verify
original=json.loads(Path(sys.argv[1]).read_text())['observations'];verify(original)
mutations=[('rate',lambda o:o['rows'][0]['messages'][0].update(rate=1)),('time',lambda o:o['rows'][0]['messages'][1].update(time=0)),('pause',lambda o:o['rows'][0].update(frozen=False)),('resume',lambda o:o['rows'][0].update(resumed='suspended')),('unmuted',lambda o:o['rows'][0].update(outputGain=1)),('missing-context',lambda o:o['rows'].pop())]
for label,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad)
 except AssertionError:continue
 raise AssertionError(label)
bad=copy.deepcopy(original)
for row in bad['rows']:
 for message in row['messages']:
  message['frame']+=row['rate']*128;message['time']+=128
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Self-consistent future Worklet clock accepted')
bad=copy.deepcopy(original)
for row in bad['rows']:
 raw=struct.pack('<2048f',*([.125]*2048));row.update(float32Base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest())
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Coherent constant realtime samples accepted')
print(json.dumps({'invalid_variants_rejected':len(mutations)+2,'coherent_future_worklet_clock_rejected':True,'coherent_constant_payload_rejected':True,'full_scope_complete':False}))
