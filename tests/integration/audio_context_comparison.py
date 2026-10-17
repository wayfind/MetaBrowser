"""Measure device-buffer exposure; this is a diagnostic, not a privacy pass gate."""
import argparse
import hashlib
import json
from pathlib import Path
from audio_context_acceptance import accept


def compare(paths, archives):
    reports={mode:json.loads(path.read_text()) for mode,path in paths.items()}
    validations={mode:accept(report,archives/mode/'inputs',archives/mode) for mode,report in reports.items()}
    assert len({r['framework_sha256'] for r in reports.values()})==1
    assert reports['scalar-buffer512']['requested_audio_buffer_size']==512
    assert '--audio-buffer-size=512' in reports['scalar-buffer512']['command']
    def index(report):
        return {(r['requestedRate'],r['requestedHint'],r['repeat']):r for r in report['observations']['rows']}
    rows={mode:index(report) for mode,report in reports.items()}
    details=[]
    for key in rows['scalar-off']:
        values={mode:{'rate':r[key]['samples'][-1]['rate'],
                      'base_latency':r[key]['samples'][-1]['baseLatency'],
                      'output_latency':r[key]['samples'][-1]['outputLatency'],
                      'clock_gap':r[key]['samples'][-1]['currentTime']-r[key]['samples'][-1]['contextTime']}
                for mode,r in rows.items()}
        details.append({'requested_rate':key[0],'requested_hint':key[1],'repeat':key[2],'values':values,
                        'buffer_changes_base_latency':values['scalar-off']['base_latency']!=values['scalar-buffer512']['base_latency'],
                        'scalar_native_same_rate_and_base':all(values['scalar-off'][field]==values['native-off'][field] for field in ('rate','base_latency'))})
    return {'functional_validations':validations,
            'reports':{mode:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for mode,p in paths.items()},
            'contexts':90,'running_samples':270,
            'buffer_changes_base_latency_cases':sum(r['buffer_changes_base_latency'] for r in details),
            'scalar_native_same_rate_and_base_cases':sum(r['scalar_native_same_rate_and_base'] for r in details),
            'privacy_protection_proven':False,'unique_device_identification_proven':False,
            'full_scope_complete':False,'cases':details}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,default=Path('out/evidence'))
    a=p.parse_args();modes=('scalar-off','native-off','scalar-buffer512')
    paths={mode:a.evidence/f'audio-context-v20h-{mode}.private.json' for mode in modes}
    print(json.dumps(compare(paths,a.evidence/'privacy-v20h-context-archives'),indent=2))
