"""Independently verify full decoded PCM buffers; not all codecs/realtime proof."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct
from functools import lru_cache

PAIRS=((8000,44100),(44100,48000),(48000,44100),(96000,44100),(44100,96000),(22050,48000),(48000,48000),(8000,48000))

def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def original(rate,frames,signal,i,ch):
    v=.25 if signal=='dc' else .5*math.sin(2*math.pi*i/128) if signal=='sine' else .5 if i==frames//2 else 0
    q=math.floor(v*(-.5 if ch else 1)*32768+.5)
    # Production FixedSampleTypeTraits uses separate positive/negative scales.
    return f32(q/(32768 if q<0 else 32767))


@lru_cache(maxsize=180)
def input_digest(rate,frames,signal):
    payload=bytearray()
    for i in range(frames):
        value=.25 if signal=='dc' else .5*math.sin(2*math.pi*i/128) if signal=='sine' else .5 if i==frames//2 else 0
        for ch in range(2):payload.extend(struct.pack('<h',math.floor(value*(-.5 if ch else 1)*32768+.5)))
    header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+len(payload),b'WAVE',b'fmt ',16,1,2,rate,rate*4,4,16,b'data',len(payload))
    return hashlib.sha256(header+payload).hexdigest()


@lru_cache(maxsize=2000)
def continuous_coefficients(sr,dr,remainder):
    phase=remainder/dr;cutoff=.9*min(1,dr/sr)
    coefficients=[]
    for k in range(32):
        t=k-16-phase;u=t/32+.5
        window=.42-.5*math.cos(2*math.pi*u)+.08*math.cos(4*math.pi*u)
        sinc=math.sin(math.pi*cutoff*t)/(math.pi*t) if t else cutoff
        coefficients.append(window*sinc)
    return coefficients


@lru_cache(maxsize=240)
def continuous_response(sr,dr,frames,signal,ch):
    # Independent ideal fractional-phase convolution. Production instead
    # interpolates 33 quantized phase tables and accumulates float32 products.
    source=[original(sr,frames,signal,i,ch) for i in range(frames)]
    output=[]
    for i in range(frames*dr//sr):
        center,remainder=divmod(i*sr,dr)
        coefficients=continuous_coefficients(sr,dr,remainder)
        output.append(math.fsum(source[j]*weight for k,weight in enumerate(coefficients)
                                if 0<=(j:=center+k-16)<frames))
    return output


def verify_graphs(data):
    assert [(x['label'],x['error']) for x in data['invalid']]==[(x,'EncodingError') for x in ('empty','junk','header-only')]
    expected={(s,d,n,signal,repeat) for s,d in PAIRS for n in (37,96,97,257,4097)
              for signal in ('dc','sine','impulse') for repeat in (0,1)}
    rows=data['rows'];assert len(rows)==len(expected)==240
    keyed={};max_error=0;max_full_error=0;float_values=0
    for row in rows:
        key=tuple(row[x] for x in ('sourceRate','destRate','frames','signal','repeat'))
        assert key in expected and key not in keyed;keyed[key]=row
        sr,dr,frames,signal,repeat=key;length=frames*dr//sr
        assert row['inputSha256']==input_digest(sr,frames,signal)
        assert row['length']==length and row['rate']==dr and row['channelCount']==2
        assert abs(row['duration']-length/dr)<1e-12
        assert row['inputDetached'] is True and row['callbackBufferIdentity'] is True and row['errorCallback'] is None
        assert len(row['channels'])==2
        for ch,c in enumerate(row['channels']):
            raw=base64.b64decode(c['float32Base64'],validate=True);assert len(raw)==length*4
            digest=hashlib.sha256(raw).hexdigest();assert digest==c['sha256']==c['copySha256']
            values=struct.unpack('<'+'f'*length,raw);float_values+=length
            assert c['finite'] is True and all(math.isfinite(v) for v in values)
            peak=max(map(abs,values));peak_frame=next(i for i,v in enumerate(values) if abs(v)==peak)
            assert c['peak']==peak and c['peakFrame']==peak_frame
            assert math.isfinite(c['sum']) and abs(c['sum']-sum(values))<1e-10
            assert c['nonzero']==sum(v!=0 for v in values) and peak>.001
            guard=math.ceil(32*dr/sr);picks=list(range(guard,max(guard,length-guard))) if signal!='impulse' else []
            assert c['referenceSamples']==len(picks)
            if picks:
                error=max(abs(values[i]-(.25 if signal=='dc' else .5*math.sin(2*math.pi*i*sr/dr/128))*(-.5 if ch else 1)) for i in picks)
                assert math.isfinite(c['referenceError']) and abs(c['referenceError']-error)<1e-10
                assert error<=.0001;max_error=max(max_error,error)
            else:assert c['referenceError'] is None
            if sr!=dr:
                theory=continuous_response(sr,dr,frames,signal,ch)
                full_error=max(abs(v-w) for v,w in zip(values,theory))
                # Includes edge samples. Bound the approximation error from
                # production's discrete phase-table interpolation separately.
                assert full_error<=.00025
                max_full_error=max(max_full_error,full_error)
            if sr==dr:
                assert max(abs(v-original(sr,frames,signal,i,ch)) for i,v in enumerate(values))<=1e-7
            if signal=='impulse':
                assert abs(peak_frame-(frames//2)*dr/sr)<=1
                if frames>=257:
                    assert abs(sum(values)-.5*dr/sr*(-.5 if ch else 1))<=.001
    assert set(keyed)==expected
    for s,d,n,signal,repeat in expected:
        if repeat:continue
        a=dict(keyed[s,d,n,signal,0]);b=dict(keyed[s,d,n,signal,1]);a.pop('repeat');b.pop('repeat');assert a==b
    return {'decode_cases':240,'full_channel_hashes':480,'full_float_values':float_values,
            'max_independent_reference_error':max_error,'max_independent_full_response_error':max_full_error,'independent_full_buffer_reference_passed':True,
            'same_rate_pcm_controls':30,'invalid_wav_failures':3}


def accept(report,probe_dir=None,raw_root=None):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['probe_kind']=='audio-resampler' and report['paid_model_calls']==0
    assert report['full_scope_complete'] is False and report['full_emulated_persona_proven'] is False
    root=Path(raw_root or report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for p,want in report['probe_sha256'].items():
        source=Path(probe_dir)/Path(p).name if probe_dir else Path(p)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==want,p
    expected_platform='Linux x86_64' if report['persona']=='linux-x86_64-software-v1' else 'MacIntel'
    assert report['observations']['platform']==expected_platform
    return dict(verify_graphs(report['observations']),accepted=True,framework_sha256=report['framework_sha256'],
                persona=report['persona'],privacy=report['privacy'],full_resampler_coverage_proven=False,full_scope_complete=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--probe-dir',type=Path);p.add_argument('--raw-root',type=Path);a=p.parse_args()
    raw=a.report.read_bytes();r=accept(json.loads(raw),a.probe_dir,a.raw_root);r['report_sha256']=hashlib.sha256(raw).hexdigest();print(json.dumps(r))
