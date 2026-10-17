"""Functional DSP matrix only: no full cross-platform audio parity assertion."""
import argparse
import json
import math
from pathlib import Path
import re
from identity_surface_runner import digest


def verify(report, framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256'] == framework and report['probe_kind'] == 'audio-vector'
    assert type(report['paid_model_calls']) is int and report['paid_model_calls'] == 0
    assert report['full_emulated_persona_proven'] is False and report['full_scope_complete'] is False
    root = Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text() == 'persona-metadata'
    raw = json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code'] == 0 and json.loads(raw['stdout']) == report['observations']
    for flag in ('--user-data-dir='+str(root/'browser'), '--metabrowser-persona-template='+report['persona'],
                 '--metabrowser-privacy='+report['privacy'], '--use-gl=angle', '--use-angle=swiftshader',
                 '--use-webgpu-adapter=swiftshader', '--disable-accelerated-video-decode', '--disable-accelerated-video-encode'):
        assert flag in report['command']
    assert report['privacy'] in ('off','balanced')
    assert report['persona'] in ('linux-x86_64-software-v1','native-macos-arm64-v1')
    data = report['observations']
    assert data['platform'] == ('Linux x86_64' if report['persona']=='linux-x86_64-software-v1' else 'MacIntel')
    verify_graphs(data)
    return {'passed':True,'framework_sha256':framework,'persona':report['persona'],'privacy':report['privacy'],
            'actual_graph_renders':32,'full_channel_hashes':64,'analytic_graph_cases':24,
            'event_copy_consistent':True,'repeat_hashes_stable':True,
            'full_audio_parity_proven':False,'full_scope_complete':False,
            'scope':'Four sample rates, gain/mix/convolution/oscillator-compressor, stereo. FFT/device/realtime/worklet/resampling/HRTF/all inputs/performance and cross-architecture parity remain separate requirements.'}


def verify_graphs(data):
    rows = data['rows']; assert len(rows) == 32
    keys = [(rate,kind,repeat) for rate in (8000,44100,48000,96000) for kind in ('gain','mix','convolution','compressor') for repeat in (0,1)]
    assert [(r['rate'],r['kind'],r['repeat']) for r in rows] == keys
    repeated = {}
    for row in rows:
        assert all(type(row[k]) is int for k in ('rate','repeat','frames','channelCount','bufferRate'))
        assert row['frames'] == 2048 and row['channelCount'] == 2 and row['bufferRate'] == row['rate']
        assert row['duration'] == 2048/row['rate'] and row['eventBufferIdentity'] is True
        assert len(row['channels']) == 2
        for ch, channel in enumerate(row['channels']):
            assert channel['finite'] is True
            assert re.fullmatch('[0-9a-f]{64}', channel['sha256']) and channel['sha256'] == channel['copySha256']
            assert type(channel['nonzero']) is int and 200 < channel['nonzero'] <= 2048
            assert type(channel['peak']) in (int,float) and math.isfinite(channel['peak']) and 0 < channel['peak'] <= 4
            assert len(channel['samples']) == 20 and all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=channel['peak'] for x in channel['samples'])
            if row['kind'] == 'compressor': assert channel['maxError'] is None
            else:
                value = channel['maxError']
                assert type(value) in (int,float) and math.isfinite(value) and 0 <= value <= (2e-5 if row['kind']=='convolution' else 1e-7)
            key = (row['rate'], row['kind'], ch)
            if row['repeat'] == 0: repeated[key] = channel['sha256']
            else: assert repeated[key] == channel['sha256'], key


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--probe-dir',type=Path)
    a = p.parse_args();r = json.loads(a.report.read_text())
    for f,h in r['probe_sha256'].items(): assert digest(a.probe_dir/Path(f).name if a.probe_dir else Path(f)) == h
    print(json.dumps(verify(r,digest(a.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))
