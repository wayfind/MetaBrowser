"""Validate owned realtime metadata traces; validation does not prove protection."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def verify_graphs(data):
    assert data['closedContexts']==30 and data['syntheticSignalOnly'] is True
    assert data['outputMutedByGraph'] is True and data['microphoneRequested'] is False
    expected={(rate,hint,repeat) for rate in (None,44100,48000) for hint in (None,'interactive','balanced','playback',.1) for repeat in (0,1)}
    rows=data['rows'];assert len(rows)==30;seen=set()
    for row in rows:
        key=tuple(row[k] for k in ('requestedRate','requestedHint','repeat'))
        assert key in expected and key not in seen;seen.add(key);rate,hint,_=key
        options={}
        if rate is not None:options['sampleRate']=rate
        if hint is not None:options['latencyHint']=hint
        assert row['options']==options
        assert row['outputGain']==0 and row['closedState']=='closed' and row['suspended']['state']=='suspended'
        snapshots=[row['initial'],*row['samples'],row['suspended']];assert len(row['samples'])==3
        rates={s['rate'] for s in snapshots};assert len(rates)==1
        actual=next(iter(rates));assert type(actual) in (int,float) and 3000<=actual<=384000
        if rate is not None:assert actual==rate
        assert len({s['baseLatency'] for s in snapshots})==1
        for s in snapshots:
            for name in ('rate','baseLatency','outputLatency','currentTime','contextTime','performanceTime','performanceNow'):
                assert type(s[name]) in (int,float) and math.isfinite(s[name]) and s[name]>=0
            assert s['contextTime']<=s['currentTime']+1e-9
        for earlier,later in zip(row['samples'],row['samples'][1:]):
            assert later['performanceNow']>earlier['performanceNow'] and later['currentTime']>=earlier['currentTime'] and later['contextTime']>=earlier['contextTime']
        for s in row['samples']:
            assert s['state']=='running' and s['finite'] is True and math.isfinite(s['rms']) and 0<=s['rms']<=1
        assert any(s['rms']>.01 for s in row['samples'])
    assert seen==expected
    return {'functional_trace_passed':True,'contexts':30,'running_samples':90,'closed_contexts':30,'privacy_protection_proven':False,'full_scope_complete':False}


def accept(report,probe_dir=None,raw_root=None):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['probe_kind']=='audio-context' and report['paid_model_calls']==0
    root=Path(raw_root or report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for name,want in report['probe_sha256'].items():
        p=Path(probe_dir)/Path(name).name if probe_dir else Path(name)
        assert hashlib.sha256(p.read_bytes()).hexdigest()==want,name
    return dict(verify_graphs(report['observations']),framework_sha256=report['framework_sha256'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--probe-dir',type=Path);p.add_argument('--raw-root',type=Path);a=p.parse_args()
    result=accept(json.loads(a.report.read_text()),a.probe_dir,a.raw_root);result['report_sha256']=hashlib.sha256(a.report.read_bytes()).hexdigest();print(json.dumps(result))
