"""Compile the exact staged selector and exercise pre-init then configured use."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--stager',type=Path,default=Path('scripts/stage-privacy-identity.py'))
p.add_argument('--expect-failure',action='store_true')
a=p.parse_args()
constants=[n.value for n in ast.walk(ast.parse(a.stager.read_text())) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('namespace {\nbool MetaBrowserScalarAudioVectorMath()')]
assert len(constants)==1
helper=constants[0].removesuffix('#if BUILDFLAG(IS_MAC)')+'}\n'
assert '#if' not in helper
source=r'''
#include <cassert>
#include <string_view>
#include "chromium/identity/persona.h"
bool initialized=false;
int selected_calls=0;
bool scalar_requested=false;
namespace base {
struct CommandLine {
 static bool InitializedForCurrentProcess() {return initialized;}
};
}
namespace metabrowser {
const Persona* EmulatedPersona() {
 if(!initialized)return nullptr;
 ++selected_calls;
 return scalar_requested?&kLinuxSoftwarePersona:nullptr;
}
}
''' + helper + r'''
int main(int argc,char** argv) {
 assert(argc==2);
 scalar_requested=std::string_view(argv[1])=="scalar";
 assert(!MetaBrowserScalarAudioVectorMath());
 assert(selected_calls==0);
 initialized=true;
 for(int i=0;i<1000;i++)assert(MetaBrowserScalarAudioVectorMath()==scalar_requested);
 assert(selected_calls==1);
}
'''
with tempfile.TemporaryDirectory(prefix='metabrowser-audio-init-') as temp:
    root=Path(temp);file=root/'test.cc';file.write_text(source);binary=root/'test'
    compile=subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-I.',str(file),'-o',str(binary)],capture_output=True,text=True)
    assert compile.returncode==0,compile.stderr
    results={}
    for choice in ('scalar','native'):
        result=subprocess.run([str(binary),choice],capture_output=True,text=True)
        results[choice]={'exit_code':result.returncode,'stderr':result.stderr}
    assert all((r['exit_code']!=0 if a.expect_failure else r['exit_code']==0) for r in results.values()),results
    print(json.dumps({'regression_reproduced':a.expect_failure,'fixed_selector_passed':not a.expect_failure,
          'production_selector_sha256':hashlib.sha256(helper.encode()).hexdigest(),
          'stager_sha256':hashlib.sha256(a.stager.read_bytes()).hexdigest(),
          'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'scope':'Exact staged function; mock process readiness/persona lookup only. Native pre-init browser invocation is not claimed.',
          'results':results},indent=2))
