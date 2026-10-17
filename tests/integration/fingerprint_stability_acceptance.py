"""Verify raw evidence for 100 clean starts of one identity and one engine."""
import argparse
import json
import subprocess
from pathlib import Path
from fingerprint_stability_runner import signature
from identity_surface_runner import digest, validate, validate_passive


def verify(report, directory, framework_sha256, minimum=100):
    assert report.get('completed') is True and report.get('requirement_100_met') is True
    assert type(report.get('paid_model_calls')) is int and report['paid_model_calls']==0
    assert report.get('active_pid') is None and not report.get('error')
    assert report.get('framework_sha256')==framework_sha256
    if report.get('sdk_mode'):
        assert report.get('sdk_mode') is True and report.get('sdk_no_provider_requests') is True
        for key in ('bundle_manifest_sha256','plugin_sha256','sdk_source_manifest_sha256'):
            value=report.get(key);assert isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    rows=report['iterations'];assert type(report['target_count']) is int and len(rows)==report['target_count'] and len(rows)>=minimum
    assert [r['index'] for r in rows]==list(range(1,len(rows)+1))
    assert all(type(r['pid']) is int and r['pid']>0 for r in rows) and len({r['pid'] for r in rows})==len(rows)
    assert len({r['root_secret_sha256'] for r in rows})==1 and len({r['signature'] for r in rows})==1
    previous=0
    paths=set()
    for row in rows:
        assert row['clean_shutdown'] is True and row['matches_first'] is True
        assert type(row['elapsed_seconds']) in (float,int) and row['elapsed_seconds']>previous;previous=row['elapsed_seconds']
        path=Path(row['artifact']);assert path.parent.resolve()==directory.resolve() and not path.is_symlink() and path.is_file()
        assert path.resolve() not in paths;paths.add(path.resolve());assert digest(path)==row['sha256']
        raw=json.loads(path.read_text());assert raw['framework_sha256']==framework_sha256 and raw['iteration']==row['index']
        assert validate(raw['observations'])['consistency_passed'] is True
        assert validate_passive(raw['observations'],True)['passed'] is True
        assert raw.get('stable_signature')==row['signature']
        assert signature(raw['observations'])==row['signature']
    assert set(report.get('probe_sha256',{}))=={
        'tests/integration/fingerprint_stability_runner.py',
        'tests/integration/identity_surface_runner.py',
        'tests/integration/identity_surface_collector.js',
        'tests/integration/identity_surface_probe.mjs'}
    return {'passed':True,'clean_cold_starts':len(rows),'stable_same_identity':True,'real_canvas_audio_webgl':True,'framework_sha256':framework_sha256,'paid_model_calls':0,'full_anonymity_passed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--app',type=Path,required=True);p.add_argument('--sdk-manifest',type=Path);a=p.parse_args()
    r=json.loads(a.report.read_text());framework=a.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    root=Path(__file__).resolve().parents[2]
    if r.get('sdk_mode'):
        assert a.sdk_manifest and digest(a.sdk_manifest)==r['bundle_manifest_sha256']
        assert digest(a.app/'Contents/Frameworks/libmetabrowser_metacodes.dylib')==r['plugin_sha256']
        assert digest(a.app/'Contents/Resources/agentcore/manifest.json')==r['sdk_source_manifest_sha256']
        subprocess.run(['python3',str(root/'scripts/app-manifest.py'),str(a.app),'--check',str(a.sdk_manifest)],check=True,stdout=subprocess.DEVNULL)
    for name,expected in r['probe_sha256'].items():assert digest(root/name)==expected,'Probe changed: '+name
    print(json.dumps(verify(r,a.report.parent,digest(framework)),indent=2))


if __name__=='__main__':main()
