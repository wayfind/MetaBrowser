"""Aligned negative records must fail semantic and full-buffer reference checks."""
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
from audio_resampler_acceptance import accept

probe_dir=Path(sys.argv[2]) if len(sys.argv)>2 else None
report=json.loads(Path(sys.argv[1]).read_text());accept(report,probe_dir=probe_dir)
def row(r):return r['observations']['rows'][0]
def corrupt_samples(r):
    target=next(x for x in r['observations']['rows'] if x['sourceRate']==48000 and x['destRate']==48000 and x['frames']==257 and x['signal']=='dc')
    c=target['channels'][0];raw=base64.b64decode(c['float32Base64']);values=list(struct.unpack('<'+'f'*257,raw));values[128]+=.01
    raw=struct.pack('<'+'f'*257,*values);values=struct.unpack('<'+'f'*257,raw)
    c.update(float32Base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),copySha256=hashlib.sha256(raw).hexdigest(),
             sum=sum(values),peak=max(map(abs,values)),peakFrame=128,referenceError=max(abs(v-.25) for v in values[32:-32]))
def corrupt_short_edges(r):
    for target in r['observations']['rows']:
        if (target['sourceRate'],target['destRate'],target['frames'],target['signal'])!=(8000,44100,37,'dc'):continue
        c=target['channels'][0];raw=base64.b64decode(c['float32Base64']);length=len(raw)//4
        values=list(struct.unpack('<'+'f'*length,raw));values[0]+=.01
        raw=struct.pack('<'+'f'*length,*values);values=struct.unpack('<'+'f'*length,raw)
        peak=max(map(abs,values));peak_frame=next(i for i,v in enumerate(values) if abs(v)==peak)
        c.update(float32Base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),copySha256=hashlib.sha256(raw).hexdigest(),
                 sum=sum(values),peak=peak,peakFrame=peak_frame,nonzero=sum(x!=0 for x in values))
mutations=[
 ('incomplete',lambda r:r.update(completed=False)),('paid',lambda r:r.update(paid_model_calls=1)),
 ('missing',lambda r:r['observations']['rows'].pop()),
 ('duplicate',lambda r:r['observations']['rows'].__setitem__(1,copy.deepcopy(r['observations']['rows'][0]))),
 ('format-error',lambda r:r['observations']['invalid'][0].update(error=None)),
 ('input',lambda r:row(r).update(inputSha256='0'*64)),('length',lambda r:row(r).update(length=100)),
 ('rate',lambda r:row(r).update(rate=48000)),('channels',lambda r:row(r).update(channelCount=1)),
 ('detach',lambda r:row(r).update(inputDetached=False)),('callback',lambda r:row(r).update(callbackBufferIdentity=False)),
 ('nonfinite',lambda r:row(r)['channels'][0].update(finite=False)),
 ('copy',lambda r:row(r)['channels'][0].update(copySha256='0'*64)),
 ('peak',lambda r:row(r)['channels'][0].update(peak=0)),
 ('phase',lambda r:row(r)['channels'][0].update(peakFrame=100)),
 ('nan-sum',lambda r:row(r)['channels'][0].update(sum=float('nan'))),
 ('bad-float-bytes',lambda r:row(r)['channels'][0].update(float32Base64='AA==')),
 ('numeric-reference',corrupt_samples),('short-boundary-reference',corrupt_short_edges),
]
for name,mutate in mutations:
 bad=copy.deepcopy(report);mutate(bad)
 with tempfile.TemporaryDirectory(prefix='metabrowser-resampler-negative-') as directory:
  root=Path(directory);bad['root']=str(root);(root/'.metabrowser-owned-fixture').write_text('persona-metadata')
  (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(bad['observations'])}))
  try:accept(bad,probe_dir=probe_dir)
  except (AssertionError,ValueError,KeyError,TypeError):continue
  raise AssertionError('Accepted corrupt '+name)
print(json.dumps({'rejected_aligned_semantic_mutations':len(mutations),'numerical_mutation_rehashes_full_payload_and_statistics':True}))
