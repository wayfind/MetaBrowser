"""Full samples vs independent RBJ recurrence and frequency response, finite matrix."""
import base64,cmath,hashlib,math,struct

TYPES=('lowpass','highpass','bandpass','lowshelf','highshelf','peaking','notch','allpass')
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]

def coefficients(kind,rate,changed=False,parameters=None):
 frequency=rate/(16 if changed else 32);detune=-19 if changed else 37
 q=2 if changed else 1;gain=-3 if changed else 6
 if parameters is not None:frequency,detune,q,gain=parameters
 w=2*math.pi*frequency*2**f32(detune/1200)/rate;c=math.cos(w);s=math.sin(w)
 # Chromium intentionally computes its pow10 through expf.
 a=f32(math.exp(gain/40*math.log(10)))
 if kind in ('lowpass','highpass'):
  alpha=s/(2*f32(math.exp(q/20*math.log(10))));b=(1-c)/2 if kind=='lowpass' else (1+c)/2
  b0,b1,b2=b,(2*b if kind=='lowpass' else -2*b),b;a0,a1,a2=1+alpha,-2*c,1-alpha
 elif kind in ('lowshelf','highshelf'):
  k=math.sqrt(2*a)*s;u=a+1;v=a-1
  if kind=='lowshelf':b0,b1,b2=a*(u-v*c+k),2*a*(v-u*c),a*(u-v*c-k);a0,a1,a2=u+v*c+k,-2*(v+u*c),u+v*c-k
  else:b0,b1,b2=a*(u+v*c+k),-2*a*(v+u*c),a*(u+v*c-k);a0,a1,a2=u-v*c+k,2*(v-u*c),u-v*c-k
 else:
  alpha=s/(2*q);a0,a1,a2=1+alpha,-2*c,1-alpha
  if kind=='bandpass':b0,b1,b2=alpha,0,-alpha
  elif kind=='notch':b0,b1,b2=1,-2*c,1
  elif kind=='allpass':b0,b1,b2=1-alpha,-2*c,1+alpha
  else:b0,b1,b2=1+alpha*a,-2*c,1-alpha*a;a0,a1,a2=1+alpha/a,-2*c,1-alpha/a
 return tuple(v/a0 for v in (b0,b1,b2,a1,a2))

def verify(data):
 assert data['offlineOnly'] is True and data['microphoneRequested'] is False
 rows=data['rows'];assert len(rows)==96
 expected={(r,t,a,n) for r in (22050,44100,96000) for t in TYPES for a in ('fixed','step') for n in (0,1)}
 seen={};peak_error=0;response_error=0;decoded={}
 for row in rows:
  key=(row['rate'],row['type'],row['automation'],row['repeat']);assert key in expected and key not in seen;seen[key]=row
  rate,kind,automation,repeat=key
  assert row['frames']==row['length']==4096 and row['changeFrame']==2048 and row['bufferRate']==rate and row['eventBufferIdentity'] is True
  assert row['initial']=={'frequency':rate/32,'detune':37,'q':1,'gain':6}
  assert len(row['channels'])==1;c=row['channels'][0];raw=base64.b64decode(c['float32Base64'],validate=True);assert len(raw)==16384
  assert hashlib.sha256(raw).hexdigest()==c['sha256']==c['copySha256']
  values=struct.unpack('<4096f',raw);assert all(math.isfinite(v) for v in values);decoded[key]=values
  coeff=[coefficients(kind,rate,False),coefficients(kind,rate,True)]
  x1=x2=y1=y2=0;err=0
  for i,actual in enumerate(values):
   b0,b1,b2,a1,a2=coeff[automation=='step' and i>=2048];x=f32(((i*17)%257-128)/640)
   y=b0*x+b1*x1+b2*x2-a1*y1-a2*y2;err=max(err,abs(actual-f32(y)))
   x2,x1=x1,x;y2,y1=y1,y
  assert err<2e-6,(key,'recurrence',err);peak_error=max(peak_error,err)
  response=row['response'];want=[f32(x) for x in (0,rate/128,rate/32,rate/8,rate/3,rate/2,-1,rate)]
  assert response['frequencies']==want and len(response['magnitude'])==len(response['phase'])==8
  for field in ('magnitude','phase'):
   payload=base64.b64decode(response[field+'Float32Base64'],validate=True);assert len(payload)==32
   actual=struct.unpack('<8f',payload)
   for i,value in enumerate(actual):
    if i>=6:assert math.isnan(value) and response[field][i] is None
    else:assert math.isfinite(value) and value==response[field][i]
  b0,b1,b2,a1,a2=coeff[0]
  for i,freq in enumerate(want):
   mag,phase=response['magnitude'][i],response['phase'][i]
   if i>=6:assert mag is None and phase is None;continue
   z=cmath.exp(-2j*math.pi*freq/rate);v=(b0+b1*z+b2*z*z)/(1+a1*z+a2*z*z)
   assert mag is not None and math.isfinite(mag) and abs(mag-abs(v))<2e-5,(key,'response',i)
   response_error=max(response_error,abs(mag-abs(v)))
   if abs(v)>1e-8:assert phase is not None and abs(cmath.phase(cmath.exp(1j*(phase-cmath.phase(v)))))<2e-5,(key,'phase',i)
 assert set(seen)==expected
 min_effect=math.inf
 for rate,kind,automation,repeat in expected:
  v=decoded[rate,kind,automation,repeat]
  assert v==decoded[rate,kind,automation,0]
  if automation=='step':
   fixed=decoded[rate,kind,'fixed',repeat];assert v[:2048]==fixed[:2048]
   effect=max(abs(a-b) for a,b in zip(v[2048:],fixed[2048:]));assert effect>1e-4;min_effect=min(min_effect,effect)
 return {'graphs':96,'full_float_values_checked':393216,'filter_types':8,'max_independent_recurrence_error':peak_error,'max_response_magnitude_error':response_error,'minimum_step_effect':min_effect,'full_scope_complete':False}
