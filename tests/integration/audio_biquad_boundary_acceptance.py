"""Finite degenerate RBJ branches plus independent recurrence for remaining cases."""
import base64,hashlib,math,struct
from audio_biquad_matrix_acceptance import TYPES,coefficients,f32

def reference_coefficients(kind,rate,boundary):
 frequency=0 if boundary=='frequency-zero' else rate/2 if boundary=='frequency-nyquist' else rate/32
 q=0 if boundary=='q-zero' else 1;gain=0 if boundary=='gain-zero' else 6
 a=f32(math.exp(gain/40*math.log(10)))
 if boundary=='frequency-zero':
  v={'lowpass':0,'highpass':1,'bandpass':0,'lowshelf':1,'highshelf':a*a,'peaking':1,'notch':1,'allpass':1}[kind]
 elif boundary=='frequency-nyquist':
  v={'lowpass':1,'highpass':0,'bandpass':0,'lowshelf':a*a,'highshelf':1,'peaking':1,'notch':1,'allpass':1}[kind]
 elif boundary=='q-zero' and kind in ('bandpass','peaking','notch','allpass'):
  v={'bandpass':1,'peaking':a*a,'notch':0,'allpass':-1}[kind]
 else:return coefficients(kind,rate,parameters=(frequency,0,q,gain))
 return v,0,0,0,0

def verify(data):
 assert data['offlineOnly'] is True and data['microphoneRequested'] is False
 rows=data['rows'];assert len(rows)==192
 expected={(r,t,b,n) for r in (22050,44100,96000) for t in TYPES for b in ('frequency-zero','frequency-nyquist','q-zero','gain-zero') for n in (0,1)}
 seen={};peak_error=0
 for r in rows:
  key=r['rate'],r['type'],r['boundary'],r['repeat'];assert key in expected and key not in seen
  rate,kind,boundary,repeat=key
  assert r['parameters']==[0 if boundary=='frequency-zero' else rate/2 if boundary=='frequency-nyquist' else rate/32,0,0 if boundary=='q-zero' else 1,0 if boundary=='gain-zero' else 6]
  assert r['frames']==r['length']==1024 and r['bufferRate']==rate and r['eventBufferIdentity'] is True
  assert len(r['channels'])==1;c=r['channels'][0];raw=base64.b64decode(c['float32Base64'],validate=True);assert len(raw)==4096
  assert hashlib.sha256(raw).hexdigest()==c['sha256']==c['copySha256'];v=struct.unpack('<1024f',raw);assert all(map(math.isfinite,v));seen[key]=c['sha256']
  b0,b1,b2,a1,a2=reference_coefficients(kind,rate,boundary);x1=x2=y1=y2=0;error=0
  for i,actual in enumerate(v):
   x=f32(((i*17)%257-128)/640);y=b0*x+b1*x1+b2*x2-a1*y1-a2*y2
   error=max(error,abs(actual-f32(y)));x2,x1=x1,x;y2,y1=y1,y
  assert error<2e-6,(key,error);peak_error=max(peak_error,error)
 assert set(seen)==expected
 for rate,kind,boundary,repeat in expected:assert seen[rate,kind,boundary,repeat]==seen[rate,kind,boundary,0]
 return {'graphs':192,'full_float_values_checked':196608,'filter_types':8,'boundary_conditions':4,'max_independent_recurrence_error':peak_error,'full_scope_complete':False}
