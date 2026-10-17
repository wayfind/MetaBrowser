"""Quota enforcement and rollback must work; denial alone is not a privacy pass."""
import argparse
import hashlib
import json
from pathlib import Path
from identity_surface_runner import digest

CASES = [('normal_small',False,4096,False), ('normal_large',False,8*1024**2,False),
         ('override_pressure',False,8*1024**2,True), ('override_reset',False,8*1024**2,False),
         ('explicit_bucket_small',True,4096,False), ('explicit_bucket_pressure',True,8*1024**2,True)]


def verify(report, framework_sha256):
    assert report['completed'] is True and report['clean_shutdown'] is True
    assert not report.get('error') and report['paid_model_calls'] == 0
    assert report['framework_sha256'] == framework_sha256
    assert report['privacy'] in ('balanced','off')
    raw=report['observations']; assert raw['completed'] is True
    assert len(raw['samples']) == len(CASES)
    checks=0
    for row,(name,bucket,bytes_,pressure) in zip(raw['samples'],CASES):
        assert (row['name'],row['bucket'],row['bytes'],row['pressure']) == (name,bucket,bytes_,pressure)
        assert row['backend']['overrideActive'] is (name=='override_pressure')
        if name=='override_pressure':assert row['backend']['quota'] == 2*1024**2
        origin='http://localhost:18878' if name in ('override_pressure','override_reset') else 'http://127.0.0.1:18878'
        assert row['origin'] == origin
        if name=='override_pressure':assert row['backend']['usage'] == 0
        assert set(row['realms']) == {'window','dedicated'}
        for realm,sample in row['realms'].items():
            assert (sample['realm'],sample['origin'],sample['bytes'],sample['bucket']) == (realm,origin,bytes_,bucket)
            for estimate in (sample['estimate'],sample['afterEstimate']):
                assert estimate['quota']-estimate['usage'] == 10*1024**3
            if bucket:assert sample['bucketEstimate']['quota'] == 2*1024**2
            assert set(sample['stores']) == {'opfs','indexedDB','cacheStorage'}
            for result in sample['stores'].values():
                assert not result.get('unexpectedError'),result
                assert result['deleted'] is True
                if pressure:
                    assert result['write']['completed'] is False,result
                    assert result['write']['error'] == 'QuotaExceededError',result
                    assert (result['size'],result['first']) == (4096,7),result
                else:
                    assert result['write']['completed'] is True,result
                    assert (result['size'],result['first']) == (bytes_,42),result
                expected_data=bytes([7])*4096 if pressure else bytes([42])*bytes_
                assert result['sha256']==hashlib.sha256(expected_data).hexdigest(),result
                checks+=1
    return {'passed':True,'framework_sha256':framework_sha256,'privacy':report['privacy'],
            'checks':checks,'scope':raw['scope'],'full_storage_privacy_proven':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path);p.add_argument('--app',type=Path,required=True)
    args=p.parse_args();report=json.loads(args.report.read_text())
    for filename,sha in report['probe_sha256'].items():assert digest(Path(filename)) == sha
    print(json.dumps(verify(report,digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))


if __name__ == '__main__':main()
