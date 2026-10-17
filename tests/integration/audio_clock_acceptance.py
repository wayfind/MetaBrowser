"""Verify actual public clock-delay policy, without claiming physical output QA."""
import argparse,json,math
from pathlib import Path
from audio_public_device_acceptance import compare as compare_static


def compare(first,second,archives):
 result=compare_static(first,second,archives)
 for report in (first,second):
  for row in report['observations']['rows']:
   for sample in row['samples']:
    # No capture permission was requested in these owned fresh profiles. The
    # pinned source quantizes output latency to 8ms in this permission state.
    expected=math.floor(2*sample['baseLatency']/.008+.5)*.008
    assert math.isclose(sample['outputLatency'],expected,rel_tol=0,abs_tol=1e-12),(row,sample,expected)
 # Dynamic timestamps are compared through invariants in the context verifier,
 # never exact values across independent launches. OS scheduling remains visible.
 result.update(public_clock_delay_cases=60,physical_callback_timestamps_forwarded=False,
               real_hardware_playback_verified=False,complete_timing_privacy_proven=False)
 return result


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('first',type=Path);p.add_argument('second',type=Path);p.add_argument('--archives',type=Path,required=True);a=p.parse_args()
 print(json.dumps(compare(json.loads(a.first.read_text()),json.loads(a.second.read_text()),a.archives),indent=2))
