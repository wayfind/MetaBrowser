"""Reject wrong degenerate branches even when payload and both hashes agree."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_biquad_boundary_acceptance import verify

original=json.loads(Path(sys.argv[1]).read_text())['observations'];verify(original)
mutations=[
 ('missing',lambda d:d['rows'].pop()),
 ('wrong-boundary',lambda d:d['rows'][0].update(boundary='q-zero')),
 ('parameters',lambda d:d['rows'][0]['parameters'].__setitem__(0,1)),
 ('rate',lambda d:d['rows'][0].update(bufferRate=1)),
 ('length',lambda d:d['rows'][0].update(length=128)),
 ('event',lambda d:d['rows'][0].update(eventBufferIdentity=False)),
 ('microphone',lambda d:d.update(microphoneRequested=True)),
]
for name,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad)
 except (AssertionError,ValueError,KeyError):continue
 raise AssertionError('Accepted '+name)
for defect in ('all-zero','non-finite','bandpass-q0-zero','allpass-q0-positive'):
 bad=copy.deepcopy(original)
 for r in bad['rows']:
  if defect=='bandpass-q0-zero' and (r['type'],r['boundary'])!=('bandpass','q-zero'):continue
  if defect=='allpass-q0-positive' and (r['type'],r['boundary'])!=('allpass','q-zero'):continue
  for c in r['channels']:
   if defect=='allpass-q0-positive':values=[-v for v in struct.unpack('<1024f',base64.b64decode(c['float32Base64']))]
   else:values=[float('nan') if defect=='non-finite' else 0]*1024
   raw=struct.pack('<1024f',*values);h=hashlib.sha256(raw).hexdigest();c.update(float32Base64=base64.b64encode(raw).decode(),sha256=h,copySha256=h)
 try:verify(bad)
 except AssertionError:continue
 raise AssertionError('Accepted '+defect)
print(json.dumps({'invalid_variants_rejected':len(mutations)+4,'coherent_wrong_branch_payloads_rejected':True,'full_scope_complete':False}))
