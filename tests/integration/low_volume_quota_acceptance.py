"""A real small APFS volume must not reveal its size through protected estimates."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest
from storage_surface_runner import validate, EXPECTED


def verify(report, framework_sha256):
    assert report['completed'] is True and report['clean_shutdown'] is True
    assert report['volume_detached'] is True
    assert report['framework_sha256']==framework_sha256 and report['paid_model_calls']==0
    volume=report['volume'];assert volume['different_device_from_host'] is True
    total=volume['total_bytes'];assert 0<total<10*1024**3
    assert report['observations']['phase']=='read'
    checked=validate(report['observations'],False);assert checked['passed'],checked
    expected=10*1024**3 if report['privacy']=='balanced' else ((total+1024**3-1)//1024**3)*1024**3
    samples=0
    extra_samples=0
    for key in EXPECTED:
        context=report['observations']['contexts'][key]
        for realm,sample in [('window_or_frame',context),*context['workers'].items()]:
            estimate=sample['estimate'];headroom=estimate['quota']-estimate['usage']
            assert headroom==expected, f'{key}/{realm} reported headroom {headroom}, expected {expected}; owned volume total {total}'
            samples+=1
        extra=context['extra'];assert set(extra)=={'window','dedicated'}
        for realm,signals in extra.items():
            for name in ('estimate','implicitBucket'):
                estimate=signals[name]
                assert estimate['quota']-estimate['usage']==expected,(key,realm,name,estimate,expected)
                extra_samples+=1
            assert signals['explicitBucket']['quota']==2*1024**2
            assert set(signals['legacy'])=={'webkitTemporaryStorage','webkitPersistentStorage'}
            for name,value in signals['legacy'].items():
                if realm=='window':assert value['available'] is True,(key,name,'missing legacy control')
                if value['available']:
                    assert not value.get('error'),value
                    assert value['quota']-value['usage']==expected,(key,realm,name,value,expected)
                    extra_samples+=1
    return {'passed':True,'framework_sha256':framework_sha256,'privacy':report['privacy'],
            'estimate_samples':samples,'extra_estimate_samples':extra_samples,
            'explicit_bucket_quota_preserved':True,
            'real_low_volume':True,'full_storage_privacy_proven':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--app',type=Path,required=True)
    args=p.parse_args();report=json.loads(args.report.read_text())
    for f,sha in report['probe_sha256'].items():assert digest(Path(f))==sha
    print(json.dumps(verify(report,digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))
