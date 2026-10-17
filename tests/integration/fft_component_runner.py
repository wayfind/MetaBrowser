"""Build same production FFT core for Linux and cross-compiled Mac; thin test ABI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();source=a.source.resolve(strict=True);work=a.output.resolve();assert not work.exists(),'Fresh component workspace required'
work.mkdir(parents=True);(work/'.metabrowser-owned-fixture').write_text('fft-component')
here=Path(__file__).resolve().parent;prefix='third_party/blink/renderer/platform/audio/'
ffi=source/prefix/'rustfft_ffi.rs';raw=ffi.read_text();assert raw.count('#[cxx::bridge')==1
(work/'engine.rs').write_text(raw.split('#[cxx::bridge',1)[0]+(here/'fft_component_cases.rs').read_text())
(work/'lib.rs').write_text('#[path="engine.rs"] mod engine;\n#[no_mangle] pub extern "C" fn mb_fft_component_run()->i32 {engine::component_run()}\n')
vendor=source/'third_party/rust/chromium_crates_io/vendor'
(work/'Cargo.toml').write_text('[package]\nname="metabrowser_fft_component"\nversion="0.1.0"\nedition="2021"\n[lib]\npath="lib.rs"\ncrate-type=["staticlib"]\n[dependencies]\nrustfft={path='+json.dumps(str(vendor/'rustfft-v6'))+'}\n[profile.release]\npanic="abort"\ndebug=0\n')
home=work/'cargo-home';home.mkdir();(home/'config.toml').write_text('[source.crates-io]\nreplace-with="vendored-sources"\n[source.vendored-sources]\ndirectory='+json.dumps(str(vendor))+'\n')
tool=source/'third_party/rust-toolchain/bin';cargo=tool/'cargo';rustc=tool/'rustc'
env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR')}
env.update(CARGO_HOME=str(home),RUSTC=str(rustc),CARGO_BUILD_JOBS='8',MACOSX_DEPLOYMENT_TARGET='13.0')
hashfile=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
inputs=[ffi,source/prefix/'metabrowser_fft_math.h',source/'third_party/fdlibm/ieee754.cc',source/'third_party/fdlibm/ieee754.h',*here.glob('fft_component_*')]
inputs.extend((vendor/'rustfft-v6/src').rglob('*.rs'))
for package in ['num-complex','num-traits','num-integer','primal-check','transpose','strength_reduce','autocfg']:
    for folder in vendor.glob(package+'-v*'):
        inputs.extend(f for f in folder.rglob('*') if f.is_file() and f.suffix in ('.rs','.toml'))
before={str(f):hashfile(f) for f in inputs if f.is_file()}
report={'completed':False,'full_audio_parity_proven':False,'source_sha256':before,'workspace':str(work),
        'rustc_version':subprocess.check_output([str(rustc),'--version'],text=True).strip(),
        'scope':'Production Rust implementation with only CXX transport declaration replaced by thin C ABI using same production fdlibm header. Not browser realtime FP mode, devices or full DSP parity.'}
def run(cmd,name):
    with (work/name).open('w') as log:subprocess.run([str(x) for x in cmd],cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
try:
    for target in ('x86_64-unknown-linux-gnu','aarch64-apple-darwin'):
        if target=='aarch64-apple-darwin':
            sysroot=source/'out/metabrowser-mac-arm64/local_rustc_sysroot'
            assert (sysroot/'lib/rustlib/aarch64-apple-darwin/lib').is_dir()
            env['CARGO_ENCODED_RUSTFLAGS']='--sysroot='+str(sysroot)
            report['mac_production_sysroot']=str(sysroot)
        run([cargo,'build','--release','--offline','--manifest-path',work/'Cargo.toml','--target',target],target+'-cargo.log')
    clang=source/'third_party/llvm-build/Release+Asserts/bin/clang++'
    common=[clang,'-std=c++20','-O2','-DNDEBUG','-ffp-contract=off','-fPIC','-I'+str(source),'-I'+str(source/'out/metabrowser-mac-arm64/gen')]
    run([*common,'-c',source/'third_party/fdlibm/ieee754.cc','-o',work/'fdlibm-linux.o'],'fdlibm-linux.log')
    lib=work/'target/x86_64-unknown-linux-gnu/release/libmetabrowser_fft_component.a'
    run([*common,here/'fft_component_driver.cc',here/'fft_component_shim.cc',work/'fdlibm-linux.o',lib,'-pthread','-ldl','-lm','-lrt','-lutil','-o',work/'component-linux'],'linux-link.log')
    run([work/'component-linux'],'linux-run.log')
    report['linux_output_sha256']=hashfile(work/'fft-component.bin')
    engine_out=source/'out/metabrowser-mac-arm64'
    object_relative='obj/third_party/fdlibm/fdlibm/ieee754.o'
    command=subprocess.check_output([str(source/'third_party/ninja/ninja'),'-C',str(engine_out),'-t','commands',object_relative]).decode('utf-8',errors='replace')
    words=shlex.split(command.splitlines()[-1]);assert '-ffp-contract=off' in words
    sdk=Path(words[words.index('-isysroot')+1]);sdk=(engine_out/sdk).resolve() if not sdk.is_absolute() else sdk
    assert sdk.is_dir()
    mac_lib=work/'target/aarch64-apple-darwin/release/libmetabrowser_fft_component.a'
    run([clang,'--target=arm64-apple-macos13.0','-isysroot',sdk,'-fuse-ld=lld','-Wl,-dead_strip',
         '-I'+str(source),here/'fft_component_driver.cc',here/'fft_component_shim.cc',
         engine_out/object_relative,mac_lib,'-liconv','-framework','Security','-framework','CoreFoundation',
         '-o',work/'component-mac'],'mac-cross-link.log')
    report['mac_fdlibm_production_object_sha256']=hashfile(engine_out/object_relative)
    report['mac_component_sha256']=hashfile(work/'component-mac')
    for target in ('x86_64-unknown-linux-gnu','aarch64-apple-darwin'):
        report[target+'_staticlib_sha256']=hashfile(work/'target'/target/'release/libmetabrowser_fft_component.a')
    assert all(hashfile(Path(f))==h for f,h in before.items()),'Production inputs changed during component build'
    report['completed']=True
finally:
    (work/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'completed':True,'linux_output_sha256':report['linux_output_sha256']}))
