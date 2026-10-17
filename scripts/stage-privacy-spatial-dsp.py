#!/usr/bin/env python3
"""Route two remaining WebAudio host transcendental sites through cohort fdlibm."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
before={};after={}
for filename,label,expression,replacement,function in [
 ('biquad_filter_handler.cc','BiquadDetune','exp2(detune / 1200)','MetaBrowserBiquadDetune(detune / 1200)',
  'double MetaBrowserBiquadDetune(float value) {\n  return MetaBrowserPortableBiquadDetune() ? fdlibm::pow(2.0, value) : exp2(value);\n}\n'),
 ('panner_handler.cc','PannerAngle',
  '  double azimuth = Rad2deg(acos(\n      ClampTo(gfx::DotProduct(projected_source, listener_right), -1.0f, 1.0f)));',
  '  double azimuth = MetaBrowserPortablePannerAngle()\n      ? Rad2deg(fdlibm::acos(ClampTo(\n            gfx::DotProduct(projected_source, listener_right), -1.0f, 1.0f)))\n      : Rad2deg(acos(ClampTo(\n            gfx::DotProduct(projected_source, listener_right), -1.0f, 1.0f)));', '')]:
 name='third_party/blink/renderer/modules/webaudio/'+filename;path=root/name
 assert not path.is_symlink() and path.resolve().is_relative_to(root)
 before[name]=path.read_bytes();text=before[name].decode()
 def edit(old,new):
  global text
  if new in text:assert text.count(new)==1
  else:
   assert text.count(old)==1,('Spatial DSP source drift',name,old[:90]);text=text.replace(old,new)
 header='#include "'+name[:-3]+'.h"'
 edit(header,header+'\n#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"\n#include "third_party/fdlibm/ieee754.h"')
 helper='''namespace {
// METABROWSER_SCOPED_'''+label+'''_BEGIN
bool MetaBrowserPortable'''+label+'''() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool enabled = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return enabled;
}
'''+function+'// METABROWSER_SCOPED_'+label+'_END\n}  // namespace\n'
 if label=='PannerAngle':
  legacy_function='double MetaBrowserPannerAngle(double value) {\n  return MetaBrowserPortablePannerAngle() ? fdlibm::acos(value) : acos(value);\n}\n'
  legacy_helper=helper.replace('// METABROWSER_SCOPED_PannerAngle_END',legacy_function+'// METABROWSER_SCOPED_PannerAngle_END')
  if legacy_helper in text:
   assert text.count(legacy_helper)==1
   text=text.replace(legacy_helper,helper)
   legacy_expression=expression.replace('Rad2deg(acos(', 'Rad2deg(MetaBrowserPannerAngle(')
   assert text.count(legacy_expression)==1
   text=text.replace(legacy_expression,replacement)
 if '// METABROWSER_SCOPED_'+label+'_BEGIN' in text:assert text.count(helper)==1,'Scoped DSP helper drift'
 edit('namespace blink {','namespace blink {\n'+helper)
 edit(expression,replacement)
 assert text.count(helper)==1
 after[name]=text.encode()
for name,raw in before.items():assert (root/name).read_bytes()==raw
if a.apply:
 for name,raw in after.items():
  if raw!=before[name]:(root/name).write_bytes(raw)
print(json.dumps({'scope':'cohort-biquad-detune-and-panner-angle-only','applied':a.apply,'full_scope_complete':False,
 'all_files':{name:hashlib.sha256(raw).hexdigest() for name,raw in after.items()}}))
