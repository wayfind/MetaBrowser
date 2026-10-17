"""Triage explicit raw native-control/CfT observations; not a release pass."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    candidate=json.loads(a.candidate.read_text());baseline=json.loads(a.baseline.read_text());assert candidate['completed'] and baseline['completed']
    control=candidate['modes']['native_control'];assert control['consistency_passed'] and control['passive_policy']['passed'] and control['version_policy']['passed']
    assert candidate['probe_sha256']['tests/integration/identity_surface_collector.js']==baseline['probe_sha256']['collector'],'Different probe expressions'
    left=control['observations'];right=baseline['observations']
    def canonical(data):
        import copy
        data=copy.deepcopy(data);pairs=data['headers']['headers'];data['headers']['order']=[k.lower() for k,v in pairs];data['headers']['headers']={k.lower():v for k,v in pairs};return data
    left,right=canonical(left),canonical(right);differences=[]
    def label(path):
        if '.uaData.' in path and any(x in path for x in ['brands','fullVersionList','uaFullVersion']):return 'declared_brand_or_patch_version'
        if path in ['headers.headers.host','headers.headers.referer']:return 'fixture_endpoint'
        if path.startswith('headers.headers.sec-ch-ua') and ('full-version' in path or path=='headers.headers.sec-ch-ua'):return 'declared_brand_or_patch_version'
        if '.connection.' in path or path.startswith('passiveSignalTrace') and any(x in path for x in ['.rtt','.downlink','.effectiveType']):return 'native_network_estimate_variation'
        if '.window.' in path and any(path.endswith('.'+x) for x in ['innerWidth','innerHeight','outerWidth','outerHeight']):return 'native_window_geometry'
        if '.storage.usage' in path:return 'origin_storage_usage'
        if '.storage.quota' in path:return 'quota_policy_review_needed'
        if '.permissions.' in path:return 'permission_state_review_needed'
        return 'unexplained_review_needed'
    def walk(x,y,path=''):
        if isinstance(x,dict) and isinstance(y,dict):
            for key in sorted(set(x)|set(y)):
                name=path+'.'+key if path else key
                if key not in x or key not in y:differences.append({'path':name,'category':'missing_on_one_side','candidate':x.get(key),'baseline':y.get(key)})
                else:walk(x[key],y[key],name)
        elif isinstance(x,list) and isinstance(y,list) and len(x)==len(y):
            for i,(xx,yy) in enumerate(zip(x,y)):walk(xx,yy,path+f'[{i}]')
        elif type(x) is not type(y) or x!=y:differences.append({'path':path,'category':label(path),'candidate':x,'baseline':y})
    walk(left,right)
    from collections import Counter
    report={'kind':'native-control-same-branch-differential-triage','candidate_framework_sha256':candidate['framework_sha256'],'baseline_framework_sha256':baseline['framework_sha256'],'baseline_version':baseline['version'],
            'input_sha256':{str(a.candidate):hashlib.sha256(a.candidate.read_bytes()).hexdigest(),str(a.baseline):hashlib.sha256(a.baseline.read_bytes()).hexdigest()},'categories':dict(Counter(x['category'] for x in differences)),'differences':differences,
            'exact_release_parity_proven':False,'privacy_coverage_proven':False,'note':'Categories describe review work, not automatic acceptance. CfT92 is a testing variant and a different patch from candidate97; dynamic/permission/quota differences do not prove equivalent behavior.'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2));a.output.chmod(0o600)
    print(json.dumps({'categories':report['categories'],'exact_release_parity_proven':False}))


if __name__=='__main__':main()
