"""Exercise exec/proc attestation with an owned native stub, not a browser claim."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from patched_linux_audio_runner import verify_renderer_transport

assert os.uname().sysname=='Linux'
here=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='metabrowser-renderer-transport-test-') as directory:
 root=Path(directory);(root/'.metabrowser-owned-fixture').write_text('patched-linux-audio-reference')
 code=root/'stub.c';code.write_text('#include <unistd.h>\nint main(void) { sleep(30); return 0; }\n')
 exe=root/'headless_shell';subprocess.run(['cc',str(code),'-o',str(exe)],check=True)
 env=dict(os.environ,METABROWSER_LINUX_REFERENCE_ROOT=str(root),METABROWSER_LINUX_REFERENCE_BINARY=str(exe))
 process=subprocess.Popen([sys.executable,str(here/'linux_persona_launcher.py'),str(exe),'--type=renderer','--','literal'],env=env)
 try:
  for _ in range(100):
   paths=list(root.glob('renderer-launch-*.json'))
   if paths and Path('/proc',str(process.pid),'exe').resolve()==exe:break
   assert process.poll() is None;time.sleep(.02)
  else:raise AssertionError('Owned native exec did not become ready')
  records=verify_renderer_transport(root,exe);assert records[0]['pid']==process.pid
  path=paths[0];original=path.read_bytes();bad=json.loads(original);bad['arguments'].append('--forged');path.write_text(json.dumps(bad))
  try:verify_renderer_transport(root,exe)
  except AssertionError:pass
  else:raise AssertionError('Forged recorded arguments accepted')
  path.write_bytes(original)
 finally:process.terminate();process.wait(timeout=5)
 try:verify_renderer_transport(root,exe)
 except AssertionError:pass
 else:raise AssertionError('Dead renderer record accepted')
 print(json.dumps({'native_exec_proc_attestation_passed':True,'forged_arguments_rejected':True,'dead_record_rejected':True,'actual_browser_backend_proven':False}))
