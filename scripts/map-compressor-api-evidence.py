#!/usr/bin/env python3
"""Map bounded compressor assertions, leaving all declarations only partially reviewed."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('catalog','protected','off','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();catalog=json.loads(a.catalog.read_text());evidence=[]
 for path,mode in ((a.protected,'balanced'),(a.off,'off')):
  r=json.loads(path.read_text())
  assert r['accepted'] is True and r['renders']==150 and r['full_channel_hashes']==300
  assert r['persona']=='linux-x86_64-software-v1' and r['privacy']==mode
  assert r['framework_sha256']==catalog['framework_sha256'] and r['full_audio_pipeline_cross_cpu_proven'] is False
  assert r['invalid_nonfinite_param_setters']==15 and r['shared_stereo_gain_passed'] is True
  evidence.append({'path':str(path),'sha256':sha(path),'pointer':'/accepted','framework_sha256':r['framework_sha256']})
 requested={'DynamicsCompressorNode':('threshold','knee','ratio','attack','release','reduction'),
            'AudioParam':('value','setValueAtTime','linearRampToValueAtTime')}
 members=[]
 for owner,names in requested.items():
  for name in names:
   matches=[m for m in catalog['members'] if m['owner']==owner and m['name']==name]
   assert len(matches)==1,(owner,name,len(matches));m=matches[0]
   members.append({'member_id':m['id'],'owner':owner,'name':name,'declaration_source':m['source'],
    'declaration_sha256':catalog['source_sha256'][m['source']],'review_status':'partial_runtime_evidence',
    'implementation_privacy_review':'pending','evidence':evidence,
    'limits':'Window offline stereo, three rates, five fixed/scheduled parameter presets and five signals. Nonfinite value setters tested. AudioParam.value setters only; getter not asserted. Compressor parameters are k-rate, not arbitrary sample-rate automation. Ratio-one startup reference difference is diagnostic, not ideal bypass proof. Not all values/realms/devices/realtime/whole pipeline portability.'})
 a.output.write_text(json.dumps({'schema_version':1,'catalog_sha256':sha(a.catalog),'framework_sha256':catalog['framework_sha256'],
  'members':members,'mapped_member_count':len(members),'fully_verified_member_count':0,'full_scope_complete':False},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'mapped_members':len(members),'fully_verified_members':0}))


if __name__=='__main__':main()
