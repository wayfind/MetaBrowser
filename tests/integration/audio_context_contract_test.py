"""Reject invalid realtime traces using an actual, independently captured fixture."""
import copy
import json
from pathlib import Path
import sys
from audio_context_acceptance import verify_graphs

original=json.loads(Path(sys.argv[1]).read_text())['observations']
verify_graphs(original)
mutations=[
 ('missing-context',lambda d:d['rows'].pop()),
 ('duplicate-context',lambda d:d['rows'].__setitem__(1,copy.deepcopy(d['rows'][0]))),
 ('explicit-rate-ignored',lambda d:d['rows'][10]['initial'].update(rate=48000)),
 ('default-option-injected',lambda d:d['rows'][0]['options'].update(sampleRate=48000)),
 ('not-closed',lambda d:d['rows'][0].update(closedState='running')),
 ('not-suspended',lambda d:d['rows'][0]['suspended'].update(state='running')),
 ('nan-latency',lambda d:d['rows'][0]['samples'][1].update(outputLatency=float('nan'))),
 ('negative-latency',lambda d:d['rows'][0]['samples'][1].update(baseLatency=-1)),
 ('future-context-clock',lambda d:d['rows'][0]['samples'][1].update(contextTime=100000)),
 ('reversed-clock',lambda d:d['rows'][0]['samples'][2].update(performanceNow=0)),
 ('unmuted-output',lambda d:d['rows'][0].update(outputGain=1)),
 ('microphone-request',lambda d:d.update(microphoneRequested=True)),
 ('silenced-rendering',lambda d:[s.update(rms=0) for s in d['rows'][0]['samples']]),
]
for label,mutate in mutations:
    bad=copy.deepcopy(original);mutate(bad)
    try:verify_graphs(bad)
    except (AssertionError,ValueError,KeyError):continue
    raise AssertionError('Invalid trace accepted: '+label)
print(json.dumps({'invalid_traces_rejected':len(mutations),'privacy_protection_proven':False}))
