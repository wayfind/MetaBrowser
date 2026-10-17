"""Real paired captures: invalid equal data and single-ULP differences must not pass."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
from audio_pipeline_cross_acceptance import compare,sha

E=Path('out/evidence')
mac=json.loads((E/'audio-resampler-v20h-linux-off.private.json').read_text())
linux=json.loads((E/'audio-resampler-v20h-patched-linux-scalar.private.json').read_text())
mr=E/'privacy-v20h-engine-receipts/receipt.json';lr=E/'privacy-v20h-linux-build-receipt.json'
mreceipt=json.loads(mr.read_text());lreceipt=json.loads(lr.read_text())

def invoke(m,l,mc,lc):
 with tempfile.TemporaryDirectory(prefix='metabrowser-cross-negative-') as directory:
  root=Path(directory);macroot=root/'mac';linuxroot=root/'linux';macroot.mkdir();linuxroot.mkdir()
  for report,target,marker in [(m,macroot,'persona-metadata'),(l,linuxroot,'patched-linux-audio-reference')]:
   (target/'.metabrowser-owned-fixture').write_text(marker)
   (target/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(report['observations'])}))
  for file in (E/'privacy-v20h-patched-linux-resampler-raw').glob('renderer-launch-*.json'):shutil.copy2(file,linuxroot/file.name)
  return compare(m,l,mc,lc,sha(mr),sha(lr),macroot,linuxroot,E/'privacy-v20h-resampler-probes',E/'privacy-v20h-linux-qa-r4')

assert invoke(mac,linux,mreceipt,lreceipt)['fixture_buffers_identical'] is True
mutations=[
 ('incomplete',lambda m,l,mc,lc:l.update(completed=False)),
 ('wrong-backend',lambda m,l,mc,lc:l.update(backend='native')),
 ('unfinished-build',lambda m,l,mc,lc:lc.update(state='building')),
 ('parent',lambda m,l,mc,lc:lc.update(parent_receipt_sha256='0'*64)),
 ('source',lambda m,l,mc,lc:lc['source_sha256'].pop(next(iter(lc['source_sha256'])))),
 ('binary',lambda m,l,mc,lc:l.update(engine_sha256='0'*64)),
 ('no-renderer',lambda m,l,mc,lc:l.update(renderer_transport=[])),
 ('forged-title',lambda m,l,mc,lc:l['renderer_transport'][0]['raw_proc_arguments'].__setitem__(0,'forged')),
]
for name,mutate in mutations:
 args=[copy.deepcopy(x) for x in (mac,linux,mreceipt,lreceipt)];mutate(*args)
 try:invoke(*args)
 except (AssertionError,KeyError,ValueError):continue
 raise AssertionError('Accepted '+name)

def payload(report,zero=False):
 for row in report['observations']['rows'][:2]:
  c=row['channels'][0];raw=base64.b64decode(c['float32Base64']);n=len(raw)//4
  if zero:raw=bytes(len(raw))
  else:
   words=list(struct.unpack('<'+'I'*n,raw));words[0]+=1;raw=struct.pack('<'+'I'*n,*words)
  values=struct.unpack('<'+'f'*n,raw);peak=max(map(abs,values))
  c.update(float32Base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),copySha256=hashlib.sha256(raw).hexdigest(),
           sum=sum(values),peak=peak,peakFrame=next(i for i,v in enumerate(values) if abs(v)==peak),nonzero=sum(v!=0 for v in values))
a,b=copy.deepcopy(mac),copy.deepcopy(linux);payload(a,True);payload(b,True)
try:invoke(a,b,mreceipt,lreceipt)
except AssertionError:pass
else:raise AssertionError('Identical invalid zero buffers accepted')
b=copy.deepcopy(linux);payload(b)
r=invoke(mac,b,mreceipt,lreceipt)
assert not r['fixture_buffers_identical'] and r['functional_checks_passed'] and r['hashes_equal']==478
print(json.dumps({'binding_and_transport_negatives_rejected':len(mutations),'equal_invalid_buffers_rejected':True,
                  'aligned_single_ulp_changes_reported':True,'synthetic_changes_are_not_browser_observations':True}))
