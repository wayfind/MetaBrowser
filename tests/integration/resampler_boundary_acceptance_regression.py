"""Demonstrate old short-buffer reference gap and the full-response fix."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from audio_resampler_acceptance import accept

source=Path(sys.argv[1]);probes=Path(sys.argv[2]);old_path=probes/'audio_resampler_acceptance.before_full_response.py'
spec=importlib.util.spec_from_file_location('old_resampler_acceptance',old_path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
report=json.loads(source.read_text());bad=copy.deepcopy(report)
for row in bad['observations']['rows']:
 if (row['sourceRate'],row['destRate'],row['frames'],row['signal'])!=(8000,44100,37,'dc'):continue
 c=row['channels'][0];raw=base64.b64decode(c['float32Base64']);n=len(raw)//4;values=list(struct.unpack('<'+'f'*n,raw));values[0]+=.01
 raw=struct.pack('<'+'f'*n,*values);values=struct.unpack('<'+'f'*n,raw);peak=max(map(abs,values))
 c.update(float32Base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),copySha256=hashlib.sha256(raw).hexdigest(),
          sum=sum(values),peak=peak,peakFrame=next(i for i,v in enumerate(values) if abs(v)==peak),nonzero=sum(x!=0 for x in values))
with tempfile.TemporaryDirectory(prefix='metabrowser-short-edge-regression-') as directory:
 root=Path(directory);bad['root']=str(root);(root/'.metabrowser-owned-fixture').write_text('persona-metadata')
 (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(bad['observations'])}))
 assert old.accept(bad,probe_dir=probes)['accepted'] is True
 try:accept(bad,probe_dir=probes)
 except AssertionError:pass
 else:raise AssertionError('New verifier accepted a wrong short-buffer edge')
print(json.dumps({'old_verifier_accepts_aligned_bad_short_edges':True,'new_full_response_verifier_rejects_bad_short_edges':True,
                  'both_repeats_payload_hashes_and_statistics_aligned':True,'old_verifier_sha256':hashlib.sha256(old_path.read_bytes()).hexdigest()}))
