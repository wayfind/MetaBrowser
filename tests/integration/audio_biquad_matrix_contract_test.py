"""Mutation tests on real captures; payload/hash coherence is not validation."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_biquad_matrix_acceptance import verify

original=json.loads(Path(sys.argv[1]).read_text())['observations']
verify(original)
mutations=[
 ('missing-graph',lambda d:d['rows'].pop()),
 ('duplicate-type',lambda d:d['rows'][0].update(type='highpass')),
 ('context-rate',lambda d:d['rows'][0].update(bufferRate=1)),
 ('event-identity',lambda d:d['rows'][0].update(eventBufferIdentity=False)),
 ('detune',lambda d:d['rows'][0]['initial'].update(detune=0)),
 ('q',lambda d:d['rows'][0]['initial'].update(q=0)),
 ('change-frame',lambda d:d['rows'][0].update(changeFrame=0)),
 ('response-magnitude',lambda d:d['rows'][0]['response']['magnitude'].__setitem__(1,0)),
 ('response-phase',lambda d:d['rows'][0]['response']['phase'].__setitem__(1,1)),
 ('invalid-frequency',lambda d:d['rows'][0]['response']['magnitude'].__setitem__(7,1)),
]
for name,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad)
 except (AssertionError,ValueError,KeyError):continue
 raise AssertionError('Accepted '+name)

def replace(channel,values):
 raw=struct.pack('<4096f',*values);h=hashlib.sha256(raw).hexdigest()
 channel.update(float32Base64=base64.b64encode(raw).decode(),sha256=h,copySha256=h)

for mode in ('constant-output','frozen-step','coherent-small-bias'):
 bad=copy.deepcopy(original)
 fixed={(r['rate'],r['type'],r['repeat']):r['channels'] for r in bad['rows'] if r['automation']=='fixed'}
 for r in bad['rows']:
  if mode=='frozen-step':
   if r['automation']=='step':r['channels']=copy.deepcopy(fixed[r['rate'],r['type'],r['repeat']])
  else:
   for c in r['channels']:
    values=struct.unpack('<4096f',base64.b64decode(c['float32Base64']))
    replace(c,[.125]*4096 if mode=='constant-output' else [v+1e-5 for v in values])
 try:verify(bad)
 except AssertionError:continue
 raise AssertionError('Accepted '+mode)
bad=copy.deepcopy(original)
for r in bad['rows']:
 response=r['response'];values=list(struct.unpack('<8f',base64.b64decode(response['phaseFloat32Base64'])))
 values[1]+=0.01;raw=struct.pack('<8f',*values);values=list(struct.unpack('<8f',raw))
 response['phaseFloat32Base64']=base64.b64encode(raw).decode();response['phase'][1]=values[1]
try:verify(bad)
except AssertionError:pass
else:raise AssertionError('Accepted coherent phase distortion')
print(json.dumps({'invalid_variants_rejected':len(mutations)+4,'coherent_payload_and_both_hashes_rejected':True,'coherent_phase_distortion_rejected':True,'full_scope_complete':False}))
