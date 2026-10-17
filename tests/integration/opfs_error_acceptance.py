"""Strict native quota errors, full rollback hashes and bounded cancellation."""
import argparse
import hashlib
import json
from pathlib import Path
from identity_surface_runner import digest

CASES=[(realm,kind,scenario) for realm in ('window','dedicated')
       for kind,scenario in (('array','quota'),('blob','quota'),('string','quota'),
                             ('array','cancel'),('array','delete_inflight'))]


def verify(report,framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256']==framework
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_storage_privacy_proven'] is False and report['privacy'] in ('balanced','off')
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='opfs-errors'
    process=json.loads((root/'probe-process.private.json').read_text())
    assert process['exit_code']==0 and json.loads(process['stdout'])==report['observations']
    data=report['observations'];assert data['completed'] is True and type(data['paid_model_calls']) is int and data['paid_model_calls']==0
    assert len(data['rows'])==len(CASES)
    old=hashlib.sha256(bytes([7])*4096).hexdigest()
    recovered=hashlib.sha256(bytes([21])*4096).hexdigest()
    for row,expected in zip(data['rows'],CASES):
        assert (row['realm'],row['kind'],row['scenario'])==expected
        assert row['completed'] is True and row['origin']=='http://127.0.0.1:18878'
        assert row['recovered']=={'bytes':4096,'sha256':recovered}
        if row['scenario']=='quota':
            assert row['write']['completed'] is False
            assert row['write']['error']=='QuotaExceededError',row
            assert row['write']['stage']=='write'
        elif row['scenario']=='cancel':
            assert row['cancelled'] is True and 'write' not in row
        else:
            write=row['write'];assert type(write['completed']) is bool
            if not write['completed']:
                assert write['error'] in ('NotFoundError','InvalidStateError','AbortError')
                assert write['stage'] in ('write','close')
        if row['scenario']!='delete_inflight':
            assert row['retained']=={'bytes':4096,'sha256':old}
    return {'passed':True,'framework_sha256':framework,'privacy':report['privacy'],
            'cases':len(CASES),'strict_quota_errors':6,'cancel_rollback_cases':2,
            'inflight_deletion_settlement_cases':2,'full_content_hashes_checked':18,
            'disconnect_default_callback_observed':any(r.get('write',{}).get('message')=='File writer disconnected' for r in data['rows']),
            'scope':'Owned explicit buckets in Window/DedicatedWorker; three payload types. No arbitrary shutdown/failure, physical disk exhaustion or full API privacy claim.',
            'full_storage_privacy_proven':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--probe-dir',type=Path)
    args=p.parse_args();r=json.loads(args.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(args.probe_dir/Path(f).name if args.probe_dir else Path(f))==h
    framework=digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    print(json.dumps(verify(r,framework),indent=2))
