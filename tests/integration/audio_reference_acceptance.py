"""Actual official Linux diagnostic graph data, not exact/default parity."""
import argparse
import json
from pathlib import Path
from audio_vector_acceptance import verify_graphs
from identity_surface_runner import digest


def verify(report,process,prepared):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['probe_kind']=='audio-vector'
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['same_version_baseline_proven'] is False and report['official_default_configuration_proven'] is False
    assert report['hardware_gpu_rendering_proven'] is False and report['full_privacy_proven'] is False
    assert report['reference_version']==prepared['version']=='154.0.8037.92'
    assert report['target_version']==prepared['target_engine_version']=='154.0.8037.97'
    assert prepared['exact_version_match'] is False and not prepared['missing_libraries']
    assert report['reference_executable_sha256']==prepared['executable_sha256']
    assert report['browser_version']=='Chrome/154.0.8037.92'
    assert process['exit_code']==0 and json.loads(process['stdout'])==report['observations']
    assert report['root'].startswith('/tmp/metabrowser-linux-reference-')
    command=report['command']
    for flag in ('--headless=new','--no-sandbox','--disable-gpu','--use-gl=angle','--use-angle=swiftshader',
                 '--use-webgpu-adapter=swiftshader','--disable-accelerated-video-decode',
                 '--disable-accelerated-video-encode','--user-data-dir='+report['root']+'/browser'):
        assert flag in command
    assert not any('metabrowser-persona-template' in flag or flag.startswith('--user-agent=') for flag in command)
    assert report['observations']['platform']=='Linux x86_64'
    # Audio probe did not query the GPU. Do not silently claim a renderer check.
    assert report['software_renderer_verified'] is None
    verify_graphs(report['observations'])
    return {'passed':True,'reference_executable_sha256':report['reference_executable_sha256'],
            'actual_graph_renders':32,'full_channel_hashes':64,'same_version_baseline_proven':False,
            'official_default_configuration_proven':False,'hardware_gpu_rendering_proven':False,
            'full_audio_parity_proven':False,'scope':report['scope']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--process',type=Path,required=True);p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--probe-dir',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(a.probe_dir/Path(f).name)==h
    print(json.dumps(verify(r,json.loads(a.process.read_text()),json.loads(a.prepared.read_text())),indent=2))
