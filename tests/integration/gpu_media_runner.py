"""Isolated native Mac GPU/media smoke matrix; no SDK or user account."""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

REQUIRED_CHECKS = frozenset('''webgl webgpu worker_gpu
canvas_videoframe_roundtrip imagebitmap_transfer protected_canvas_handoffs
taint_preserved worker_media_transfer raw_rgba_frame_preserved
canvas_rgb_bounds_and_crops media_performance_1080p video_encoder_decoder
canvas_capture_recorder_playback webrtc_local_canvas_roundtrip audio_data_clone
opus_audio_encoder_decoder avc_mse_decode_playback aac_actual_decode'''.split())
EXTENDED_CHECKS = frozenset('''canvas_budget_fail_closed canvas_png_exports
canvas_alpha_preserved canvas_float16_exports
fake_camera_capture fake_av_recording camera_clone_lifecycle
media_permissions_policy offline_audio_worklet realtime_audio_worklet
owned_tab_capture webgpu_canvas_exports worker_canvas_exports clearkey_actual_decryption
gpu_optional_privacy gpu_limit_negotiation gpu_codec_capabilities
media_device_aliases media_labels_retained drm_identifier_policy'''.split())
CONTROL_CHECKS = frozenset(('gpu_features_on_off', 'media_label_on_off', 'retained_gpu_policy'))


def validate_probe(result, extended=False, control=False):
    """Reject incomplete evidence even if a probe claims success."""
    if not isinstance(result, dict):
        raise ValueError('Probe result is not an object')
    required = CONTROL_CHECKS if control else REQUIRED_CHECKS | EXTENDED_CHECKS if extended else REQUIRED_CHECKS
    checks, details = result.get('checks'), result.get('details')
    if not isinstance(checks, dict) or set(checks) != required:
        raise ValueError('Probe checks are missing or unexpected')
    if not isinstance(details, dict) or set(details) != required:
        raise ValueError('Probe details are missing or unexpected')
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError('Probe checks must be booleans')
    if type(result.get('passed')) is not bool or result['passed'] != all(checks.values()):
        raise ValueError('Probe pass status contradicts its checks')
    if type(result.get('paid_model_calls')) is not int or result['paid_model_calls'] != 0:
        raise ValueError('GPU/media fixture must not call a model')
    return result


