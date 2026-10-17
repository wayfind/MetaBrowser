"""Native HTTP/seven-realm metadata only; not complete Linux emulation."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest,validate


def verify(report,framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256']==framework
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_emulated_persona_proven'] is False and report['full_scope_complete'] is False
    assert report['privacy'] in ('balanced','off')
    template=report['persona'];assert template in ('native-macos-arm64-v1','linux-x86_64-software-v1')
    emulated=template=='linux-x86_64-software-v1'
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    command=report['command']
    for flag in ('--user-data-dir='+str(root/'browser'),'--metabrowser-persona-template='+template,
                 '--metabrowser-privacy='+report['privacy'],'--use-gl=angle','--use-angle=swiftshader',
                 '--use-webgpu-adapter=swiftshader','--disable-accelerated-video-decode','--disable-accelerated-video-encode'):
        assert flag in command
    assert not any(s.startswith('--user-agent=') for s in command)
    data=report['observations'];assert validate(data)['consistency_passed'] is True
    assert set(data['realms'])=={'window','iframe','dedicated','shared','service'}
    assert set(data['extraRealms'])=={'module','nested'}
    realms={**data['realms'],**data['extraRealms']};window=realms['window']
    keys=('userAgent','appVersion','platform','hardwareConcurrency','deviceMemory','uaData')
    for realm,row in realms.items():
        assert type(row['hardwareConcurrency']) is int and row['hardwareConcurrency']>0
        assert type(row['deviceMemory']) in (int,float) and row['deviceMemory']>0
        assert {k:row[k] for k in keys}=={k:window[k] for k in keys},realm
        if emulated:
            assert row['platform']=='Linux x86_64'
            assert '(X11; Linux x86_64)' in row['userAgent'] and 'Mac' not in row['userAgent']
            assert row['uaData']['platform']==row['uaData']['high']['platform']=='Linux'
            assert row['uaData']['high']['architecture']=='x86'
            assert row['uaData']['high']['bitness']=='64'
            assert row['uaData']['high']['platformVersion']==''
            assert row['hardwareConcurrency']==8 and row['deviceMemory']==8
        else:
            assert row['platform']=='MacIntel'
            assert row['uaData']['platform']=='macOS'
            assert row['uaData']['high']['architecture']=='arm'
        if realm in ('module','nested'):
            assert row['actualGlobal']=='DedicatedWorkerGlobalScope' and row['platformNative'] is True
            assert row['location'].startswith('blob:http://127.0.0.1:18861/')
            if realm=='module':assert row['moduleUrl']==row['location']
            else:
                assert row['nestedParentGlobal']=='DedicatedWorkerGlobalScope'
                assert row['nestedParentLocation'].startswith('blob:http://127.0.0.1:18861/')
                assert row['nestedParentLocation']!=row['location']
    headers={k.lower():v for k,v in data['headers']['headers']}
    assert headers['user-agent']==window['userAgent']
    assert headers['sec-ch-ua-platform'].strip('"')==('Linux' if emulated else 'macOS')
    assert headers['sec-ch-ua-arch'].strip('"')==('x86' if emulated else 'arm')
    assert headers['sec-ch-ua-bitness'].strip('"')=='64'
    if emulated:assert headers.get('sec-ch-ua-platform-version','').strip('"')==''
    memory_headers=[headers[name] for name in ('device-memory','sec-ch-device-memory') if name in headers]
    assert memory_headers and all(float(value)==window['deviceMemory'] for value in memory_headers)
    assert data['nativePersonaGetters']==dict.fromkeys(('platform','hardwareConcurrency','deviceMemory'),True)
    assert [r['requested'] for r in data['cpuTrace']]==[8,4,1,8]
    expected_tier={1:1,4:2,8:3 if emulated else 4}
    for row in data['cpuTrace']:
        assert type(row['requested']) is int
        for realm in ('window','iframe'):
            observed=row['observed'][realm]
            assert type(observed['cores']) is int and type(observed['tier']) is int
            assert observed['cores']==row['requested'] and observed['tier']==expected_tier[row['requested']]
            assert observed['platform']==window['platform'] and observed['memory']==window['deviceMemory']
        retained=row['observed']['retained']
        assert type(retained['tier']) is int
        # Inspector overrides can stop applying when the owner frame is gone.
        # Either way, the retained object's tier must match its public cores,
        # and emulation must not fall back to the Mac platform or Apple tier.
        assert type(retained['cores']) is int and retained['cores'] in (row['requested'],8)
        assert retained['tier']==expected_tier[retained['cores']]
        assert retained['platform']==window['platform'] and retained['memory']==window['deviceMemory']
    gpu=data['nativeGpuInfo'];assert gpu['devices']
    assert 'SwiftShader' in gpu['auxAttributes']['glRenderer']
    renderers=[v['parameters'].get('unmaskedRenderer') for v in window['rendering']['webgl'].values()]
    assert len(renderers)==2
    if report['privacy']=='off':assert all(isinstance(v,str) and 'SwiftShader' in v for v in renderers)
    else:assert all(v is None for v in renderers)
    return {'passed':True,'framework_sha256':framework,'persona':template,'privacy':report['privacy'],
            'metadata_realms':7,'http_js_metadata_consistent':True,'memory_hints_consistent':True,
            'cpu_override_states':4,'retained_metadata_coherent':True,'native_getters':True,
            'software_webgl_verified':True,'full_emulated_persona_proven':False,'full_scope_complete':False,
            'scope':'Explicit diagnostic metadata cohort only. Not complete Linux fonts/Math/media/API surface/GPU parity or validated user-selectable profile.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--probe-dir',type=Path)
    args=p.parse_args();r=json.loads(args.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(args.probe_dir/Path(f).name if args.probe_dir else Path(f))==h
    frame=digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    print(json.dumps(verify(r,frame),indent=2))
