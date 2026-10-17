"""Check moving-HRTF control effects, causality and dyadic signal linearity."""
import argparse,base64,hashlib,json,math,struct
from pathlib import Path
from audio_hrtf_acceptance import verify_trace


def verify(data,portable=True):
 assert data['offlineOnly'] is True and data['microphoneRequested'] is False
 expected={(rate,motion,scale,repeat) for rate in (22050,44100,96000) for motion in ('static','azimuth','elevation','listener') for scale in (1,.5) for repeat in (0,1)}
 rows=data['rows'];assert len(rows)==48;seen={};values={};max_scale_error=0;min_motion_change=math.inf
 for row in rows:
  key=(row['rate'],row['motion'],row['scale'],row['repeat']);assert key in expected and key not in seen;seen[key]=row
  assert row['frames']==row['length']==8192 and row['bufferRate']==row['rate'] and row['channelCount']==2
  assert row['model']=='HRTF' and row['rolloff']==0 and row['eventBufferIdentity'] is True
  assert len(row['channels'])==2;channels=[]
  for channel in row['channels']:
   raw=base64.b64decode(channel['float32Base64'],validate=True);assert len(raw)==32768
   assert hashlib.sha256(raw).hexdigest()==channel['sha256']==channel['copySha256']
   samples=struct.unpack('<8192f',raw);assert all(math.isfinite(v) for v in samples)
   assert .001<sum(v*v for v in samples)<10000 and .001<max(map(abs,samples))<2
   channels.append(samples)
  values[key]=channels
 assert set(seen)==expected
 for rate,motion,scale,repeat in expected:
  current=values[rate,motion,scale,repeat]
  if repeat:assert current==values[rate,motion,scale,0]
  if scale==.5:
   full=values[rate,motion,1,repeat]
   error=max(abs(x-.5*y) for xs,ys in zip(current,full) for x,y in zip(xs,ys));assert error<=1e-7;max_scale_error=max(max_scale_error,error)
  if motion=='static':assert current[0]==current[1]
  else:
   baseline=values[rate,'static',scale,repeat]
   prefix=max(abs(x-y) for xs,ys in zip(current,baseline) for x,y in zip(xs[:2048],ys[:2048]));assert prefix<=1e-7
   changed=max(abs(x-y) for xs,ys in zip(current,baseline) for x,y in zip(xs[2048:],ys[2048:]));assert changed>1e-4,(rate,motion,scale,changed)
   min_motion_change=min(min_motion_change,changed)
 result={'dynamic_hrtf_graphs':48,'full_float_values_checked':786432,'max_dyadic_scale_error':max_scale_error,'minimum_motion_effect':min_motion_change,'full_scope_complete':False,'full_hrtf_privacy_proven':False}
 result.update(verify_trace(data,portable));return result


def accept(report,archive):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-hrtf-dynamic' and report['paid_model_calls']==0 and report['privacy']=='off'
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 return verify(report['observations'],report['persona']=='linux-x86_64-software-v1')


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive),indent=2))
