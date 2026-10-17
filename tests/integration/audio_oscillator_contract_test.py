"""Reject corrupted semantic evidence rather than accepting only a digest."""
import copy
import json
import sys
import tempfile
from pathlib import Path
from audio_oscillator_acceptance import accept

report=json.load(open(sys.argv[1]));accept(report)
mutations=[
 ('incomplete',lambda r:r.update(completed=False)),
 ('shutdown',lambda r:r.update(clean_shutdown=False)),
 ('paid',lambda r:r.update(paid_model_calls=1)),
 ('missing',lambda r:r['observations']['rows'].pop()),
 ('duplicate',lambda r:r['observations']['rows'].__setitem__(1,copy.deepcopy(r['observations']['rows'][0]))),
 ('nan',lambda r:r['observations']['rows'][0].update(maxError=float('nan'))),
 ('infinite',lambda r:r['observations']['rows'][0].update(peak=float('inf'))),
 ('wrong-rate',lambda r:r['observations']['rows'][0].update(bufferRate=48000)),
 ('wrong-length',lambda r:r['observations']['rows'][0].update(bufferLength=4095)),
 ('copy',lambda r:r['observations']['rows'][0].update(copySha256='0'*64)),
 ('nonfinite',lambda r:r['observations']['rows'][0].update(finite=False)),
 ('event',lambda r:r['observations']['rows'][0].update(eventBufferIdentity=False)),
 ('analytic',lambda r:r['observations']['rows'][4].update(maxError=0.1)),
 ('silent',lambda r:r['observations']['rows'][4].update(nonzero=0)),
 ('repeat',lambda r:r['observations']['rows'][5].update(sha256='0'*64,copySha256='0'*64)),
]
for name,mutate in mutations:
    bad=copy.deepcopy(report);mutate(bad)
    # Align raw transport with the mutation: rejection must come from semantics,
    # not merely from a stale raw-versus-summary comparison.
    with tempfile.TemporaryDirectory(prefix='metabrowser-oscillator-negative-') as directory:
        root=Path(directory);bad['root']=str(root)
        (root/'.metabrowser-owned-fixture').write_text('persona-metadata')
        (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(bad['observations'])}))
        try:accept(bad)
        except (AssertionError,ValueError,KeyError,TypeError):continue
        raise AssertionError('Accepted corrupt '+name)
print(json.dumps({'rejected_semantic_mutations':len(mutations)}))
