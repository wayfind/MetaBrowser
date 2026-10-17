"""Exercise real production staging on an owned seven-file source fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
for key in ('source','stager','old-stager','stage-receipt'):p.add_argument('--'+key,type=Path,required=True)
a=p.parse_args();receipt=json.loads(a.stage_receipt.read_text());files=receipt['all_files']
with tempfile.TemporaryDirectory(prefix='metabrowser-resampler-stage-contract-') as directory:
 root=Path(directory)
 for name in ['chrome/VERSION',*files]:
  dst=root/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a.source/name,dst)
 def run(script):return subprocess.run(['python3',str(script.resolve()),str(root)],capture_output=True,text=True)
 good=run(a.stager);assert good.returncode==0,good.stderr
 assert json.loads(good.stdout)['all_files']==files
 path=root/'media/base/sinc_resampler.cc';s=path.read_text();start=s.index('float SincResampler::Convolve_Portable(')
 tail=s[start:];assert '  float sum1 = 0;' in tail
 path.write_text(s[:start]+tail.replace('  float sum1 = 0;','  double sum1 = 0;',1))
 old=run(a.old_stager);assert old.returncode==0,old.stderr
 corrected=run(a.stager);assert corrected.returncode!=0 and 'Portable convolution source drift' in corrected.stderr
 print(json.dumps({'fresh_current_source_preflight_passed':True,'old_stager_incorrectly_accepts_changed_accumulation_type':True,
                   'new_stager_rejects_changed_accumulation_type':True,
                   'old_stager_sha256':hashlib.sha256(a.old_stager.read_bytes()).hexdigest(),
                   'new_stager_sha256':hashlib.sha256(a.stager.read_bytes()).hexdigest(),
                   'source_fixture_files':len(files),'new_stager_rejection':corrected.stderr}))
