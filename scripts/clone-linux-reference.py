#!/usr/bin/env python3
"""Copy an owned reference tree, then overlay a content-addressed Mac source snapshot.

No hard links or in-place writes are used. The old reference stays executable.
"""
import argparse,hashlib,json,os
from pathlib import Path
import subprocess,time
p=argparse.ArgumentParser(description=__doc__)
for flag in ('base','destination','mac-source','parent-receipt'):p.add_argument('--'+flag,type=Path,required=True)
p.add_argument('--expected-parent-sha256',required=True);a=p.parse_args()
base=a.base.resolve(strict=True);mac=a.mac_source.resolve(strict=True);dst=a.destination.absolute()
assert base.name=='linux-reference-v20h' and dst.name=='linux-reference-v20l2' and dst.parent==base.parent
assert not dst.exists() and not dst.is_symlink()
raw=a.parent_receipt.read_bytes();digest=hashlib.sha256(raw).hexdigest();assert digest==a.expected_parent_sha256
parent=json.loads(raw);assert parent['framework_sha256']=='f46dc3e5ff57df7498af5f12beb3aaa987fc6c375876b6138b12dd3a480fdd00'
sources={name:value for name,value in parent['sources'].items() if not name.startswith('out/')}
def check_mac():
 for name,want in sources.items():assert hashlib.sha256((mac/name).read_bytes()).hexdigest()==want,name
check_mac()
logs=base.parent/'linux-reference-v20l2-clone-evidence';logs.mkdir(exist_ok=True)
status={'state':'copying','pid':os.getpid(),'base':str(base),'destination':str(dst),'started':time.time(),'parent_receipt_sha256':digest,'parent_mac_framework_sha256':parent['framework_sha256'],'copy_method':'rsync-a-without-hardlinks-or-inplace','gpu_workloads_started':False}
def save():(logs/'status.json').write_text(json.dumps(status,indent=2)+'\n')
def atomic(path,data):
 assert not path.is_symlink() and path.parent.resolve().is_relative_to(dst.resolve())
 temporary=path.with_name(path.name+'.metabrowser-clone-new');assert not temporary.exists()
 temporary.write_bytes(data);os.replace(temporary,path)
save()
try:
 dst.mkdir()
 command=['rsync','-a','--exclude=/out/metabrowser-audio-clock-tests','--exclude=/metabrowser_audio_clock_test',str(base)+'/',str(dst)+'/']
 with (logs/'copy.log').open('wb') as stream:
  child=subprocess.Popen(command,stdout=stream,stderr=stream);status['copy_pid']=child.pid;save();code=child.wait();assert code==0,code
 assert (dst/'out/metabrowser-linux-reference').resolve().is_relative_to(dst)
 check_mac();changed=[]
 for name,want in sources.items():
  path=dst/name;path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==want:continue
  atomic(path,(mac/name).read_bytes());changed.append(name)
 for name,want in sources.items():assert hashlib.sha256((dst/name).read_bytes()).hexdigest()==want,name
 toolchain=base/'third_party/llvm-build/Release+Asserts'
 compiler=toolchain/'bin/clang';compiler_hash=hashlib.sha256(compiler.read_bytes()).hexdigest()
 marker={'schema_version':2,'kind':'owned-linux-same-patch-source-snapshot','state':'source-snapshot-complete','destination':str(dst),'base_source':str(base),'parent_receipt_sha256':digest,'parent_mac_framework_sha256':parent['framework_sha256'],'source_sha256':sources,'toolchain_root':str(toolchain),'compiler_sha256':compiler_hash,'changed_overlay_files':changed,'copy_method':status['copy_method']}
 atomic(dst/'.metabrowser-owned-linux-reference-snapshot.json',json.dumps(marker,indent=2).encode()+b'\n')
 atomic(dst/'parent-mac-l2-receipt.json',raw)
 status.update(state='source-snapshot-complete',source_files=len(sources),changed_overlay_files=changed,seconds=time.time()-status['started']);save()
except BaseException as error:
 status.update(state='failed',error=str(error),seconds=time.time()-status['started']);save();raise
