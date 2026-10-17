"""Real realm identities and exact payload hashes, not success counters."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from identity_surface_runner import digest

REALMS=['window','iframe','dedicated','module','nested','shared','service']
KINDS=['uint8','arraybuffer','offset_uint8','dataview','blob','string']
CASES=[(realm,kind,scenario) for realm in REALMS for kind,scenario in
       ([(kind,'quota') for kind in KINDS]+[('uint8','cancel'),('uint8','delete_inflight')])]
ORIGIN='http://127.0.0.1:18878'


def verify(report,framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256']==framework and report['matrix']=='seven'
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_storage_privacy_proven'] is False and report['privacy'] in ('balanced','off')
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='opfs-errors'
    process=json.loads((root/'probe-process.private.json').read_text())
    assert process['exit_code']==0 and json.loads(process['stdout'])==report['observations']
    path=root/'fixture-requests.private.json'
    assert not path.is_symlink() and digest(path)==report['fixture_requests_sha256']
    requested={urlsplit(url).path for url in json.loads(path.read_text())}
    assert {'/','/opfs-trial.js','/opfs-frame.html','/opfs-worker.js','/opfs-module.js',
            '/opfs-nested.js','/opfs-shared.js','/opfs-service.js'}<=requested
    data=report['observations'];assert data['completed'] is True
    assert type(data['paid_model_calls']) is int and data['paid_model_calls']==0
    assert len(data['rows'])==len(CASES)
    old=hashlib.sha256(bytes([7])*4096).hexdigest()
    recovered=hashlib.sha256(bytes([21])*4096).hexdigest()
    globals_={'window':'Window','iframe':'Window','shared':'SharedWorkerGlobalScope',
              'service':'ServiceWorkerGlobalScope'}
    locations={'window':'/','dedicated':'/opfs-worker.js','nested':'/opfs-worker.js',
               'module':'/opfs-module.js','shared':'/opfs-shared.js','service':'/opfs-service.js'}
    hashes=0
    for row,expected in zip(data['rows'],CASES):
        realm,kind,scenario=expected
        assert (row['realm'],row['kind'],row['scenario'])==expected
        assert row['completed'] is True and row['origin']==ORIGIN and row['secure'] is True
        assert row['actualGlobal']==globals_.get(realm,'DedicatedWorkerGlobalScope')
        assert row['topLevel'] is (True if realm=='window' else False if realm=='iframe' else None)
        if realm=='iframe':
            url=urlsplit(row['actualLocation'])
            assert url.scheme+'://'+url.netloc==ORIGIN and url.path=='/opfs-frame.html'
            assert parse_qs(url.query)==dict(realm=[realm],kind=[kind],scenario=[scenario])
        else:assert row['actualLocation']==ORIGIN+locations[realm]
        assert row['moduleUrl']==(ORIGIN+'/opfs-module.js' if realm=='module' else None)
        assert row['serviceScope']==(ORIGIN+'/owned-opfs/' if realm=='service' else None)
        if realm=='nested':
            assert row['nestedParentLocation']==ORIGIN+'/opfs-nested.js'
            assert row['nestedParentGlobal']=='DedicatedWorkerGlobalScope'
        else:assert row.get('nestedParentLocation') is None
        type_={'uint8':'Uint8Array','arraybuffer':'ArrayBuffer','offset_uint8':'Uint8Array',
               'dataview':'DataView','blob':'Blob','string':'string'}[kind]
        offset=32 if kind in ('offset_uint8','dataview') else 0
        backing=None if kind=='string' else 8*1024**2+(64 if offset else 0)
        assert type(row['payload']['bytes']) is int and type(row['payload']['byteOffset']) is int
        assert row['payload']['backingBytes'] is None or type(row['payload']['backingBytes']) is int
        assert row['payload']==dict(type=type_,bytes=8*1024**2,byteOffset=offset,backingBytes=backing)
        normal=hashlib.sha256(bytes([120 if kind=='string' else 42])*65536).hexdigest()
        assert row['normal']=={'bytes':65536,'sha256':normal}
        assert row['recovered']=={'bytes':4096,'sha256':recovered};hashes+=2
        if scenario=='quota':
            assert row['write']['completed'] is False and row['write']['error']=='QuotaExceededError'
            assert row['write']['stage']=='write'
        elif scenario=='cancel':assert row['cancelled'] is True and 'write' not in row
        else:
            write=row['write'];assert type(write['completed']) is bool
            if not write['completed']:
                assert write['error'] in ('NotFoundError','InvalidStateError','AbortError')
                assert write['stage'] in ('write','close')
        if scenario!='delete_inflight':
            assert row['retained']=={'bytes':4096,'sha256':old};hashes+=1
    return {'passed':True,'framework_sha256':framework,'privacy':report['privacy'],'cases':len(CASES),
            'realms':REALMS,'quota_payloads':KINDS,'strict_quota_errors':42,'normal_payload_controls':56,
            'cancel_rollback_cases':7,'inflight_deletion_settlement_cases':7,'full_content_hashes_checked':hashes,
            'disconnect_default_callback_observed':any(r.get('write',{}).get('message')=='File writer disconnected' for r in data['rows']),
            'scope':'Same-origin Window/iframe and five real worker categories. Bounded sizes and explicit buckets only; not forced Mojo disconnect, cross-site partitions, physical exhaustion or all payload/value classes.',
            'full_storage_privacy_proven':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--probe-dir',type=Path)
    args=p.parse_args();r=json.loads(args.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(args.probe_dir/Path(f).name if args.probe_dir else Path(f))==h
    framework=digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    print(json.dumps(verify(r,framework),indent=2))
