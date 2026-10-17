"""Reject coherent, raw-aligned bad clock data and the actual previous engine."""
import copy,json
from pathlib import Path
import shutil,sys,tempfile
from audio_clock_acceptance import compare

root=Path(sys.argv[1]);archives=root/'privacy-v20j-context-archives'
reports=[json.loads((root/f'audio-context-v20j-{mode}.private.json').read_text()) for mode in ('scalar-off','scalar-buffer512')]
compare(*reports,archives)
mutations=[
 ('zero-output-latency',lambda d:[s.update(outputLatency=0) for r in d['observations']['rows'] for s in r['samples']]),
 ('extra-device-delay',lambda d:[s.update(outputLatency=s['outputLatency']+.008) for r in d['observations']['rows'] for s in r['samples']]),
 ('future-clock',lambda d:d['observations']['rows'][0]['samples'][1].update(contextTime=1e6)),
 ('reversed-performance-clock',lambda d:d['observations']['rows'][0]['samples'][2].update(performanceNow=0)),
]
with tempfile.TemporaryDirectory(prefix='metabrowser-clock-contract-') as temp:
 archive=Path(temp)/'archives';shutil.copytree(archives,archive)
 for label,mutate in mutations:
  bad=copy.deepcopy(reports);mutate(bad[0])
  p=archive/'scalar-off/probe-process.private.json';raw=json.loads(p.read_text());raw['stdout']=json.dumps(bad[0]['observations']);p.write_text(json.dumps(raw))
  try:compare(*bad,archive)
  except AssertionError:continue
  raise AssertionError('Aligned bad clock accepted: '+label)
old=[json.loads((root/f'audio-context-v20i-{mode}.private.json').read_text()) for mode in ('scalar-off','scalar-buffer512')]
try:compare(*old,root/'privacy-v20i-context-archives')
except AssertionError:pass
else:raise AssertionError('Old physical-clock engine accepted')
print(json.dumps({'raw_aligned_invalid_variants_rejected':len(mutations),'actual_old_engine_rejected':True,'full_scope_complete':False}))
