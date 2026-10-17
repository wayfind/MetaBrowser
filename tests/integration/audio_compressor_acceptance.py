"""Bounded compressor functional invariants, not cross-CPU DSP equivalence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct


def verify_graphs(data):
    expected_invalid=[(name,label,'TypeError') for name in ('threshold','knee','ratio','attack','release')
                      for label in ('nan','infinity','negative-infinity')]
    assert [(x['name'],x['label'],x['error']) for x in data['invalid']]==expected_invalid
    expected={(rate,setting,signal,repeat) for rate in (8000,44100,96000)
              for setting in ('bypass','default','hard','slow','automated')
              for signal in ('silence','dc','ramp','pulses','noise') for repeat in (0,1)}
    rows=data['rows'];assert len(rows)==len(expected)==150
    keyed={}
    finite=lambda x:type(x) in (int,float) and math.isfinite(x)
    for row in rows:
        key=tuple(row[x] for x in ('rate','setting','signal','repeat'))
        assert key in expected and key not in keyed;keyed[key]=row
        f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
        assert row['delay']==math.floor(f32(f32(.006)*row['rate']))
        assert row['frames']==row['bufferLength']==8192 and row['bufferRate']==row['rate']
        assert row['channelCount']==2 and row['eventBufferIdentity'] is True
        assert finite(row['reduction']) and row['reduction']<=0
        assert finite(row['linkedError']) and 0<=row['linkedError']<=1e-7
        assert len(row['channels'])==2
        for channel in row['channels']:
            assert channel['finite'] is True
            assert re.fullmatch('[0-9a-f]{64}',channel['sha256'])
            assert channel['sha256']==channel['copySha256']
            assert finite(channel['peak']) and channel['peak']>=0
            assert channel['prefixPeak']==0
            assert len(channel['segments'])==8
            assert all(finite(x) and 0<=x<=channel['peak'] for x in channel['segments'])
            if row['setting']=='bypass':
                assert finite(channel['idealDelayError']) and channel['idealDelayError']>=0
            else:assert channel['idealDelayError'] is None
            if row['signal']=='silence':assert channel['peak']==0 and channel['nonzero']==0
            else:assert 7000<=channel['nonzero']<=8192-row['delay'] and channel['peak']>0.001
    assert set(keyed)==expected
    for rate,setting,signal,repeat in expected:
        if repeat:continue
        a=dict(keyed[rate,setting,signal,0]);b=dict(keyed[rate,setting,signal,1])
        a.pop('repeat');b.pop('repeat');assert a==b
    for rate in (8000,44100,96000):
        for signal in ('dc','ramp','pulses','noise'):
            hashes={keyed[rate,s,signal,0]['channels'][0]['sha256'] for s in ('bypass','default','hard','slow','automated')}
            assert len(hashes)==5,'Parameter schedules must affect actual output'
    return {'renders':150,'full_channel_hashes':300,'paired_repeats':75,
            'invalid_nonfinite_param_setters':15,'shared_stereo_gain_passed':True,
            'lookahead_prefix_silent':True,'parameter_schedules_affect_actual_output':True,
            'ratio_one_ideal_delay_error_is_diagnostic_only':True}


def accept(report, probe_dir=None, raw_root=None):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['probe_kind']=='audio-compressor' and report['paid_model_calls']==0
    assert report['full_emulated_persona_proven'] is False and report['full_scope_complete'] is False
    root=Path(raw_root or report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for p,want in report['probe_sha256'].items():
        source=Path(probe_dir)/Path(p).name if probe_dir else Path(p)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==want,p
    assert report['observations']['platform']==('Linux x86_64' if report['persona']=='linux-x86_64-software-v1' else 'MacIntel')
    result=verify_graphs(report['observations'])
    return dict(result,accepted=True,framework_sha256=report['framework_sha256'],persona=report['persona'],privacy=report['privacy'],full_audio_pipeline_cross_cpu_proven=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    parser.add_argument('--probe-dir',type=Path);parser.add_argument('--raw-root',type=Path);args=parser.parse_args()
    raw=args.report.read_bytes();result=accept(json.loads(raw),args.probe_dir,args.raw_root);result['report_sha256']=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result))
