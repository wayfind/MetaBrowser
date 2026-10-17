"""A coherent NaN-payload difference must fail cross CPU despite valid DSP math."""
import argparse,base64,copy,json,shutil,struct,tempfile
from pathlib import Path
from audio_pipeline_cross_acceptance import compare,sha
from audio_biquad_matrix_acceptance import verify

p=argparse.ArgumentParser(description=__doc__)
for n in ('mac','linux','mac-receipt','linux-receipt','mac-raw-root','linux-raw-root','mac-probe-dir','linux-probe-dir'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();m=json.loads(a.mac.read_text());l=json.loads(a.linux.read_text());mr=json.loads(a.mac_receipt.read_text());lr=json.loads(a.linux_receipt.read_text())
def invoke(left,right):
 with tempfile.TemporaryDirectory() as d:
  roots=[]
  for name,source,report in [('mac',a.mac_raw_root,left),('linux',a.linux_raw_root,right)]:
   dst=Path(d)/name;dst.mkdir();roots.append(dst)
   for f in source.iterdir():
    if f.is_file():shutil.copy2(f,dst/f.name)
   raw=json.loads((dst/'probe-process.private.json').read_text());raw['stdout']=json.dumps(report['observations']);(dst/'probe-process.private.json').write_text(json.dumps(raw))
  return compare(left,right,mr,lr,sha(a.mac_receipt),sha(a.linux_receipt),*roots,a.mac_probe_dir,a.linux_probe_dir)
assert invoke(m,l)['fixture_buffers_identical'] is True
bad=copy.deepcopy(l)
# Index six is deliberately invalid frequency: the API still exposes its NaN
# bits through a typed-array view. Change a payload bit without changing NaN.
for row in bad['observations']['rows']:
 r=row['response'];raw=base64.b64decode(r['magnitudeFloat32Base64']);words=list(struct.unpack('<8I',raw));words[6]^=1
 r['magnitudeFloat32Base64']=base64.b64encode(struct.pack('<8I',*words)).decode()
verify(bad['observations'])
result=invoke(m,bad)
assert result['functional_checks_passed'] and result['hashes_equal']==result['hashes_compared']==96
assert result['fixture_buffers_identical'] is False and result['frequency_response_float32_buffers_equal'] is False
assert len(result['frequency_response_mismatches'])==96
print(json.dumps({'real_baseline_equal':True,'coherent_nan_payload_difference_detected':True,'render_hash_equality_alone_rejected':True,'synthetic_changes_are_not_browser_observations':True}))
