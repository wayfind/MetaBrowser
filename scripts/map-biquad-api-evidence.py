#!/usr/bin/env python3
"""Map finite Biquad runtime assertions to pinned IDL, never certify whole APIs."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
for n in ('catalog','matrix','boundary','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();catalog=json.loads(a.catalog.read_text());evidence=[]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
for path,count,kind in ((a.matrix,96,'audio-biquad-matrix'),(a.boundary,192,'audio-biquad-boundary')):
 r=json.loads(path.read_text())
 assert r['probe_kind']==kind and r['fixture_buffers_identical'] is True and r['functional_checks_passed'] is True
 assert r['hashes_compared']==r['hashes_equal']==count and not r['mismatches']
 if kind=='audio-biquad-matrix':assert r['frequency_response_float32_buffers_equal'] is True
 assert r['same_patch_source_binding_verified'] is True and r['mac_framework_sha256']==catalog['framework_sha256']
 assert r['full_scope_complete'] is False and r['full_pipeline_cross_cpu_proven'] is False
 evidence.append({'path':str(path),'sha256':sha(path),'pointer':'/fixture_buffers_identical','framework_sha256':r['mac_framework_sha256']})
requested={'BiquadFilterNode':('type','frequency','detune','Q','gain','getFrequencyResponse'),
 'BaseAudioContext':('createBiquadFilter',),'AudioParam':('value','setValueAtTime'),
 'AudioBuffer':('getChannelData','copyFromChannel'),'OfflineAudioContext':('startRendering',)}
members=[]
for owner,names in requested.items():
 for name in names:
  matches=[m for m in catalog['members'] if m['owner']==owner and m['name']==name];assert len(matches)==1,(owner,name,len(matches))
  m=matches[0];members.append({'member_id':m['id'],'owner':owner,'name':name,'declaration_source':m['source'],
   'declaration_sha256':catalog['source_sha256'][m['source']],'review_status':'partial_runtime_evidence','evidence':evidence,
   'limits':'Owned Window offline only: eight types, three rates, fixed/step changes, four boundary cases, full buffers, repeat and two read paths; finite analytic response and recurrence checks. Not all values/exceptions/automation/realms/realtime/devices or full privacy.'})
a.output.write_text(json.dumps({'schema_version':1,'catalog_sha256':sha(a.catalog),'framework_sha256':catalog['framework_sha256'],
 'members':members,'mapped_member_count':len(members),'fully_verified_member_count':0,'full_scope_complete':False},indent=2)+'\n')
print(json.dumps({'mapped_members':len(members),'fully_verified_members':0}))
