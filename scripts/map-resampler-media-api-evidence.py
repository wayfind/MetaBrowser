#!/usr/bin/env python3
"""Bind decode/playback partial API observations to the current engine inventory."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('catalog','decode-protected','decode-off','media-protected','media-off','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();catalog=json.loads(a.catalog.read_text());decode=[];media=[]
 for kind,paths,required in [('decode',[(a.decode_protected,'balanced'),(a.decode_off,'off')],240),('media',[(a.media_protected,'balanced'),(a.media_off,'off')],16)]:
  for path,mode in paths:
   r=json.loads(path.read_text());assert r['accepted'] is True and r['privacy']==mode and r['persona']=='linux-x86_64-software-v1'
   assert r['framework_sha256']==catalog['framework_sha256'] and r['full_scope_complete'] is False
   assert r['decode_cases' if kind=='decode' else 'playback_cases']==required
   if kind=='decode':assert r['independent_full_buffer_reference_passed'] is True and r['full_float_values']==1063284
   else:assert r['closed_contexts']==16 and r['silent_output'] is True and r['microphone_requested'] is False
   (decode if kind=='decode' else media).append({'path':str(path),'sha256':sha(path),'pointer':'/accepted','framework_sha256':r['framework_sha256']})
 requested={'BaseAudioContext':('decodeAudioData','sampleRate','state'),
            'AudioContext':('createMediaElementSource','resume','close'),
            'HTMLMediaElement':('play','pause','load','src','preload','loop','currentTime','paused','readyState','error')}
 members=[]
 for owner,names in requested.items():
  for name in names:
   matches=[m for m in catalog['members'] if m['owner']==owner and m['name']==name];assert len(matches)==1,(owner,name)
   m=matches[0];evidence=decode if name=='decodeAudioData' else media
   members.append({'member_id':m['id'],'owner':owner,'name':name,'declaration_source':m['source'],
    'declaration_sha256':catalog['source_sha256'][m['source']],'review_status':'partial_runtime_evidence','implementation_privacy_review':'pending',
    'evidence':evidence,'limits':'Window only: PCM16 WAV success/callback identity/detach/three malformed inputs and bounded 8-ratio decode matrix; realtime Blob WAV, explicit CDP user gesture, zero-gain graph output, captured tone frequency/amplitude and close promise. src/preload/loop setters only. load only invoked during cleanup. Not all codecs, callbacks, realms, policies, network sites, sink/device changes, microphones, WebRTC, SetRatio or full audio parity.'})
 a.output.write_text(json.dumps({'schema_version':1,'catalog_sha256':sha(a.catalog),'framework_sha256':catalog['framework_sha256'],
  'members':members,'mapped_member_count':len(members),'fully_verified_member_count':0,'full_scope_complete':False},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'mapped_members':len(members),'fully_verified_members':0}))


if __name__=='__main__':main()
