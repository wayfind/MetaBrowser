"""Parse full numeric artifacts before accepting cross-CPU byte equivalence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]


def parse(raw):
    assert raw[:8]==b'MBFFT001';offset=8
    def u32():
        nonlocal offset
        value=struct.unpack_from('<I',raw,offset)[0];offset+=4;return value
    def floats(n):
        nonlocal offset
        value=struct.unpack_from('<'+str(n)+'f',raw,offset);offset+=4*n
        assert all(math.isfinite(x) for x in value);return value
    assert u32()==110
    sizes=[2**n for n in range(1,16)]+[3,5,7,15,31,257,4097]
    maximum=0;float_count=0
    for n in sizes:
        for pattern in range(5):
            assert (u32(),u32(),u32())==(n,pattern,(n+1)//2)
            data=floats(n);real=floats((n+1)//2);imag=floats((n+1)//2);restored=floats(n);recorded=floats(1)[0]
            if pattern==0:expected=[f32(((i*17%257)-128)/137) for i in range(n)]
            elif pattern==1:expected=[1.0]+[0.0]*(n-1)
            elif pattern==2:expected=[1.0 if i%2==0 else -1.0 for i in range(n)]
            elif pattern==3:expected=[.25]*n
            else:
                expected=[0.0]*n;expected[n//3]=.5;expected[n//7]=-.25
            assert tuple(expected)==data
            error=max(abs(a-b) for a,b in zip(data,restored));assert error<=2e-5
            assert math.isclose(error,recorded,rel_tol=1e-6,abs_tol=1e-12)
            assert abs(real[0]-sum(data))<=n*2e-6
            if n%2==0:assert abs(imag[0]-sum(x if i%2==0 else -x for i,x in enumerate(data)))<=n*2e-6
            else:assert imag[0]==0
            if pattern==1:
                assert all(abs(x-1)<=n*2e-6 for x in real)
                assert all(abs(x)<=n*2e-6 for x in imag[1:])
            if pattern==3:
                assert all(abs(x)<=n*2e-6 for x in real[1:])
                assert all(abs(x)<=n*2e-6 for x in imag)
            maximum=max(maximum,error);float_count+=2*n+2*((n+1)//2)
    assert offset==len(raw)
    return {'cases':110,'sizes':22,'primary_float_values':float_count,'maximum_roundtrip_error':maximum}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('linux','mac','receipt','process','build-receipt'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=json.loads(a.receipt.read_text());process=json.loads(a.process.read_text());build=json.loads(a.build_receipt.read_text())
    assert r['completed'] is True and process['exit_code']==0
    assert 'component cases=110 cache_isolation=pass concurrent_cold_planning=pass' in process['stdout']
    assert digest(a.linux)==r['linux_output_sha256'] and a.linux.read_bytes()==a.mac.read_bytes()
    root='/data/metabrowser/source/unpacked/chromium-154.0.8037.97/'
    matched=0
    for name,h in r['source_sha256'].items():
        if name.startswith(root) and name[len(root):] in build['sources']:
            assert build['sources'][name[len(root):]]==h;matched+=1
    assert matched>=50
    result=parse(a.mac.read_bytes())
    result.update(passed=True,framework_sha256=build['framework_sha256'],full_numeric_buffers_byte_equal=True,
                  sha256=digest(a.mac),production_bound_source_files=matched,
                  full_audio_parity_proven=False,full_scope_complete=False,
                  scope=r['scope'],artifacts={str(x):digest(x) for x in [a.linux,a.mac,a.receipt,a.process,a.build_receipt,Path(__file__)]})
    print(json.dumps(result,indent=2))
