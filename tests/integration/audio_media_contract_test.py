"""Aligned playback negatives, including an independently wrong signal frequency."""
import base64
import copy
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
from audio_media_acceptance import accept

report=json.loads(Path(sys.argv[1]).read_text());accept(report)
def row(r):return r['observations']['rows'][0]
def wrong_tone(r):
 x=row(r);rate=x['destRate'];frequency=x['expectedFrequency']*1.02
 raw=struct.pack('<2048f',*(.1875*math.sin(2*math.pi*i*frequency/rate) for i in range(2048)));values=struct.unpack('<2048f',raw)
 crossings=[i-1-values[i-1]/(values[i]-values[i-1]) for i in range(1,2048) if values[i-1]<=0<values[i]]
 x.update(float32Base64=base64.b64encode(raw).decode(),rms=math.sqrt(sum(v*v for v in values)/2048),peak=max(map(abs,values)),
          crossings=len(crossings),observedFrequency=(len(crossings)-1)*rate/(crossings[-1]-crossings[0]))
mutations=[
 ('incomplete',lambda r:r.update(completed=False)),('missing',lambda r:r['observations']['rows'].pop()),
 ('cleanup',lambda r:r['observations'].update(closedContexts=15)),
 ('output',lambda r:row(r).update(outputGain=1)),('paused',lambda r:row(r).update(paused=True)),
 ('state',lambda r:row(r).update(contextState='suspended')),('media-error',lambda r:row(r).update(mediaError=3)),
 ('rate',lambda r:row(r).update(contextRate=8000)),('activation',lambda r:row(r).update(hadUserActivation=False)),
 ('nan-rms',lambda r:row(r).update(rms=float('nan'))),('capture-bytes',lambda r:row(r).update(float32Base64='AA==')),
 ('silence',lambda r:row(r).update(float32Base64=base64.b64encode(bytes(8192)).decode(),peak=0,rms=0,crossings=0,observedFrequency=0)),
 ('frequency',wrong_tone),
]
for name,mutate in mutations:
 bad=copy.deepcopy(report);mutate(bad)
 with tempfile.TemporaryDirectory(prefix='metabrowser-media-negative-') as directory:
  root=Path(directory);bad['root']=str(root);(root/'.metabrowser-owned-fixture').write_text('persona-metadata')
  (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(bad['observations'])}))
  try:accept(bad)
  except (AssertionError,ValueError,KeyError,TypeError):continue
  raise AssertionError('Accepted corrupt '+name)
print(json.dumps({'rejected_aligned_semantic_mutations':len(mutations),'wrong_tone_updates_full_buffer_and_statistics':True}))
