"""Verify actual captured Chromium process-title encoding without heuristic parsing."""
import json
from pathlib import Path
import sys
from patched_linux_audio_runner import attest_proc_arguments

r=json.loads(Path(sys.argv[1]).read_text());exe='/data/metabrowser/source/linux-reference-v20h/out/metabrowser-linux-reference/headless_shell'
canonical,kind=attest_proc_arguments(r['actual'],exe,r['expected']);assert kind=='single-process-title'
assert canonical==[exe,*r['expected']]
assert attest_proc_arguments(canonical,exe,r['expected'])[1]=='nul-separated'
for actual,expected in [(r['actual']+['--forged'],r['expected']),([r['actual'][0]+' --forged'],r['expected']),
                        ([exe+' --type=renderer two words'],['--type=renderer','two words'])]:
 try:attest_proc_arguments(actual,exe,expected)
 except AssertionError:continue
 raise AssertionError('Accepted forged/ambiguous process title')
print('Actual Chromium title and native argv accepted; forged/ambiguous titles rejected')
