"""Owned device boundary and lifecycle observations; not audible-output proof."""
import argparse,hashlib,json,math
from pathlib import Path


def verify(data):
 assert data['closedContexts']==8 and data['microphoneRequested'] is False and data['outputMutedByGraph'] is True
 expected={(silent,hint) for silent in (False,True) for hint in (-1,0,.1,1e300)};seen=set()
 assert len(data['rows'])==8
 for row in data['rows']:
  key=(row['silent'],row['requestedHint']);assert key in expected and key not in seen;seen.add(key)
  assert row['rate']==48000 and row['maxChannelCount']==2 and row['mono']==1 and row['stereo']==2
  assert row['excessChannels']=='IndexSizeError'
  assert row['running']==row['resumed']=='running' and row['suspended']=='suspended' and row['frozen'] is True
  assert row['outputGain']==0
  frames={-1:128,0:128,.1:4864,1e300:8192}[row['requestedHint']]
  assert math.isclose(row['baseLatency'],frames/48000,rel_tol=0,abs_tol=1e-12)
 assert seen==expected
 assert data['invalid']==[{'value':name,'result':'TypeError'} for name in ('NaN','Infinity','-Infinity')]
 return {'capability_and_lifecycle_cases':8,'invalid_nonfinite_hints_rejected':3,'full_scope_complete':False,'real_hardware_playback_verified':False}


def accept(report,archive):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-device' and report['persona']=='linux-x86_64-software-v1' and report['paid_model_calls']==0
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 return verify(report['observations'])


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive),indent=2))
