"""Actual media playback and full captured-signal verification, silent graph output."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct


def verify_graphs(data):
    assert data['outputMutedByGraph'] is True and data['real_microphone_requested'] is False
    assert data['closedContexts']==16
    expected={(sr,dr,repeat) for sr in (8000,22050,44100,96000) for dr in (44100,48000) for repeat in (0,1)}
    rows=data['rows'];assert len(rows)==16;seen=set();max_frequency_error=0
    for row in rows:
        key=tuple(row[x] for x in ('sourceRate','destRate','repeat'));assert key in expected and key not in seen;seen.add(key)
        sr,dr,repeat=key
        assert row['contextRate']==dr and row['contextState']=='running'
        assert row['outputGain']==0 and row['paused'] is False and row['readyState']>=2 and row['mediaError'] is None
        assert math.isfinite(row['playbackTime']) and row['playbackTime']>0 and row['hadUserActivation'] is True
        raw=base64.b64decode(row['float32Base64'],validate=True);assert len(raw)==8192
        values=struct.unpack('<2048f',raw)
        assert row['finite'] is True and all(math.isfinite(v) for v in values)
        rms=math.sqrt(sum(v*v for v in values)/len(values));peak=max(map(abs,values))
        assert math.isfinite(row['rms']) and abs(row['rms']-rms)<1e-12 and .12<=rms<=.145
        assert math.isfinite(row['peak']) and row['peak']==peak and .17<=peak<=.21
        crossings=[i-1-values[i-1]/(values[i]-values[i-1]) for i in range(1,len(values)) if values[i-1]<=0<values[i]]
        assert len(crossings)==row['crossings'] and len(crossings)>=2
        frequency=(len(crossings)-1)*dr/(crossings[-1]-crossings[0])
        assert math.isfinite(row['observedFrequency']) and abs(row['observedFrequency']-frequency)<1e-9
        assert row['expectedFrequency']==sr/128
        error=abs(frequency-sr/128)/(sr/128);assert error<=.001;max_frequency_error=max(max_frequency_error,error)
    assert seen==expected
    return {'playback_cases':16,'full_captured_float_values':32768,'closed_contexts':16,
            'max_independent_frequency_relative_error':max_frequency_error,'silent_output':True,
            'microphone_requested':False,'full_realtime_media_chain_proven':False}


def accept(report,probe_dir=None,raw_root=None):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['probe_kind']=='audio-media' and report['paid_model_calls']==0
    assert report['full_scope_complete'] is False
    root=Path(raw_root or report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for p,want in report['probe_sha256'].items():
        source=Path(probe_dir)/Path(p).name if probe_dir else Path(p)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==want,p
    expected_platform='Linux x86_64' if report['persona']=='linux-x86_64-software-v1' else 'MacIntel'
    assert report['observations']['platform']==expected_platform
    return dict(verify_graphs(report['observations']),accepted=True,framework_sha256=report['framework_sha256'],persona=report['persona'],privacy=report['privacy'],full_scope_complete=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--probe-dir',type=Path);p.add_argument('--raw-root',type=Path);a=p.parse_args()
    raw=a.report.read_bytes();result=accept(json.loads(raw),a.probe_dir,a.raw_root);result['report_sha256']=hashlib.sha256(raw).hexdigest();print(json.dumps(result))
