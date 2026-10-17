#!/usr/bin/env python3
"""Stage the experimental public-clock / physical-output WebAudio adapter."""
import argparse
import hashlib
import json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
name='content/renderer/media/renderer_webaudiodevice_impl.cc';path=root/name
assert not path.is_symlink() and path.resolve().is_relative_to(root)
original=path.read_text();text=original
assert 'bool MetaBrowserPublicAudioDevice()' in text,'Public stream policy prerequisite missing'
body=(Path(__file__).resolve().parents[1]/'chromium/privacy/metabrowser_audio_clock_sink.inc').read_text()
block='// METABROWSER_AUDIO_CLOCK_BEGIN\n'+body+'// METABROWSER_AUDIO_CLOCK_END\n\n'
if '// METABROWSER_AUDIO_CLOCK_BEGIN' in text:assert text.count(block)==1,'Public audio clock source drift'
def edit(old,new):
 global text
 if new in text:assert text.count(new)==1
 else:
  assert text.count(old)==1,('Audio clock source drift',old[:100]);text=text.replace(old,new)
edit('#include "base/check_op.h"','#include "base/check_op.h"\n#include "base/sequence_checker.h"\n#include "base/synchronization/lock.h"')
edit('#include "media/base/audio_bus.h"','#include "media/base/audio_bus.h"\n#include "media/base/audio_fifo.h"')
edit('scoped_refptr<media::AudioRendererSink> GetNullAudioSink(',block+'scoped_refptr<media::AudioRendererSink> GetNullAudioSink(')
anchor='''      // Use a task runner instead of the render thread for fake Render() calls'''
edit(anchor,'''      if (MetaBrowserPublicAudioDevice()) {
        sink_ = base::MakeRefCounted<MetaBrowserAudioClockSink>(
            std::move(sink_), GetSilentSinkTaskRunner());
      }

'''+anchor)
assert text.count(block)==1
assert path.read_text()==original
if a.apply and text!=original:path.write_text(text)
print(json.dumps({'scope':'experimental-public-clock-private-output', 'applied':a.apply,
 'runtime_verified':False,'full_scope_complete':False,'all_files':{name:hashlib.sha256(text.encode()).hexdigest()}}))
