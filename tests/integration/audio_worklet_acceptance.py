"""Verify full Worklet buffers with independent gain, allpass and panning math."""
import argparse,base64,hashlib,json,math,struct
from pathlib import Path


def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]

def reference(kind,rate,frames):
 data=[f32(((i*17)%257-128)/640) for i in range(frames)]
 if kind=='gain-a-rate':data=[f32(v*(.25+(i%13)/32)) for i,v in enumerate(data)]
 if kind=='biquad-detune':
  theta=2*math.pi*(rate/32)*2**f32(37/1200)/rate
  alpha=math.sin(theta)/2;c=math.cos(theta)
  b0=(1-alpha)/(1+alpha);b1=-2*c/(1+alpha);b2=1
  a1=b1;a2=b0;x1=x2=y1=y2=0;result=[]
  for x in data:
   y=b0*x+b1*x1+b2*x2-a1*y1-a2*y2
   result.append(f32(y));x2,x1=x1,x;y2,y1=y1,y
  data=result
 if kind=='spatial':return [[f32(v*g) for v in data] for g in (math.cos(math.pi/8),math.sin(math.pi/8))]
 return [data,data]


def verify(data):
 assert data['offlineOnly'] is True and data['microphoneRequested'] is False
 rows=data['rows'];assert len(rows)==24
 expected={(rate,kind,repeat) for rate in (22050,44100,96000) for kind in ('identity','gain-a-rate','biquad-detune','spatial') for repeat in (0,1)}
 seen={};errors={kind:0 for _,kind,_ in expected}
 for row in rows:
  key=(row['rate'],row['kind'],row['repeat']);assert key in expected and key not in seen;seen[key]=row
  rate,kind,repeat=key;assert row['frames']==row['length']==2048 and row['bufferRate']==rate and row['channelCount']==2 and row['eventBufferIdentity'] is True
  if kind=='biquad-detune':assert row['settings']=={'type':'allpass','frequency':rate/32,'detune':37,'q':1}
  elif kind=='spatial':assert row['settings']=={'model':'equalpower','rolloff':0,'position':[-1,0,-1]}
  else:assert row['settings'] is None
  assert len(row['messages'])==16
  for n,message in enumerate(row['messages']):
   assert message['frame']==n*128 and message['rate']==rate and message['frames']==128 and message['inputChannels']==1
   assert abs(message['time']-n*128/rate)<1e-12
   if kind=='gain-a-rate':
    assert message['gainValues']==128 and message['gainFirst']==.25+((n*128)%13)/32 and message['gainLast']==.25+((n*128+127)%13)/32
   else:assert message['gainValues'] in (1,128) and message['gainFirst']==message['gainLast']==1
  want=reference(kind,rate,2048);assert len(row['channels'])==2
  for ch,channel in enumerate(row['channels']):
   raw=base64.b64decode(channel['float32Base64'],validate=True);assert len(raw)==8192
   assert hashlib.sha256(raw).hexdigest()==channel['sha256']==channel['copySha256']
   values=struct.unpack('<2048f',raw);assert all(math.isfinite(v) for v in values)
   error=max(abs(v-w) for v,w in zip(values,want[ch]));errors[kind]=max(errors[kind],error)
   assert error<=(1e-7 if kind in ('biquad-detune','spatial') else 0),(key,ch,error)
 assert set(seen)==expected
 for rate,kind,repeat in expected:
  if repeat==1:assert [c['sha256'] for c in seen[rate,kind,0]['channels']]==[c['sha256'] for c in seen[rate,kind,1]['channels']]
 return {'worklet_graphs':24,'actual_processor_blocks':384,'full_float_values_checked':98304,'max_independent_error':errors,'full_scope_complete':False,'full_worklet_privacy_proven':False}


def accept(report,archive):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-worklet' and report['paid_model_calls']==0 and report['privacy']=='off'
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 return verify(report['observations'])


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive),indent=2))
