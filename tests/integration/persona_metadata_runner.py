"""Owned native persona metadata prototype; no complete emulated-OS claim."""
import argparse
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import identity_surface_runner as identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('app','manifest','ui-helper','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--persona',choices=['native-macos-arm64-v1','linux-x86_64-software-v1'],required=True)
    p.add_argument('--privacy',choices=['balanced','off'],default='balanced')
    p.add_argument('--probe',choices=['metadata','audio-vector','audio-fft','audio-oscillator','audio-compressor','audio-resampler','audio-media','audio-signature','audio-context','audio-device','audio-clock-long','audio-worklet','audio-worklet-realtime','audio-hrtf','audio-hrtf-dynamic','audio-biquad-matrix','audio-biquad-boundary'],default='metadata')
    p.add_argument('--audio-buffer-size',type=int,choices=[128,256,512,1024])
    p.add_argument('--mute-audio',action='store_true')
    fft_override=p.add_mutually_exclusive_group()
    fft_override.add_argument('--native-rust-fft',action='store_true')
    fft_override.add_argument('--disable-rust-fft',action='store_true')
    a=p.parse_args();app=a.app.resolve(strict=True);here=Path(__file__).resolve().parent
    assert not a.native_rust_fft or a.persona=='native-macos-arm64-v1'
    subprocess.run(['python3',str(here.parents[1]/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18860,18861):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-persona-metadata-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('persona-metadata')
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    probe=here/('persona_metadata_probe.mjs' if a.probe=='metadata' else 'audio_vector_probe.mjs')
    probes=[Path(__file__).resolve(),probe,here/'identity_surface_runner.py',here/'identity_surface_probe.mjs',here/'identity_surface_collector.js']
    if a.probe.startswith('audio-'):probes.append(here/(a.probe.replace('-','_')+'_trial.js'))
    report={'root':str(root),'completed':False,'clean_shutdown':False,'persona':a.persona,'privacy':a.privacy,
            'framework_sha256':identity.digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
            'probe_sha256':{str(f):identity.digest(f) for f in probes},'paid_model_calls':0,
            'full_emulated_persona_proven':False,'full_scope_complete':False}
    report['probe_kind']=a.probe
    report['requested_audio_buffer_size']=a.audio_buffer_size
    report['requested_audio_muted']=a.mute_audio
    assert a.probe!='audio-clock-long' or a.mute_audio, 'Long audio probe requires browser mute'
    report['native_rust_fft']=a.native_rust_fft
    report['disable_rust_fft']=a.disable_rust_fft
    a.output.parent.mkdir(parents=True,exist_ok=True)
    identity.HINTS+=', Device-Memory, Sec-CH-Device-Memory'
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18861),identity.Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            command=[str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(root/'browser'),
              '--remote-debugging-port=18860','--use-mock-keychain','--no-first-run','--no-default-browser-check',
              '--disable-component-update','--disable-background-networking','--metabrowser-privacy='+a.privacy,
              '--metabrowser-persona-template='+a.persona,'--use-gl=angle','--use-angle=swiftshader',
              '--use-webgpu-adapter=swiftshader','--disable-accelerated-video-decode','--disable-accelerated-video-encode','about:blank']
            if a.audio_buffer_size:command.insert(-1,'--audio-buffer-size='+str(a.audio_buffer_size))
            if a.mute_audio:command.insert(-1,'--mute-audio')
            if a.native_rust_fft:command.insert(-1,'--enable-blink-features=WebAudioRustFft')
            if a.disable_rust_fft:command.insert(-1,'--disable-blink-features=WebAudioRustFft')
            report['command']=command
            process=subprocess.Popen(command,env=env,stdout=log,stderr=log,start_new_session=True);report['pid']=process.pid
            for _ in range(150):
                assert process.poll() is None,'Owned persona browser exited'
                try:urllib.request.urlopen('http://127.0.0.1:18860/json/version',timeout=.3).close();break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('Owned persona readiness')
            probe_command=['node',str(probe)]
            if a.probe in ('audio-fft','audio-oscillator','audio-compressor','audio-resampler','audio-media','audio-signature','audio-context','audio-device','audio-clock-long','audio-worklet','audio-worklet-realtime','audio-hrtf','audio-hrtf-dynamic','audio-biquad-matrix','audio-biquad-boundary'):probe_command.append(a.probe.replace('-','_')+'_trial.js')
            r=subprocess.run(probe_command,capture_output=True,text=True,timeout=210)
            identity.write_private(root/'probe-process.private.json',{'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
            assert r.returncode==0,r.stderr[-2500:]
            report['observations']=json.loads(r.stdout)
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0
            assert all(identity.digest(Path(f))==h for f,h in report['probe_sha256'].items())
            report.update(completed=True,clean_shutdown=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();identity.write_private(a.output,report)
    print(json.dumps({'completed':True,'persona':a.persona,'full_emulated_persona_proven':False}))


if __name__=='__main__':main()
