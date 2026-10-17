#!/usr/bin/env python3
"""Build/run the exact adapter with Chromium media/base, in an owned Linux out."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys,time
root=Path(sys.argv[1]).resolve(strict=True)
project=Path(__file__).resolve().parents[1]
assert root.name=='linux-reference-v20h'
fixture=root/'metabrowser_audio_clock_test';fixture.mkdir(exist_ok=True)
marker=fixture/'.metabrowser-owned-clock-test'
assert marker.exists() or not any(fixture.iterdir())
marker.write_text('owned-audio-clock-test')
inputs={'adapter.inc':project/'chromium/privacy/metabrowser_audio_clock_sink.inc',
        'native_test.cc':project/'tests/integration/audio_clock_sink_native_test.cc'}
for name,p in inputs.items():(fixture/name).write_bytes(p.read_bytes())
# Production staging expands this exact body inside a .cc translation unit.
# Match that compilation context: Chromium's header-style plugin rejects the
# same inlined class when compiled as a header, although it is valid in .cc.
expanded = inputs['native_test.cc'].read_text().replace(
    '#include "adapter.inc"', inputs['adapter.inc'].read_text())
(fixture/'native_test.cc').write_text(expanded)
(fixture/'BUILD.gn').write_text('''executable("metabrowser_audio_clock_tests") {
  testonly = true
  sources = [ "native_test.cc" ]
  deps = [ "//base", "//media", "//testing/gtest" ]
}
''')
out=root/'out/metabrowser-audio-clock-tests';out.mkdir(exist_ok=True)
args=(root/'out/metabrowser-linux-reference/args.gn').read_text()+'\nroot_extra_deps = [ "//metabrowser_audio_clock_test:metabrowser_audio_clock_tests" ]\n'
(out/'args.gn').write_text(args)
media_inputs = ['media/audio/null_audio_sink.cc','media/audio/null_audio_sink.h','media/base/fake_audio_worker.cc','media/base/fake_audio_worker.h','media/base/audio_fifo.cc','media/base/audio_fifo.h','media/base/audio_bus.cc','media/base/audio_bus.h','media/base/audio_renderer_sink.h']
media_hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in media_inputs}
status={'state':'building','pid':os.getpid(),'source':str(root),'started':time.time(),
 'fixture_sha256':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in inputs.items()},
 'args_sha256':hashlib.sha256(args.encode()).hexdigest(),
 'expanded_test_sha256':hashlib.sha256(expanded.encode()).hexdigest(),
 'media_source_sha256':media_hashes,'real_hardware_verified':False}
logs=out/'clock-evidence';logs.mkdir(exist_ok=True)
def save():(logs/'status.json').write_text(json.dumps(status,indent=2)+'\n')
def run(command,name):
 with (logs/name).open('wb') as stream:
  process=subprocess.Popen(command,cwd=root,stdout=stream,stderr=stream)
  status.update(child_pid=process.pid,command=command);save()
  code=process.wait();status['exit_code']=code;save();assert code==0,(name,code)
save()
try:
 run([str(root/'buildtools/linux64/gn'),'gen',str(out),'--fail-on-unused-args'],'gn.log')
 run([str(root/'third_party/ninja/ninja'),'-C',str(out),'-j','64','metabrowser_audio_clock_tests'],'build.log')
 for name,p in inputs.items():assert hashlib.sha256(p.read_bytes()).hexdigest()==status['fixture_sha256'][name]
 assert hashlib.sha256((fixture/'native_test.cc').read_bytes()).hexdigest()==status['expanded_test_sha256']
 for name,want in media_hashes.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==want
 binary=out/'metabrowser_audio_clock_tests'
 status['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest();save()
 run([str(out/'metabrowser_audio_clock_tests'),'--gtest_color=no'],'tests.log')
 assert hashlib.sha256(binary.read_bytes()).hexdigest()==status['binary_sha256']
 for name,want in media_hashes.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==want
 status['tests_log_sha256']=hashlib.sha256((logs/'tests.log').read_bytes()).hexdigest()

 status['state']='passed';status['seconds']=time.time()-status['started'];save()
except BaseException as error:
 status.update(state='failed',error=str(error),seconds=time.time()-status['started']);save();raise
