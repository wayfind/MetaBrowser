"""Original signature checks reject coherent fake signals, not just stale digests."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
from audio_signature_acceptance import verify_graphs

report=json.loads(Path(sys.argv[1]).read_text());data=report['observations'];verify_graphs(data)
mutations=[('missing',lambda d:d['rows'].pop()),('parameters',lambda d:d['rows'][3]['parameters'].update(knee=30)),
 ('read-repeat',lambda d:d['rows'][0].update(repeatGetSha256='0'*64)),
 ('length',lambda d:d['rows'][0].update(length=5000)),('frequency',lambda d:d['rows'][0].update(frequency=9999)),
 ('sample',lambda d:d['rows'][0]['sample4500to4510'].__setitem__(0,0)),('sum',lambda d:d['rows'][0].update(sumAbsolute4500to5000=0)),
 ('event',lambda d:d['rows'][0].update(eventBufferIdentity=False)),('nan-parameter',lambda d:d['rows'][0]['parameters'].update(attack=float('nan')))]
for label,mutate in mutations:
 bad=copy.deepcopy(data);mutate(bad)
 try:verify_graphs(bad)
 except (AssertionError,ValueError,KeyError):continue
 raise AssertionError(label)
bad=copy.deepcopy(data)
for row in bad['rows']:
 raw=struct.pack('<'+'f'*row['frames'],*([.125]*row['frames']));digest=hashlib.sha256(raw).hexdigest()
 row.update(float32Base64=base64.b64encode(raw).decode(),sha256=digest,copySha256=digest,repeatGetSha256=digest,repeatCopySha256=digest,
            peak=.125,nonzero=row['frames'],sample4500to4510=[.125]*10,sumAbsolute4500to4510=1.25,sumAbsolute4500to5000=62.5)
try:verify_graphs(bad)
except AssertionError:pass
else:raise AssertionError('Coherent constant fake signature accepted')
print(json.dumps({'invalid_variants_rejected':len(mutations)+1,'coherent_constant_payload_and_all_four_hashes_rejected':True}))
