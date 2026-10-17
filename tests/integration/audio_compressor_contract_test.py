"""Mutate aligned raw/summary records to exercise semantic rejection."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from audio_compressor_acceptance import accept

report=json.loads(Path(sys.argv[1]).read_text());accept(report)
def row(r):return r['observations']['rows'][2]
mutations=[
 ('incomplete',lambda r:r.update(completed=False)),
 ('shutdown',lambda r:r.update(clean_shutdown=False)),
 ('paid',lambda r:r.update(paid_model_calls=1)),
 ('missing',lambda r:r['observations']['rows'].pop()),
 ('duplicate',lambda r:r['observations']['rows'].__setitem__(1,copy.deepcopy(r['observations']['rows'][0]))),
 ('exception',lambda r:r['observations']['invalid'][0].update(error=None)),
 ('delay',lambda r:row(r).update(delay=1)),
 ('buffer-rate',lambda r:row(r).update(bufferRate=16000)),
 ('channels',lambda r:row(r).update(channelCount=1)),
 ('event',lambda r:row(r).update(eventBufferIdentity=False)),
 ('nan-reduction',lambda r:row(r).update(reduction=float('nan'))),
 ('positive-reduction',lambda r:row(r).update(reduction=1)),
 ('stereo',lambda r:row(r).update(linkedError=.01)),
 ('copy',lambda r:row(r)['channels'][0].update(copySha256='0'*64)),
 ('nonfinite',lambda r:row(r)['channels'][0].update(finite=False)),
 ('lookahead',lambda r:row(r)['channels'][0].update(prefixPeak=.1)),
 ('silent-signal',lambda r:row(r)['channels'][0].update(nonzero=0)),
 ('nan-statistic',lambda r:row(r)['channels'][0]['segments'].__setitem__(0,float('nan'))),
 ('repeat',lambda r:r['observations']['rows'][3]['channels'][0].update(sha256='0'*64,copySha256='0'*64)),
]
for name,mutate in mutations:
 bad=copy.deepcopy(report);mutate(bad)
 with tempfile.TemporaryDirectory(prefix='metabrowser-compressor-negative-') as directory:
  root=Path(directory);bad['root']=str(root)
  (root/'.metabrowser-owned-fixture').write_text('persona-metadata')
  (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(bad['observations'])}))
  try:accept(bad)
  except (AssertionError,ValueError,KeyError,TypeError):continue
  raise AssertionError('Accepted corrupted '+name)
print(json.dumps({'rejected_aligned_semantic_mutations':len(mutations)}))