def write_report(path, result):
    """Create private evidence atomically, including on a failed run."""
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--diagnostic-modes', action='store_true')
    parser.add_argument('--extended-media', action='store_true',
                        help='use synthetic camera/microphone and capture only the owned fixture tab')
    parser.add_argument('--mode', action='append', choices=('native', 'swiftshader'),
                        help='run only selected primary modes (default: both)')
    parser.add_argument('--policy-controls', action='store_true',
                        help='add on/off/developer/site-exception/global-pref controls for each backend')
    args = parser.parse_args()
    if args.policy_controls and not args.extended_media:
        parser.error('--policy-controls requires --extended-media (synthetic devices only)')
    base = Path(__file__).resolve().parents[2]
    app = (args.app or base / 'out/mac-privacy-standalone/MetaBrowser.app').resolve(strict=True)
    assert not (app / 'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    assert not (app / 'Contents/Resources/agentcore').exists()
    for port in (18850, 18858, 18859):
        with socket.socket() as sock:
            # Match HTTPServer's policy: a previous fixture's TIME_WAIT sockets
            # must not be mistaken for a live listener during repeated reviews.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-gpu-media-'))
    (root / 'index.html').write_text('<!doctype html><title>Owned GPU and media fixture</title>')
    (root / 'taint.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="red"/></svg>')
    for name in ('media-avc-fragmented.mp4', 'media-aac.m4a', 'media-avc-clearkey.mp4'):
        shutil.copyfile(base / 'tests/fixtures' / name, root / name)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/progress' or not 0 < length <= 16384:
                self.send_error(400)
                return
            self.server.progress = json.loads(self.rfile.read(length))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_):
            pass

        def end_headers(self):
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
            self.send_header('Cross-Origin-Resource-Policy', 'cross-origin')
            super().end_headers()

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 18858), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cross_origin = http.server.ThreadingHTTPServer(('127.0.0.1', 18859), functools.partial(Handler, directory=str(root)))
    threading.Thread(target=cross_origin.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_CTYPE', 'TMPDIR', 'SHELL', '__CF_USER_TEXT_ENCODING')}
    modes = {
        'native': [],
        'swiftshader': ['--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader', '--disable-accelerated-video-decode', '--disable-accelerated-video-encode'],
    }
    if args.mode:
        modes = {name: flags for name, flags in modes.items() if name in args.mode}
    if args.policy_controls:
        for backend, flags in list(modes.items()):
            for variant in ('balanced', 'off', 'developer', 'exception', 'disabled'):
                extra = ['--metabrowser-privacy=off'] if variant == 'off' else []
                if variant == 'developer':
                    extra = ['--enable-blink-features=WebGPUDeveloperFeatures']
                modes['control_' + backend + '_' + variant] = [*flags, *extra]
    if args.diagnostic_modes:
        modes.update({
        'swiftshader_webgpu_optin': ['--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader', '--enable-unsafe-webgpu'],
        'swiftshader_blocklist_diagnostic': ['--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader', '--disable-dawn-features=adapter_blocklist'],
        })
    framework = app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    framework_hash = hashlib.sha256()
    with framework.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            framework_hash.update(chunk)
    results = {'root': str(root), 'app': str(app), 'framework_sha256': framework_hash.hexdigest(), 'rtc_policy': 'system-for-local-only-transport-test', 'extended_media': args.extended_media, 'completed': False, 'modes': {}}
    probe_files = ['tests/integration/gpu_media_probe.mjs',
                   'tests/integration/gpu_policy_probe.mjs',
                   'tests/integration/device_label_probe.mjs',
                   'tests/integration/hardware_policy_control.mjs',
                   'tests/integration/media_lifecycle_probe.mjs',
                   'tests/integration/gpu_media_runner.py',
                   'tests/fixtures/media-avc-fragmented.mp4',
                   'tests/fixtures/media-aac.m4a',
                   'tests/fixtures/media-avc-clearkey.mp4']
    results['probe_sha256'] = {name: hashlib.sha256((base / name).read_bytes()).hexdigest()
                               for name in probe_files}
    media_flags = (['--use-fake-device-for-media-stream',
                    '--auto-accept-camera-and-microphone-capture',
                    '--auto-select-tab-capture-source-by-title=Owned GPU and media fixture']
                   if args.extended_media else [])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for name, flags in modes.items():
            server.progress = {'mode': name, 'phase': 'starting'}
            owned = root / name
            owned.mkdir()
            control = name.startswith('control_')
            if control and name.endswith(('_exception', '_disabled')):
                privacy = ({'compatibility_sites': ['http://127.0.0.1']}
                           if name.endswith('_exception') else {'enabled': False})
                preferences = owned / 'browser/Default/Preferences'
                preferences.parent.mkdir(parents=True)
                preferences.write_text(json.dumps({'metabrowser': {'privacy': privacy}}))
                preferences.chmod(0o600)
            runenv = dict(env, METABROWSER_IDENTITY_HOME=str(owned / 'identities'), METABROWSER_ACCOUNT_HOME=str(owned / 'account'), METABROWSER_CONVERSATION_HOME=str(owned / 'conversations'), METABROWSER_WORKSPACE=str(owned / 'workspace'))
            with (owned / 'browser.log').open('w') as log:
                process = subprocess.Popen([str(app / 'Contents/MacOS/Chromium'), '--user-data-dir=' + str(owned / 'browser'), '--remote-debugging-port=18850', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check', '--disable-component-update', '--hide-crash-restore-bubble', '--metabrowser-webrtc-policy=system', *media_flags, *flags, 'about:blank'], env=runenv, stdout=log, stderr=log, start_new_session=True)
                try:
                    ready = False
                    for _ in range(150):
                        assert process.poll() is None, 'Browser exited'
                        try:
                            urllib.request.urlopen('http://127.0.0.1:18850/json/version', timeout=.2).close()
                            ready = True
                            break
                        except OSError:
                            time.sleep(.1)
                    if not ready:
                        raise TimeoutError('Owned browser CDP did not become ready')
                    kind = 'control' if control else 'extended' if args.extended_media else 'base'
                    result = subprocess.run(['node', str(base / 'tests/integration/gpu_media_probe.mjs'), '18850', kind, name], capture_output=True, text=True, timeout=180 if args.extended_media else 100)
                    assert result.returncode == 0, result.stderr[-2000:]
                    results['modes'][name] = validate_probe(json.loads(result.stdout), args.extended_media, control)
                    if name == 'swiftshader':
                        gpu = results['modes'][name]['details']['webgpu']
                        worker = results['modes'][name]['details']['worker_gpu']
                        backend_ok = gpu.get('vendor') == 'google' and gpu.get('isFallbackAdapter') is True and worker.get('fallback') is True
                        safe = not any(f.startswith('chromium-experimental-') for f in gpu.get('features', []))
                        results['modes'][name]['checks']['real_software_backend'] = backend_ok
                        results['modes'][name]['checks']['no_experimental_features'] = safe
                        results['modes'][name]['passed'] = all(results['modes'][name]['checks'].values())
                    elif name == 'native':
                        gpu = results['modes'][name]['details']['webgpu']
                        results['modes'][name]['checks']['native_hardware_adapter'] = gpu.get('isFallbackAdapter') is False
                        results['modes'][name]['passed'] = all(results['modes'][name]['checks'].values())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            # Only this fixture's Popen child; never the user's app.
                            process.kill()
                            process.wait(timeout=10)
                            raise
            time.sleep(.3)
        if any(hashlib.sha256((base / name).read_bytes()).hexdigest() != digest
               for name, digest in results['probe_sha256'].items()):
            raise RuntimeError('Probe source changed during acceptance run')
        results['completed'] = True
        results['passed'] = all(v['passed'] for v in results['modes'].values())
    except Exception as error:
        results['passed'] = False
        results['last_progress'] = getattr(server, 'progress', None)
        results['error'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        server.shutdown()
        server.server_close()
        cross_origin.shutdown()
        cross_origin.server_close()
        write_report(args.output, results)
    print(json.dumps(results, indent=2))
    if not results.get('passed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
