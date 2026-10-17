"""Owned headless-reference renderer transport; never used by the shipped app."""
import json
import os
from pathlib import Path
import sys

FLAGS=(
 '--metabrowser-persona-template=linux-x86_64-software-v1',
 '--use-gl=angle','--use-angle=swiftshader','--use-webgpu-adapter=swiftshader',
 '--disable-accelerated-video-decode','--disable-accelerated-video-encode',
)

def renderer_arguments(arguments):
    stop=arguments.index('--') if '--' in arguments else len(arguments)
    switches=arguments[:stop]
    types=[x for x in switches if x=='--type' or x.startswith('--type=')]
    assert types==['--type=renderer'],'Expected exactly one real renderer process type'
    for name in ('--user-agent','--metabrowser-persona-template','--use-gl','--use-angle','--use-webgpu-adapter'):
        matches=[x for x in switches if x==name or x.startswith(name+'=')]
        allowed=[x for x in FLAGS if x==name or x.startswith(name+'=')]
        assert not matches or matches==allowed,('Conflicting renderer argument',name)
    return switches+[x for x in FLAGS if x not in switches]+arguments[stop:]


def main():
    root=Path(os.environ['METABROWSER_LINUX_REFERENCE_ROOT']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='patched-linux-audio-reference'
    binary=Path(sys.argv[1]).resolve(strict=True)
    expected=Path(os.environ['METABROWSER_LINUX_REFERENCE_BINARY']).resolve(strict=True)
    assert binary==expected and binary.name=='headless_shell'
    arguments=renderer_arguments(sys.argv[2:])
    # Preserve a durable, per-process launch observation for subsequent /proc verification.
    path=root/f'renderer-launch-{os.getpid()}.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump({'pid':os.getpid(),'binary':str(binary),'arguments':arguments},stream)
    os.execv(str(binary),[str(binary),*arguments])


if __name__=='__main__':main()
