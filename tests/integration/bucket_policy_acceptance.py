"""Bucket metadata controls must not reveal physical storage capacity."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest
from storage_surface_runner import validate,EXPECTED

QUOTAS=[1048576,67108864,1073741824,21474836480,1099511627776,9007199254740991]


def verify(report,framework_sha256):
    assert report['completed'] is True and report['clean_shutdown'] is True and report['volume_detached'] is True
    assert not report.get('error') and report['paid_model_calls']==0
    assert report['framework_sha256']==framework_sha256 and report['privacy'] in ('balanced','off')
    volume=report['volume'];assert volume['different_device_from_host'] and 0<volume['total_bytes']<10*1024**3
    raw=report['observations'];assert raw['phase']=='read';assert validate(raw,False)['passed']
    checks=0
    for key in EXPECTED:
        extra=raw['contexts'][key]['extra'];assert set(extra)=={'window','dedicated'}
        for realm,value in extra.items():
            assert value['realm']==realm
            expected=10*1024**3 if report['privacy']=='balanced' else ((volume['total_bytes']+1024**3-1)//1024**3)*1024**3
            assert value['estimate']['quota']-value['estimate']['usage']==expected
            assert [row['requested'] for row in value['largeQuotas']]==QUOTAS
            for row in value['largeQuotas']:
                assert row['opened'] is True,row
                assert row['estimate']['quota']==row['requested'],row
                checks+=1
            # Chromium does not change an existing bucket's quota via open().
            for field in ('initial','firstAfterReopen','second'):
                assert value['reopen'][field]['quota']==2097152,value['reopen']
                checks+=1
            count=value['count'];assert count['error']=='QuotaExceededError'
            assert count['batchSize']==16 and count['failures']
            assert all(row['opened'] is False and row['error']=='QuotaExceededError' for row in count['failures'])
            assert len({row['key'] for row in count['failures']})==len(count['failures'])
            assert not set(count['created']).intersection(row['key'] for row in count['failures'])
            assert len(set(count['created']))==len(count['created'])
            assert set(count['keysAtLimit'])==set(count['before'])|set(count['created'])
            assert count['afterCleanup']==count['before'] and count['creationRecovers'] is True
            named_total=len(count['before'])+len(count['created'])
            if report['privacy']=='balanced':
                # The fixture has a real default bucket as well as the named
                # buckets; QuotaDatabase includes that default in the count.
                assert named_total+1==512,(key,realm,'capacity-derived bucket limit',named_total+1)
            else:
                assert 1<=named_total+1<256,(key,realm,named_total)
            checks+=1
    return {'passed':True,'framework_sha256':framework_sha256,'privacy':report['privacy'],'checks':checks,
            'scope':'Window/iframe/DedicatedWorker metadata only: six positive quota classes, reopen immutability, bounded bucket count/cleanup/recovery on an owned small APFS volume.',
            'full_storage_privacy_proven':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--app',type=Path,required=True)
    args=p.parse_args();report=json.loads(args.report.read_text())
    for f,sha in report['probe_sha256'].items():assert digest(Path(f))==sha
    print(json.dumps(verify(report,digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))
