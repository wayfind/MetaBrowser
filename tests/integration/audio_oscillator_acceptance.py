"""Bounded oscillator analytical/repeat checks; no whole audio portability claim."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def accept(report):
    assert report['completed'] is True and report['clean_shutdown'] is True
    assert report['probe_kind']=='audio-oscillator' and report['paid_model_calls']==0
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    assert report['observations']['platform']==('Linux x86_64' if report['persona']=='linux-x86_64-software-v1' else 'MacIntel')
    for name,want in report['probe_sha256'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==want,name
    rows=report['observations']['rows']
    expected={(rate,mode,variant,repeat) for rate in (22050,44100,96000)
              for mode in ('constant','frequency-a-rate','detune-a-rate')
              for variant in ('zero','low','positive','negative','octave','fractional')
              for repeat in (0,1)}
    assert len(rows)==len(expected)==108
    keyed={}
    for row in rows:
        key=tuple(row[k] for k in ('rate','mode','variant','repeat'))
        assert key in expected and key not in keyed
        keyed[key]=row
        assert row['frames']==row['bufferLength']==4096 and row['bufferRate']==row['rate']
        assert row['finite'] is True and row['eventBufferIdentity'] is True
        for name in ('sha256','copySha256'):
            assert isinstance(row[name],str) and len(row[name])==64
            int(row[name],16)
        assert row['sha256']==row['copySha256']
        for name in ('maxError','rmsError','peak'):
            assert type(row[name]) in (float,int) and math.isfinite(row[name]) and row[name]>=0
        assert row['rmsError']<=row['maxError']<= (0.0002 if row['variant']=='fractional' else 0.00001)
        assert row['peak']<=1.000001
        if row['variant']=='zero':assert row['nonzero']==0 and row['peak']==0
        else:assert 3900<=row['nonzero']<=4096 and row['peak']>0.2
    assert set(keyed)==expected
    for rate,mode,variant,repeat in expected:
        if repeat:continue
        left=dict(keyed[rate,mode,variant,0]);right=dict(keyed[rate,mode,variant,1])
        left.pop('repeat');right.pop('repeat');assert left==right
    return {'accepted':True,'renders':108,'paired_repeats':54,
            'max_error':max(row['maxError'] for row in rows),
            'full_audio_pipeline_cross_cpu_proven':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    args=parser.parse_args();raw=args.report.read_bytes();result=accept(json.loads(raw))
    result['report_sha256']=hashlib.sha256(raw).hexdigest();print(json.dumps(result))


if __name__=='__main__':main()
