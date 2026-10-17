#!/usr/bin/env python3
"""Stage persona-only Biquad recurrence; leave native Accelerate/C++ intact."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=Path)
p.add_argument('--apply', action='store_true')
a = p.parse_args()
root = a.source.resolve(strict=True)
assert (root / 'chrome/VERSION').read_text().splitlines() == [
    'MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']
name = 'third_party/blink/renderer/platform/audio/biquad.cc'
path = root / name
assert not path.is_symlink() and path.resolve().is_relative_to(root)
original = path.read_bytes()
text = original.decode()
body = (Path(__file__).resolve().parents[1] /
        'chromium/privacy/metabrowser_biquad_process.inc').read_text()
block = '// METABROWSER_BIQUAD_PROCESS_BEGIN\n' + body + '// METABROWSER_BIQUAD_PROCESS_END\n'
helper = '''namespace {
bool MetaBrowserPortableBiquadProcess() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool enabled = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return enabled;
}
}  // namespace
'''
def edit(old, new):
    global text
    if new in text:
        assert text.count(new) == 1
    else:
        assert text.count(old) == 1, ('Biquad source drift', old[:80])
        text = text.replace(old, new)

if '// METABROWSER_BIQUAD_PROCESS_BEGIN' in text:
    assert text.count(block) == 1, 'Biquad recurrence drift'
edit('#include "third_party/blink/renderer/platform/audio/biquad.h"',
     '#include "third_party/blink/renderer/platform/audio/biquad.h"\n'
     '#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"')
edit('#include <complex>', '#include <complex>\n#include <cmath>')
edit('namespace blink {', 'namespace blink {\n' + helper)
anchor = '  DCHECK_EQ(source.size(), dest.size());'
edit(anchor, anchor + '\n' + block)
assert path.read_bytes() == original
if a.apply and text.encode() != original:
    path.write_bytes(text.encode())
print(json.dumps({'scope': 'cohort-biquad-double-history-no-contraction',
                  'applied': a.apply, 'runtime_verified': False,
                  'full_scope_complete': False,
                  'all_files': {name: hashlib.sha256(text.encode()).hexdigest()}}))
