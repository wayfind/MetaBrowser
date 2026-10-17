#!/usr/bin/env python3
"""Bind bounded FFT graph assertions to exact IDL members, never certify APIs."""
import argparse
import hashlib
import json
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('catalog','protected','off','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();catalog=json.loads(a.catalog.read_text());evidence=[]
    for path,mode in ((a.protected,'balanced'),(a.off,'off')):
        r=json.loads(path.read_text());assert r['passed'] is True and r['privacy']==mode
        assert r['persona']=='linux-x86_64-software-v1' and r['framework_sha256']==catalog['framework_sha256']
        assert r['actual_graph_renders']==30 and r['analyser_sizes']==11 and r['invalid_fft_sizes']==10
        assert r['full_audio_parity_proven'] is False and r['full_scope_complete'] is False
        evidence.append({'path':str(path),'sha256':sha(path),'pointer':'/passed','framework_sha256':r['framework_sha256'],'scope':r['scope']})
    requested={
        'AudioBuffer':('length',),
        'BaseAudioContext':('createAnalyser','createPeriodicWave'),
        'AnalyserNode':('fftSize','frequencyBinCount','smoothingTimeConstant','minDecibels','maxDecibels',
                        'getFloatFrequencyData','getFloatTimeDomainData','getByteFrequencyData'),
        'OscillatorNode':('setPeriodicWave',),
    }
    members=[]
    for owner,names in requested.items():
        for name in names:
            matches=[m for m in catalog['members'] if m['owner']==owner and m['name']==name]
            assert len(matches)==1,(owner,name,len(matches));m=matches[0]
            members.append({'member_id':m['id'],'owner':owner,'name':name,'declaration_source':m['source'],
                'declaration_sha256':catalog['source_sha256'][m['source']],
                'review_status':'partial_runtime_evidence','implementation_privacy_review':'pending','evidence':evidence,
                'limits':'Window mono only. Eleven analyser FFT sizes, selected direct-DFT bins and setter failures, fixed sparse 4096-tap convolution and selected custom Fourier coefficients. Not all values/offsets/permissions/realms/realtime/worklets/resampling/HRTF/devices or full audio privacy/parity.'})
    a.output.write_text(json.dumps({'schema_version':1,'catalog_sha256':sha(a.catalog),
        'framework_sha256':catalog['framework_sha256'],'members':members,'mapped_member_count':len(members),
        'fully_verified_member_count':0,'full_scope_complete':False},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'mapped_members':len(members),'fully_verified_members':0}))

if __name__=='__main__':main()
