#!/usr/bin/env python3
"""Stage cohort complex-analysis math used by HRTF kernel preparation."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
name='third_party/blink/renderer/platform/audio/fft_frame.cc';path=root/name
assert not path.is_symlink() and path.resolve().is_relative_to(root)
original=path.read_bytes();text=original.decode()
body=(Path(__file__).resolve().parents[1]/'chromium/privacy/metabrowser_fft_complex_math.inc').read_text()
block='namespace {\n// METABROWSER_FFT_COMPLEX_BEGIN\n'+body+'// METABROWSER_FFT_COMPLEX_END\n}  // namespace\n'
if '// METABROWSER_FFT_COMPLEX_BEGIN' in text:assert text.count(block)==1,'Complex math source drift'
def edit(old,new,count=1):
 global text
 if new in text:assert text.count(new)==count
 else:
  assert text.count(old)==count,('HRTF source drift',old[:90],text.count(old));text=text.replace(old,new)
edit('#include <complex>','#include <algorithm>\n#include <complex>\n#include <cmath>\n#include <limits>')
anchor='  return portable;\n}\n}  // namespace'
edit(anchor,anchor+'\n'+block)
for variable,count in [('c1',1),('c2',1),('c',2)]:
 edit('= abs('+variable+');','= MetaBrowserFftMagnitude('+variable+');',count)
 edit('= arg('+variable+');','= MetaBrowserFftPhase('+variable+');',count)
edit('std::polar(mag, phase_accum)','MetaBrowserFftPolar(mag, phase_accum)')
edit('std::polar(mag, phase)','MetaBrowserFftPolar(mag, phase)')
edit('#include "base/check_op.h"','#include "base/check_op.h"\n#include "base/trace_event/trace_event.h"')
for stage,head in [
 ('interpolate','void FFTFrame::InterpolateFrequencyComponents(const FFTFrame& frame1,\n                                              const FFTFrame& frame2,\n                                              double interp) {'),
 ('group-delay','double FFTFrame::ExtractAverageGroupDelay() {'),
 ('phase-adjust','void FFTFrame::AddConstantGroupDelay(double sample_frame_delay) {')]:
 edit(head,head+'\n  TRACE_EVENT_INSTANT("audio", "MetaBrowser HRTF complex backend",\n                      "stage", "'+stage+'", "portable", MetaBrowserPortableFft());')

assert text.count(block)==1 and path.read_bytes()==original
if a.apply and text.encode()!=original:path.write_bytes(text.encode())
print(json.dumps({'scope':'cohort-finite-complex-hrtf-analysis','applied':a.apply,'full_hrtf_privacy_proven':False,'all_files':{name:hashlib.sha256(text.encode()).hexdigest()}}))
