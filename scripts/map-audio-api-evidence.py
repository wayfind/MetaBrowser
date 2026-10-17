#!/usr/bin/env python3
"""Map bounded DSP assertions to actual IDL declarations, without certifying APIs."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('catalog','protected','off','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();catalog=json.loads(a.catalog.read_text());evidence=[]
    for path,mode in ((a.protected,'balanced'),(a.off,'off')):
        receipt=json.loads(path.read_text())
        assert receipt['passed'] is True and receipt['privacy']==mode
        assert receipt['persona']=='linux-x86_64-software-v1'
        assert receipt['framework_sha256']==catalog['framework_sha256']
        assert receipt['actual_graph_renders']==32 and receipt['full_channel_hashes']==64
        assert receipt['full_audio_parity_proven'] is False and receipt['full_scope_complete'] is False
        evidence.append({'path':str(path),'sha256':sha(path),'pointer':'/passed',
                         'framework_sha256':receipt['framework_sha256'],'scope':receipt['scope']})
    requested={
        'AudioBuffer':('getChannelData','copyFromChannel','duration','sampleRate','numberOfChannels'),
        'OfflineAudioContext':('startRendering',),
        'BaseAudioContext':('createBuffer','createBufferSource','createGain','createConvolver','createOscillator','createDynamicsCompressor'),
    }
    members=[]
    for owner,names in requested.items():
        for name in names:
            matches=[m for m in catalog['members'] if m['owner']==owner and m['name']==name]
            assert len(matches)==1,(owner,name,len(matches))
            m=matches[0]
            members.append({'member_id':m['id'],'owner':owner,'name':name,'declaration_source':m['source'],
                'declaration_sha256':catalog['source_sha256'][m['source']],
                'review_status':'partial_runtime_evidence','evidence':evidence,
                'implementation_privacy_review':'pending',
                'limits':'Window only. Four rates, stereo, 2048-frame gain/mix/convolution/oscillator-compressor graphs. Repeat/event/promise/readback/copy and bounded analytic error assertions only. Not all values, exceptions, offsets/detachment, realms, realtime/worklet/device/HRTF/resampling, 100 starts, seven days or cross-platform parity.'})
    result={'schema_version':1,'catalog_sha256':sha(a.catalog),'framework_sha256':catalog['framework_sha256'],
            'members':members,'mapped_member_count':len(members),'fully_verified_member_count':0,
            'full_scope_complete':False,'scope':'Partial runtime mapping; catalog remains an unclassified potential-surface inventory.'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'mapped_members':len(members),'fully_verified_members':0}))


if __name__=='__main__':main()
