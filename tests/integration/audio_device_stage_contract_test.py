"""Exercise the exact staged native buffer policy, including hostile hints."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

source=Path(sys.argv[1]);project=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='metabrowser-audio-policy-contract-') as temp:
 root=Path(temp);(root/'chrome').mkdir();(root/'chrome/VERSION').write_text('MAJOR=154\nMINOR=0\nBUILD=8037\nPATCH=97\n')
 p=root/'content/renderer/media/renderer_webaudiodevice_impl.cc';p.parent.mkdir(parents=True);p.write_bytes(source.read_bytes())
 command=[sys.executable,str(project/'scripts/stage-privacy-audio-device.py'),str(root)]
 preview=json.loads(subprocess.check_output(command,text=True));assert p.read_bytes()==source.read_bytes()
 staged=json.loads(subprocess.check_output(command+['--apply'],text=True));raw=p.read_bytes()
 assert json.loads(subprocess.check_output(command+['--apply'],text=True))==staged and raw==p.read_bytes()
 text=raw.decode();start=text.index('constexpr int kMetaBrowserAudioSampleRate');end=text.index('// METABROWSER_PUBLIC_AUDIO_DEVICE_END',start)
 body=text[start:end]
 stub='''#include <algorithm>
#include <cmath>
#include <cassert>
#include <limits>
#include <cstdlib>
#define NOTREACHED() std::abort()
constexpr int kMinWebAudioBufferSize=128;
constexpr int kMaxWebAudioBufferSize=8192;
struct WebAudioLatencyHint {
 enum AudioContextLatencyCategory {kCategoryInteractive,kCategoryBalanced,kCategoryPlayback,kCategoryExact,kLastValue};
 AudioContextLatencyCategory category; double seconds=0;
 auto Category() const {return category;} double Seconds() const {return seconds;}
};
'''
 tests='''int main() {
 using H=WebAudioLatencyHint;
 assert(MetaBrowserPublicAudioBufferSize({H::kCategoryInteractive},48000)==256);
 assert(MetaBrowserPublicAudioBufferSize({H::kCategoryBalanced},48000)==512);
 assert(MetaBrowserPublicAudioBufferSize({H::kCategoryPlayback},48000)==1024);
 assert(MetaBrowserPublicAudioBufferSize({H::kCategoryExact,.1},48000)==4864);
 for(int rate:{3000,44100,48000,96000,192000,384000}) {
  for(double hint:{-1.,0.,1e-300,.001,.1,10.,1e300,
   std::numeric_limits<double>::infinity(),-std::numeric_limits<double>::infinity(),
   std::numeric_limits<double>::quiet_NaN()}) {
   int size=MetaBrowserPublicAudioBufferSize({H::kCategoryExact,hint},rate);
   assert(size>=128 && size<=8192 && size%128==0);
  }
 }
}
'''
 cpp=root/'policy.cc';cpp.write_text(stub+body+tests)
 subprocess.run(['c++','-std=c++17','-fsanitize=undefined,float-cast-overflow',str(cpp),'-o',str(root/'policy')],check=True)
 subprocess.run([str(root/'policy')],check=True)
 p.write_text(text.replace('seconds = 0.01;','seconds = 0.1;'))
 failed=subprocess.run(command+['--apply'],capture_output=True,text=True);assert failed.returncode!=0
 print(json.dumps({'preview_no_mutation':True,'idempotent':True,'altered_policy_rejected':True,
 'actual_policy_compiled':True,'ubsan_passed':True,'exact_hint_boundary_cases':60,
 'scope':'buffer-policy-unit-only-not-browser-or-clock-privacy',
 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'staged':staged}))
