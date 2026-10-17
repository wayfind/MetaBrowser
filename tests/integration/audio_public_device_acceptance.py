"""Verify actual public stream parameters; hardware timing remains outside scope."""
import argparse
import json
import math
from pathlib import Path
from audio_context_acceptance import accept


def verify_policy(report,archive):
 result=accept(report,archive/'inputs',archive)
 assert report['persona']=='linux-x86_64-software-v1'
 assert report['privacy']=='off'
 for row in report['observations']['rows']:
  rate=row['requestedRate'] or 48000
  hint=row['requestedHint']
  seconds={None:256/48000,'interactive':256/48000,'balanced':.01,'playback':1024/48000}.get(hint,hint)
  frames=min(8192,max(128,math.ceil(seconds*rate/128)*128))
  for sample in [row['initial'],*row['samples'],row['suspended']]:
   assert sample['rate']==rate
   assert math.isclose(sample['baseLatency'],frames/rate,rel_tol=0,abs_tol=1e-12),(row,sample,frames)
 return dict(result,public_stream_parameters_passed=True,hardware_clock_isolated=False)


def compare(first,second,archives):
 validations={mode:verify_policy(report,archives/mode) for mode,report in [('scalar-off',first),('scalar-buffer512',second)]}
 assert first['framework_sha256']==second['framework_sha256']
 assert second['requested_audio_buffer_size']==512 and '--audio-buffer-size=512' in second['command']
 def index(report):
  return {(r['requestedRate'],r['requestedHint'],r['repeat']):r for r in report['observations']['rows']}
 left,right=index(first),index(second)
 assert left.keys()==right.keys()
 for key in left:
  for field in ('rate','baseLatency'):
   assert left[key]['initial'][field]==right[key]['initial'][field]
 return {'validations':validations,'buffer_independent_static_parameter_cases':len(left),
         'privacy_protection_proven':False,'hardware_clock_isolated':False,'full_scope_complete':False}


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('first',type=Path);p.add_argument('second',type=Path);p.add_argument('--archives',type=Path,required=True);a=p.parse_args()
 print(json.dumps(compare(json.loads(a.first.read_text()),json.loads(a.second.read_text()),a.archives),indent=2))
