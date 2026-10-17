#!/usr/bin/env python3
"""Build native privacy changes with GN/Ninja dependency propagation on H200.

Unlike the UI-only adapter build, Mojo and public header changes require the
real dependency graph. This script never manually links stale engine archives.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=pathlib.Path)
parser.add_argument('--out', default='out/metabrowser-mac-arm64')
parser.add_argument('--jobs', type=int, default=96)
parser.add_argument('--plan-only', action='store_true')
args = parser.parse_args()
if not 1 <= args.jobs <= 128:
    parser.error('jobs must be between 1 and 128')
root = args.source.resolve()
project = pathlib.Path(__file__).resolve().parents[1]
out = root / args.out
logs = out / 'metabrowser-privacy'
logs.mkdir(exist_ok=True)
started = time.monotonic()
native_stage = project / 'scripts/stage-chromium-hooks.py'
script_paths = [pathlib.Path(__file__).resolve(), native_stage]
script_paths.extend(project / f'scripts/stage-privacy-{surface}.py'
                    for surface in ('context', 'canvas', 'audio', 'webgl', 'workers', 'diagnostics', 'mac', 'webgl-readback', 'display', 'fonts', 'speech', 'gpu', 'media', 'device-labels', 'passive-signals', 'identity', 'storage', 'fft', 'oscillator', 'compressor', 'resampler', 'audio-device', 'audio-clock', 'spatial-dsp', 'hrtf', 'biquad'))
script_paths.append(project / 'chromium/privacy/metabrowser_webgl_readback.inc')
script_paths.append(project / 'chromium/privacy/metabrowser_cpu_identity.h')
script_paths.append(project / 'chromium/privacy/metabrowser_storage_quota.h')
script_paths.append(project / 'chromium/privacy/metabrowser_audio_clock_sink.inc')
script_paths.append(project / 'chromium/privacy/metabrowser_fft_complex_math.inc')
script_paths.append(project / 'chromium/privacy/metabrowser_biquad_process.inc')
script_paths.extend(project / 'chromium/identity' / filename for filename in
    ('BUILD.gn', 'platform_version_policy.h', 'persona.h', 'persona_runtime.h', 'fft_math.h', 'fft_math.rs'))
script_paths.append(project / 'scripts/stage-privacy-network.py')
script_paths.append(project / 'chromium/metabrowser/background_service_policy.h')
script_paths.append(project / 'chromium/metabrowser/BUILD.gn')
scripts = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in script_paths}


def run(command, name):
    with (logs / name).open('wb') as stream:
        subprocess.run(command, cwd=root, stdout=stream, stderr=stream, check=True)


run([sys.executable, str(project / 'scripts/stage-chromium-hooks.py'), str(root)], 'native-stage.log')
gpu = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-gpu.py'), str(root), '--apply'], cwd=root))
(logs / 'gpu-stage.json').write_text(json.dumps(gpu, indent=2) + '\n')
context = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-context.py'), str(root), '--apply'], cwd=root))
(logs / 'context-stage.json').write_text(json.dumps(context, indent=2) + '\n')
network = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-network.py'), str(root), '--apply'], cwd=root))
(logs / 'network-stage.json').write_text(json.dumps(network, indent=2) + '\n')
workers = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-workers.py'), str(root), '--apply'], cwd=root))
(logs / 'workers-stage.json').write_text(json.dumps(workers, indent=2) + '\n')
diagnostics = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-diagnostics.py'), str(root), '--apply'], cwd=root))
(logs / 'diagnostics-stage.json').write_text(json.dumps(diagnostics, indent=2) + '\n')
for surface in ('canvas', 'audio', 'webgl'):
    run([sys.executable, str(project / f'scripts/stage-privacy-{surface}.py'), str(root)], f'{surface}-stage.log')
media = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-media.py'), str(root), '--apply'], cwd=root))
(logs / 'media-stage.json').write_text(json.dumps(media, indent=2) + '\n')
mac = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-mac.py'), str(root), '--apply'], cwd=root))
(logs / 'mac-stage.json').write_text(json.dumps(mac, indent=2) + '\n')
device_labels = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-device-labels.py'), str(root), '--apply'], cwd=root))
(logs / 'device-labels-stage.json').write_text(json.dumps(device_labels, indent=2) + '\n')
passive = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-passive-signals.py'), str(root), '--apply'], cwd=root))
(logs / 'passive-signals-stage.json').write_text(json.dumps(passive, indent=2) + '\n')
identity = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-identity.py'), str(root), '--apply'], cwd=root))
(logs / 'identity-stage.json').write_text(json.dumps(identity, indent=2) + '\n')
fft = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-fft.py'), str(root), '--apply'], cwd=root))
(logs / 'fft-stage.json').write_text(json.dumps(fft, indent=2) + '\n')
oscillator = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-oscillator.py'), str(root), '--apply'], cwd=root))
(logs / 'oscillator-stage.json').write_text(json.dumps(oscillator, indent=2) + '\n')
compressor = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-compressor.py'), str(root), '--apply'], cwd=root))
(logs / 'compressor-stage.json').write_text(json.dumps(compressor, indent=2) + '\n')
resampler = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-resampler.py'), str(root), '--apply'], cwd=root))
(logs / 'resampler-stage.json').write_text(json.dumps(resampler, indent=2) + '\n')
audio_device = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-audio-device.py'), str(root), '--apply'], cwd=root))
(logs / 'audio-device-stage.json').write_text(json.dumps(audio_device, indent=2) + '\n')
audio_clock = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-audio-clock.py'), str(root), '--apply'], cwd=root))
(logs / 'audio-clock-stage.json').write_text(json.dumps(audio_clock, indent=2) + '\n')
spatial_dsp = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-spatial-dsp.py'), str(root), '--apply'], cwd=root))
(logs / 'spatial-dsp-stage.json').write_text(json.dumps(spatial_dsp, indent=2) + '\n')
hrtf = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-hrtf.py'), str(root), '--apply'], cwd=root))
(logs / 'hrtf-stage.json').write_text(json.dumps(hrtf, indent=2) + '\n')
biquad = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-biquad.py'), str(root), '--apply'], cwd=root))
(logs / 'biquad-stage.json').write_text(json.dumps(biquad, indent=2) + '\n')
readback = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-webgl-readback.py'), str(root), '--apply'], cwd=root))
(logs / 'webgl-readback-stage.json').write_text(json.dumps(readback, indent=2) + '\n')
display = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-display.py'), str(root), '--apply'], cwd=root))
(logs / 'display-stage.json').write_text(json.dumps(display, indent=2) + '\n')
fonts = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-fonts.py'), str(root), '--apply'], cwd=root))
(logs / 'fonts-stage.json').write_text(json.dumps(fonts, indent=2) + '\n')
speech = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-speech.py'), str(root), '--apply'], cwd=root))
(logs / 'speech-stage.json').write_text(json.dumps(speech, indent=2) + '\n')
storage = json.loads(subprocess.check_output([
    sys.executable, str(project / 'scripts/stage-privacy-storage.py'), str(root), '--apply'], cwd=root))
(logs / 'storage-stage.json').write_text(json.dumps(storage, indent=2) + '\n')

paths = set(context['all_files'])
paths.update(network['all_files'])
paths.update(workers['all_files'])
paths.update(media['all_files'])
paths.update(workers['prerequisite_sha256'])
paths.update(diagnostics['all_files'])
paths.update(diagnostics['prerequisite_sha256'])
paths.update(mac['all_files'])
paths.update(device_labels['all_files'])
paths.update(passive['all_files'])
paths.update(identity['all_files'])
paths.update(fft['all_files'])
paths.update(oscillator['all_files'])
paths.update(compressor['all_files'])
paths.update(resampler['all_files'])
paths.update(audio_device['all_files'])
paths.update(audio_clock['all_files'])
paths.update(spatial_dsp['all_files'])
paths.update(hrtf['all_files'])
paths.update(biquad['all_files'])
paths.update(readback['all_files'])
paths.update(display['all_files'])
paths.update(fonts['all_files'])
paths.update(speech['all_files'])
paths.update(storage['all_files'])
# The native staging script also edits upstream account/UI/BUILD files. Include
# its literal file inputs (including loop literals), not only metabrowser/*.
for node in ast.walk(ast.parse(native_stage.read_text())):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        if (value == 'BUILD.gn' or value.startswith(('chrome/', 'tools/'))) and '\n' not in value:
            if (root / value).is_file():
                paths.add(value)
paths.add(str((out / 'args.gn').relative_to(root)))
paths.update(str(p.relative_to(root)) for p in (root / 'metabrowser').glob('*') if p.is_file())
paths.update([
    'gpu/command_buffer/service/webgpu_decoder_impl.cc',
    'third_party/blink/renderer/modules/webgpu/external_image_utils.cc',
    'third_party/blink/renderer/core/canvas_interventions/build.gni',
    'third_party/blink/renderer/core/canvas_interventions/metabrowser_canvas_noise.h',
    'third_party/blink/renderer/core/canvas_interventions/metabrowser_noise_mix.h',
    'third_party/blink/renderer/core/html/canvas/html_canvas_element.cc',
    'third_party/blink/renderer/core/offscreencanvas/offscreen_canvas.cc',
    'third_party/blink/renderer/modules/canvas/canvas2d/base_rendering_context_2d.cc',
    'third_party/blink/renderer/modules/webaudio/offline_audio_context.cc',
    'third_party/blink/renderer/modules/webaudio/offline_audio_context_test.cc',
    'third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc',
])


def hashes():
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in sorted(paths)}


sources = hashes()
if any(hashlib.sha256((project / path).read_bytes()).hexdigest() != digest
       for path, digest in scripts.items()):
    raise SystemExit('Privacy staging script changed while staging; build refused')
gn = root / 'buildtools/linux64/gn'
ninja = root / 'third_party/ninja/ninja'
run([str(gn), 'gen', args.out, '--fail-on-unused-args'], 'gn-gen.log')
run([str(gn), 'check', args.out, '//metabrowser:*'], 'gn-check.log')
target = 'obj/chrome/chrome_framework_shared_library/Chromium Framework'
if args.plan_only:
    run([str(ninja), '-C', str(out), '-n', target], 'ninja-plan.log')
    print('Staged and validated privacy build plan:', logs, flush=True)
    sys.exit(0)
run([str(ninja), '-C', str(out), '-j', str(args.jobs), target], 'ninja-build.log')
if hashes() != sources:
    raise SystemExit('Privacy source changed during build; receipt refused')
if any(hashlib.sha256((project / path).read_bytes()).hexdigest() != digest
       for path, digest in scripts.items()):
    raise SystemExit('Privacy staging script changed during build; receipt refused')
framework = out / target
destination = out / 'Chromium.app/Contents/Frameworks/Chromium Framework.framework/Versions/154.0.8037.97/Chromium Framework'
temporary = destination.with_name(destination.name + '.privacy-new')
shutil.copy2(framework, temporary)
framework_sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
temporary.replace(destination)
receipt = {
    'kind': 'native-privacy-engine-dependency-cross-build',
    'target': 'aarch64-macos.13.0',
    'framework_sha256': framework_sha256,
    'sources': sources,
    'staging_scripts': scripts,
    'worker_scope': workers['scope'],
    'args_sha256': sources[str((out / 'args.gn').relative_to(root))],
    'seconds': round(time.monotonic() - started, 3),
}
(logs / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Privacy engine linked and staged:', logs / 'receipt.json', flush=True)
