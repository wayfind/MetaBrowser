"""Reject coherent moving-HRTF failures, not merely stale sample hashes."""
import base64,copy,hashlib,json,struct,sys
from pathlib import Path
from audio_hrtf_dynamic_acceptance import verify
report=json.loads(Path(sys.argv[1]).read_text());original=report['observations'];portable=report['persona']=='linux-x86_64-software-v1';verify(original,portable)
mutations=[('missing',lambda o:o['rows'].pop()),('event',lambda o:o['rows'][0].update(eventBufferIdentity=False)),('bad-rate',lambda o:o['rows'][0].update(bufferRate=1)),('backend',lambda o:o['complexBackendTrace'][0].update(portable=not portable))]
for label,mutate in mutations:
 bad=copy.deepcopy(original);mutate(bad)
 try:verify(bad,portable)
 except AssertionError:continue
 raise AssertionError(label)

def update(channel,values):
 raw=struct.pack('<8192f',*values);digest=hashlib.sha256(raw).hexdigest()
 channel.update(float32Base64=base64.b64encode(raw).decode(),sha256=digest,copySha256=digest)

for mode in ('frozen-motion','nonlinear-gain','premature-motion','constant-output'):
 bad=copy.deepcopy(original)
 baseline={(r['rate'],r['scale'],r['repeat']):r for r in bad['rows'] if r['motion']=='static'}
 for row in bad['rows']:
  if mode=='frozen-motion' and row['motion']!='static':row['channels']=copy.deepcopy(baseline[row['rate'],row['scale'],row['repeat']]['channels']);continue
  for channel in row['channels']:
   values=list(struct.unpack('<8192f',base64.b64decode(channel['float32Base64'])))
   if mode=='nonlinear-gain' and row['scale']==.5:values=[v*1.001 for v in values]
   if mode=='premature-motion' and row['motion']!='static':values[:100]=[v+.0001*row['scale'] for v in values[:100]]
   if mode=='constant-output':values=[.125*row['scale']]*8192
   update(channel,values)
 try:verify(bad,portable)
 except AssertionError:continue
 raise AssertionError('Coherent '+mode+' accepted')
print(json.dumps({'invalid_variants_rejected':len(mutations)+4,'coherent_motion_gain_causality_and_signal_fakes_rejected':True,'full_scope_complete':False}))
