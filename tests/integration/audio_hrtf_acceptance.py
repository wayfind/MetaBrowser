"""HRTF signal/shape, directional energy and full linearity checks; finite scope."""
import argparse,base64,hashlib,json,math,struct
from pathlib import Path


def verify(data):
 assert data['offlineOnly'] is True and data['microphoneRequested'] is False
 rows=data['rows'];assert len(rows)==36
 expected={(rate,direction,signal,repeat) for rate in (22050,44100,96000) for direction in ('front','left','right') for signal in ('impulse','pair') for repeat in (0,1)}
 seen={};values={};max_linear_error=0
 for row in rows:
  key=(row['rate'],row['direction'],row['signal'],row['repeat']);assert key in expected and key not in seen;seen[key]=row
  rate,direction,signal,repeat=key
  assert row['frames']==row['length']==4096 and row['bufferRate']==rate and row['channelCount']==2
  assert row['eventBufferIdentity'] is True and row['model']=='HRTF' and row['rolloff']==0
  assert row['position']==[{'front':0,'left':-1,'right':1}[direction],0,-1]
  assert len(row['channels'])==2;channels=[]
  for channel in row['channels']:
   raw=base64.b64decode(channel['float32Base64'],validate=True);assert len(raw)==16384
   assert hashlib.sha256(raw).hexdigest()==channel['sha256']==channel['copySha256']
   samples=struct.unpack('<4096f',raw);assert all(math.isfinite(v) for v in samples)
   assert .01<max(map(abs,samples))<2 and .001<sum(v*v for v in samples)<10
   assert sum(abs(v)>1e-7 for v in samples)>=64
   channels.append(samples)
  values[key]=channels
 assert set(seen)==expected
 for rate,direction,signal,repeat in expected:
  key=(rate,direction,signal,repeat)
  if repeat==1:assert values[key]==values[rate,direction,signal,0]
  if direction=='front':assert values[key][0]==values[key][1]
  if signal=='impulse':
   energy=[sum(v*v for v in channel) for channel in values[key]]
   if direction=='left':assert energy[0]>1.5*energy[1]
   if direction=='right':assert energy[1]>1.5*energy[0]
  else:
   impulse=values[rate,direction,'impulse',repeat]
   for ch in range(2):
    error=max(abs(v-(impulse[ch][i]-.5*(impulse[ch][i-1024] if i>=1024 else 0))) for i,v in enumerate(values[key][ch]))
    assert error<=1e-7,(key,ch,error);max_linear_error=max(max_linear_error,error)
 return {'hrtf_graphs':36,'full_channel_outputs':72,'full_float_values_checked':294912,'max_linear_superposition_error':max_linear_error,'full_hrtf_privacy_proven':False,'full_scope_complete':False}


def verify_trace(data,portable):
 events=data['complexBackendTrace']
 assert len(events)==3
 assert {e['stage'] for e in events}=={'interpolate','group-delay','phase-adjust'}
 for event in events:
  assert event['portable'] is portable
  assert type(event['count']) is int and event['count']>0
 return {'actual_complex_backend_stages':3,'portable_backend_observed':portable,
         'actual_traced_stage_calls':sum(e['count'] for e in events)}


def accept(report,archive,require_trace=False):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-hrtf' and report['paid_model_calls']==0 and report['privacy']=='off'
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 result=verify(report['observations'])
 if require_trace:result.update(verify_trace(report['observations'],report['persona']=='linux-x86_64-software-v1'))
 return result


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);p.add_argument('--require-trace',action='store_true');a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive,a.require_trace),indent=2))
