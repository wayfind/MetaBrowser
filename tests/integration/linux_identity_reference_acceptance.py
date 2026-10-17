"""Verify a Linux software diagnostic without converting it to release parity."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest,validate


def verify(report,process,prepared):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['same_version_baseline_proven'] is False
    assert report['official_default_configuration_proven'] is False
    assert report['hardware_gpu_rendering_proven'] is False and report['full_privacy_proven'] is False
    assert report['reference_version']==prepared['version']=='154.0.8037.92'
    assert report['target_version']==prepared['target_engine_version']=='154.0.8037.97'
    assert prepared['exact_version_match'] is False
    assert prepared['version_command_return_code']==0 and not prepared['missing_libraries']
    assert report['reference_executable_sha256']==prepared['executable_sha256']
    assert report['reference_version'] in prepared['version_stdout']
    assert report['browser_version']=='Chrome/'+report['reference_version']
    assert process['exit_code']==0 and json.loads(process['stdout'])==report['observations']
    command=report['command']
    for required in ('--headless=new','--no-sandbox','--disable-gpu','--use-gl=angle',
                     '--use-angle=swiftshader','--use-webgpu-adapter=swiftshader',
                     '--disable-accelerated-video-decode','--disable-accelerated-video-encode'):
        assert required in command
    assert '--user-data-dir='+report['root']+'/browser' in command
    consistency=validate(report['observations'])
    assert consistency==report['consistency'] and consistency['consistency_passed'] is True
    data=report['observations'];assert not data['errors']
    assert set(data['realms'])=={'window','iframe','dedicated','shared','service'}
    for realm,row in data['realms'].items():
        assert row['uaData']['high']['platform']=='Linux'
        assert row['uaData']['high']['architecture']=='x86'
    renderers=[g['parameters']['unmaskedRenderer'] for g in data['realms']['window']['rendering']['webgl'].values()]
    assert len(renderers)==2 and all('SwiftShader' in r for r in renderers)
    assert report['software_renderer_verified'] is True
    return {'diagnostic_collection_verified':True,'reference_executable_sha256':report['reference_executable_sha256'],
            'reference_version':report['reference_version'],'target_version':report['target_version'],
            'realms':5,'http_js_identity_consistency_passed':True,'software_renderer_verified':True,
            'same_version_baseline_proven':False,'official_default_configuration_proven':False,
            'hardware_gpu_rendering_proven':False,'full_privacy_proven':False,'paid_model_calls':0,
            'scope':report['scope']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path);p.add_argument('--process',type=Path,required=True)
    p.add_argument('--prepared',type=Path,required=True);p.add_argument('--probe-dir',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(a.probe_dir/Path(f).name)==h
    print(json.dumps(verify(r,json.loads(a.process.read_text()),json.loads(a.prepared.read_text())),indent=2))
