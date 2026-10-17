#!/usr/bin/env python3
"""Build an isolated, same-patch headless Linux DSP reference; not a shipped product."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--parent-receipt',type=Path,required=True);p.add_argument('--jobs',type=int,default=64);a=p.parse_args()
assert 1<=a.jobs<=96
root=a.source.resolve(strict=True)
marker=json.loads((root/'.metabrowser-owned-linux-reference-snapshot.json').read_text())
assert marker['state']=='source-snapshot-complete' and marker['destination']==str(root)
parent_raw=a.parent_receipt.read_bytes();assert hashlib.sha256(parent_raw).hexdigest()==marker['parent_receipt_sha256']
parent=json.loads(parent_raw)
if marker.get('schema_version')==2:
 assert marker['kind']=='owned-linux-same-patch-source-snapshot'
 assert parent['framework_sha256']==marker['parent_mac_framework_sha256']
 assert marker['source_sha256']=={name:value for name,value in parent['sources'].items() if not name.startswith('out/')}
 toolchain=Path(marker['toolchain_root']).resolve(strict=True)
 assert toolchain==Path(marker['base_source'])/'third_party/llvm-build/Release+Asserts'
 assert hashlib.sha256((toolchain/'bin/clang').read_bytes()).hexdigest()==marker['compiler_sha256']
else:
 # Preserve the original strict H snapshot contract.
 assert parent['framework_sha256']=='9e7ddb445b1b0a4b9516fedfb4b2ff7d9bb382bf52b1912a8647f6d83224ddbe'
 toolchain=root/'third_party/llvm-build/Release+Asserts'
sources={name:value for name,value in parent['sources'].items() if not name.startswith('out/')}
domain_sources=marker.get('domain_source_sha256',{})
def check_sources():
 for name,want in {**sources,**domain_sources}.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==want,name
check_sources()
out=root/'out/metabrowser-linux-reference';out.mkdir(parents=True,exist_ok=True);logs=out/'reference-evidence';logs.mkdir(exist_ok=True)
(logs/'parent-mac-receipt.json').write_bytes(parent_raw)
args='''target_os = "linux"
target_cpu = "x64"
is_debug = false
is_component_build = false
is_official_build = false
use_remoteexec = false
use_siso = false
symbol_level = 0
blink_symbol_level = 0
v8_symbol_level = 0
proprietary_codecs = true
ffmpeg_branding = "Chrome"
'''+f'clang_base_path = "{toolchain}"\n'
(out/'args.gn').write_text(args)
status={'kind':'isolated-same-patch-linux-headless-reference-build','pid':os.getpid(),'source':str(root),
        'target':'headless_shell','target_cpu':'x64','started':time.time(),'state':'configuring',
        'parent_mac_framework_sha256':parent['framework_sha256'],'parent_receipt_sha256':hashlib.sha256(parent_raw).hexdigest(),
        'source_sha256':sources,'domain_source_sha256':domain_sources,'args_sha256':hashlib.sha256(args.encode()).hexdigest(),
        'builder_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'snapshot_marker_sha256':hashlib.sha256((root/'.metabrowser-owned-linux-reference-snapshot.json').read_bytes()).hexdigest(),
        'toolchain_root':str(toolchain),
        'full_browser_product_parity_proven':False,'gpu_workloads_started':False}
status_file=logs/'status.json'
def save():status_file.write_text(json.dumps(status,indent=2)+'\n')
def run(command,name):
 with (logs/name).open('wb') as stream:
  process=subprocess.Popen(command,cwd=root,stdout=stream,stderr=stream)
  status.update(child_pid=process.pid,command=command);save()
  result=process.wait();status['last_exit_code']=result;save()
  if result:raise subprocess.CalledProcessError(result,command)
save()
try:
 run([str(root/'buildtools/linux64/gn'),'gen',str(out),'--fail-on-unused-args'],'gn-gen.log')
 status['state']='building';save()
 run([str(root/'third_party/ninja/ninja'),'-C',str(out),'-j',str(a.jobs),'headless_shell'],'ninja-build.log')
 check_sources()
 binary=out/'headless_shell';assert binary.is_file()
 with binary.open('rb') as stream:status['binary_sha256']=hashlib.file_digest(stream,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else None
 if status['binary_sha256'] is None:
  digest=hashlib.sha256()
  with binary.open('rb') as stream:
   for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
  status['binary_sha256']=digest.hexdigest()
 status.update(state='build-complete',seconds=time.time()-status['started']);save()
 print(json.dumps({'state':status['state'],'binary_sha256':status['binary_sha256']}),flush=True)
except BaseException as error:
 status.update(state='build-failed',error=str(error),seconds=time.time()-status['started']);save();raise
