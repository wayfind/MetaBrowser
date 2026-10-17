#!/usr/bin/env python3
"""Select fdlibm for remaining compressor transcendental calls in scalar persona."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
name='third_party/blink/renderer/platform/audio/dynamics_compressor.cc'
path=root/name
assert not path.is_symlink() and path.resolve().is_relative_to(root)
before=path.read_bytes();text=before.decode('utf-8')
def edit(old,new):
    global text
    if new in text:assert text.count(new)==1
    else:
        assert text.count(old)==1,('Compressor source drift',old)
        text=text.replace(old,new)
edit('#include "third_party/blink/renderer/platform/audio/dynamics_compressor.h"',
     '#include "third_party/blink/renderer/platform/audio/dynamics_compressor.h"\n#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"')
edit('namespace {\n\n// Metering', '''namespace {

bool MetaBrowserScalarCompressor() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool scalar = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return scalar;
}

double MetaBrowserCompressorSin(double value) {
  return MetaBrowserScalarCompressor() ? fdlibm::sin(value) : sin(value);
}

double MetaBrowserCompressorExp(double value) {
  return MetaBrowserScalarCompressor() ? fdlibm::exp(value) : exp(value);
}

// Metering''')
edit('sin(static_cast<double>(kPiOverTwoFloat * compressor_gain))',
     'MetaBrowserCompressorSin(static_cast<double>(kPiOverTwoFloat * compressor_gain))')
edit('static_cast<float>(exp(static_cast<double>(\n',
     'static_cast<float>(MetaBrowserCompressorExp(static_cast<double>(\n')
assert path.read_bytes()==before
if a.apply and text.encode('utf-8')!=before:path.write_bytes(text.encode('utf-8'))
print(json.dumps({'scope':'scalar-persona-compressor-sin-exp','applied':a.apply,
                  'all_files':{name:hashlib.sha256(text.encode('utf-8')).hexdigest()}}))
