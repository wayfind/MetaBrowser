"""FFT pipeline correctness; does not certify all DSP or platform parity."""
import argparse
import json
import math
from pathlib import Path
import re
import struct
from functools import lru_cache
from identity_surface_runner import digest


def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]


@lru_cache(maxsize=11)
def expected_window(size):
    frames=max(4096,size*2)
    return tuple(f32(f32(((((frames-size+i)*17)%257)-128)/137)*
                     f32(.42-.5*math.cos(2*math.pi*i/size)+.08*math.cos(4*math.pi*i/size)))
                 for i in range(size))


@lru_cache(maxsize=66)
def expected_amplitude(size,bin):
    real=imag=0.0
    for i,x in enumerate(expected_window(size)):
        angle=2*math.pi*bin*i/size;real+=x*math.cos(angle);imag-=x*math.sin(angle)
    return math.hypot(real,imag)/size


def verify_graphs(data):
    invalid=data['invalid']
    assert [x['label'] for x in invalid]==['zero','below','31','33','above','65536','negative','fraction','nan','infinity']
    assert all(x['error']=='IndexSizeError' and x['retained']==2048 for x in invalid)
    rows=data['rows'];assert len(rows)==30
    expected=[('analyser',2**n,repeat) for n in range(5,16) for repeat in (0,1)]
    expected += [(kind,rate,repeat) for rate in (44100,48000) for kind in ('long-convolution','periodic-wave') for repeat in (0,1)]
    assert [(r['kind'],r.get('size',r['rate']),r['repeat']) for r in rows]==expected
    seen={}
    def finite(x):return type(x) in (int,float) and math.isfinite(x)
    def hash_ok(x):return isinstance(x,str) and re.fullmatch('[0-9a-f]{64}',x)
    for r in rows:
        assert all(type(r[k]) is int for k in ('rate','repeat','frames','bufferLength'))
        assert r['bufferLength']==r['frames']
        if r['kind']=='analyser':
            assert type(r['size']) is int and r['rate']==44100 and r['frames']==max(4096,r['size']*2)
            assert type(r['binCount']) is int and r['binCount']==r['size']//2
            hashes=[r[k] for k in ('timeHash','frequencyHash','byteHash')]
            assert finite(r['timeError']) and 0<=r['timeError']<=1e-7
            # A zero spectral magnitude is specified as -Infinity dB. It is
            # different from a NaN/+Infinity caused by broken DSP.
            assert type(r['nanFrequencyBins']) is int and r['nanFrequencyBins']==0
            assert type(r['positiveInfiniteFrequencyBins']) is int and r['positiveInfiniteFrequencyBins']==0
            assert type(r['zeroMagnitudeBins']) is int and 0<=r['zeroMagnitudeBins']<=r['binCount']-6
            assert r['finiteFrequency'] is (r['zeroMagnitudeBins']==0)
            assert type(r['maxByteError']) is int and 0<=r['maxByteError']<=1
            assert [x['bin'] for x in r['picks']]==[0,1,7,r['size']//8,r['size']//4,r['size']//2-1]
            for pick in r['picks']:
                assert all(finite(pick[k]) for k in ('expected','observed','error'))
                assert abs(10**(pick['expected']/20)-expected_amplitude(r['size'],pick['bin']))<=1e-12
                assert pick['error']==abs(pick['observed']-pick['expected'])
                # Relative dB error is ill-conditioned for bins near float32
                # cancellation noise. Bound their actual linear amplitude;
                # retain the tighter relative check for resolved bins.
                if pick['expected'] >= -120:
                    assert pick['error']<=.02
                else:
                    assert abs(10**(pick['observed']/20)-10**(pick['expected']/20))<=1e-8
        else:
            assert r['frames']==8192 and r['bufferRate']==r['rate']
            assert r['eventBufferIdentity'] is True and r['finite'] is True
            assert type(r['nonzero']) is int and 2048<r['nonzero']<=8192
            assert finite(r['peak']) and 0<r['peak']<=4
            assert finite(r['maxError']) and 0<=r['maxError']<=2e-5
            assert r['sha256']==r['copySha256'] and hash_ok(r['copySha256'])
            assert len(r['samples'])==20 and all(finite(x) and abs(x)<=r['peak'] for x in r['samples'])
            for i,x in enumerate(r['samples'],450):
                if r['kind']=='periodic-wave':
                    reference=f32(.5*math.cos(2*math.pi*i/1024)+.25*math.sin(6*math.pi*i/1024)-.125*math.cos(34*math.pi*i/1024))
                else:
                    positions=[0,127,128,129,255,256,511,512,1023,2047,2048,4095]
                    reference=f32(sum(f32(((((i-p)*17)%257)-128)/137)*f32(((-1 if j%2 else 1)/(3+j*7))) for j,p in enumerate(positions) if i>=p))
                assert abs(x-reference)<=2e-5
            hashes=[r['sha256']]
        assert all(hash_ok(x) for x in hashes)
        key=(r['kind'],r.get('size',r['rate']))
        if r['repeat']==0:seen[key]=hashes
        else:assert seen[key]==hashes,key


def verify(report,framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256']==framework and report['probe_kind']=='audio-fft'
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_emulated_persona_proven'] is False and report['full_scope_complete'] is False
    assert report['persona'] in ('native-macos-arm64-v1','linux-x86_64-software-v1') and report['privacy'] in ('balanced','off')
    native_rust=report.get('native_rust_fft',False);assert type(native_rust) is bool
    assert ('--enable-blink-features=WebAudioRustFft' in report['command']) is native_rust
    if native_rust:assert report['persona']=='native-macos-arm64-v1'
    disable_rust=report.get('disable_rust_fft',False);assert type(disable_rust) is bool
    assert ('--disable-blink-features=WebAudioRustFft' in report['command']) is disable_rust
    assert not (native_rust and disable_rust)
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for flag in ('--user-data-dir='+str(root/'browser'),'--metabrowser-persona-template='+report['persona'],
                 '--metabrowser-privacy='+report['privacy'],'--use-gl=angle','--use-angle=swiftshader',
                 '--use-webgpu-adapter=swiftshader','--disable-accelerated-video-decode','--disable-accelerated-video-encode'):
        assert flag in report['command']
    assert report['observations']['platform']==('MacIntel' if report['persona']=='native-macos-arm64-v1' else 'Linux x86_64')
    verify_graphs(report['observations'])
    return {'passed':True,'framework_sha256':framework,'persona':report['persona'],'privacy':report['privacy'],
            'actual_graph_renders':30,'analyser_sizes':11,'direct_dft_bins':132,'invalid_fft_sizes':10,
            'long_convolution_renders':4,'periodic_wave_renders':4,'repeat_hashes_stable':True,
            'full_audio_parity_proven':False,'full_scope_complete':False,
            'scope':'Window, finite rational inputs, stereo not included here. Direct DFT selected bins, 4096-tap sparse convolution and custom periodic wave; not all values, devices/realtime/worklet/resampling/HRTF/performance or full cross-architecture parity.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--probe-dir',type=Path)
    a=p.parse_args();r=json.loads(a.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(a.probe_dir/Path(f).name if a.probe_dir else Path(f))==h
    print(json.dumps(verify(r,digest(a.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))
