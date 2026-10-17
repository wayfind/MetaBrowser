"""Validate full realtime Worklet samples and its actual rendering-realm clock."""
import argparse,base64,hashlib,json,math,struct
from pathlib import Path
from audio_worklet_acceptance import f32


def verify(data):
 assert data['closedContexts']==6 and data['microphoneRequested'] is False and data['outputMutedByGraph'] is True
 rows=data['rows'];assert len(rows)==6;expected={(rate,mode) for rate in (None,44100,96000) for mode in ('constant','gain-a-rate')};seen=set();max_error=0;observed_blocks=0
 for row in rows:
  key=(row['requestedRate'],row['mode']);assert key in expected and key not in seen;seen.add(key)
  rate=key[0] or 48000;assert row['rate']==rate and row['frames']==2048 and row['outputGain']==0
  assert row['frozen'] is True and row['resumed']=='running' and row['after']>row['suspended']>=row['before']>0
  assert 2<=len(row['messages'])<=64 and row['processedMessages']>=len(row['messages']);observed_blocks+=len(row['messages'])
  for n,message in enumerate(row['messages']):
   assert message['rate']==rate and message['frames']==128 and message['frame']>=0 and message['frame']%128==0
   assert math.isfinite(message['time']) and abs(message['time']-message['frame']/rate)<1e-12
   assert message['time']<=row['after']+128/rate
   if n:assert message['frame']==row['messages'][n-1]['frame']+128
  raw=base64.b64decode(row['float32Base64'],validate=True);assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==row['sha256']
  values=struct.unpack('<2048f',raw);assert all(math.isfinite(v) for v in values)
  period=[f32(((i*17)%257-128)/640) for i in range(257)]
  if key[1]=='gain-a-rate':period=[f32(v*(.25+(i%13)/32)) for i,v in enumerate(period)]
  # Acquisition phase is asynchronous. Verify every sample against one phase
  # of the independently constructed period, not just an aggregate RMS value.
  error=min(max(abs(value-period[(i+phase)%257]) for i,value in enumerate(values)) for phase in range(257))
  assert error<=1e-7,(key,error);max_error=max(max_error,error)
 assert seen==expected
 return {'realtime_worklet_contexts':6,'captured_full_float_values':12288,'observed_worklet_clock_blocks':observed_blocks,'max_independent_error':max_error,'output_muted':True,'full_worklet_privacy_proven':False,'full_scope_complete':False}


def accept(report,archive):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-worklet-realtime' and report['paid_model_calls']==0 and report['privacy']=='off'
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 return verify(report['observations'])


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive),indent=2))
