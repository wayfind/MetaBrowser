#!/usr/bin/env python3
"""Recompile native adapters against an existing pinned engine, on Linux H200.

Uses GN/Ninja's actual compile/link commands. Does not pretend that the upstream
engine was rebuilt. This avoids invalidating the engine cache when Ninja log
versions differ. The original Chromium libraries must already be built.
"""
import argparse, concurrent.futures, hashlib, json, pathlib, shlex, subprocess
p=argparse.ArgumentParser();p.add_argument('source',type=pathlib.Path);p.add_argument('--out',default='out/metabrowser-mac-arm64');mode=p.add_mutually_exclusive_group();mode.add_argument('--only-avatar',action='store_true');mode.add_argument('--only-side-panel',action='store_true');mode.add_argument('--only-harness',action='store_true');a=p.parse_args()
root=a.source.resolve();out=root/a.out;ninja=root/'third_party/ninja/ninja'
def run(args): return subprocess.check_output([str(ninja),'-C',str(out),*args],cwd=root)
def command(target):
    # -s avoids recursively printing every upstream compiler command.
    return run(['-t','commands','-s',target]).splitlines()[-1].decode()
logs=out/'metabrowser-integration';logs.mkdir(exist_ok=True)
jobs=[(name,f'obj/metabrowser/side_panel_hook/{name}.o') for name in ['browser_tools','side_panel_hook','agent_gateway','conversation_store','conversation_view']]+[
    ('avatar-toolbar','obj/chrome/browser/ui/views/profiles/avatar_toolbar_button_impl/avatar_toolbar_button.o'),
    ('app-menu','obj/chrome/browser/ui/toolbar/impl/app_menu_model.o'),
    ('account-commands','obj/chrome/browser/ui/ui/browser_command_controller.o'),
    ('settings-account','obj/chrome/browser/ui/webui/settings/impl/people_handler.o'),
    ('settings-strings','obj/chrome/browser/ui/webui/settings/impl/settings_localized_strings_provider.o')]
if a.only_avatar or a.only_side_panel or a.only_harness:
    changed='chrome/browser/ui/views/profiles/avatar_toolbar_button.cc' if a.only_avatar else 'metabrowser/side_panel_hook.cc'
    previous=json.loads((logs/'receipt.json').read_text())
    for path,expected in {**previous['sources'],**previous['upstream_account_hooks']}.items():
        if path==changed or (a.only_harness and path in {'metabrowser/browser_tools.cc','metabrowser/browser_tools.h','metabrowser/browser_tool_catalog.inc','metabrowser/agent_gateway.cc','metabrowser/agent_gateway.h','metabrowser/BUILD.gn'}):continue
        if hashlib.sha256((root/path).read_bytes()).hexdigest()!=expected:raise SystemExit('Other native input changed; use full rebuild: '+path)
    jobs=[job for job in jobs if job[0] in ({'browser_tools','agent_gateway','side_panel_hook'} if a.only_harness else {'avatar-toolbar' if a.only_avatar else 'side_panel_hook'})]
def compile_one(job):
    name,target=job
    path=logs/(name+'.log')
    with path.open('wb') as log:result=subprocess.run(command(target),shell=True,cwd=out,stdout=log,stderr=log)
    if result.returncode:return name,path.read_text()[-5000:]
    print('Compiled',name,flush=True)
    return name,None
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(compile_one,jobs))
errors=[name+': '+error for name,error in results if error]
if errors:raise SystemExit('\n'.join(errors))
target='obj/chrome/chrome_framework_shared_library/Chromium Framework'
entries=json.loads(run(['-t','compdb','-x','solink']))
expanded=next(e['command'] for e in entries if e.get('output')==target)
raw=command(target);original=shlex.split(raw);arguments=shlex.split(expanded)
for i,arg in enumerate(original):
    if not arg.startswith('@'):continue
    suffix=len(original)-i-1;contents=arguments[i:len(arguments)-suffix if suffix else None]
    response=contents[0] if len(contents)==1 else ' '.join(shlex.quote(v) for v in contents)
    (out/arg[1:]).write_text(response)
    break
else:raise SystemExit('GN link rule no longer contains the expected response file')
with (logs/'framework-link.log').open('wb') as log:
    subprocess.run(raw,shell=True,cwd=out,stdout=log,stderr=log,check=True)
framework=out/target
dest=out/'Chromium.app/Contents/Frameworks/Chromium Framework.framework/Versions/154.0.8037.97/Chromium Framework'
if not dest.parent.is_dir():raise SystemExit('Pinned app framework layout changed')
import shutil
if framework.stat().st_ino!=dest.stat().st_ino:shutil.copy2(framework,dest)
receipt={'kind':'native-adapter-incremental-cross-build','target':'aarch64-macos.13.0','framework_sha256':hashlib.sha256(framework.read_bytes()).hexdigest(),'sources':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (root/'metabrowser').glob('*') if f.is_file()}}
receipt['upstream_account_hooks']={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [root/'chrome/browser/ui/views/profiles/avatar_toolbar_button.cc',root/'chrome/browser/ui/views/profiles/avatar_toolbar_button.h',root/'chrome/browser/ui/views/profiles/BUILD.gn']}
for path in ['chrome/browser/ui/toolbar/app_menu_model.cc','chrome/browser/ui/browser_command_controller.cc','chrome/browser/ui/webui/settings/people_handler.cc','chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc']:
    receipt['upstream_account_hooks'][path]=hashlib.sha256((root/path).read_bytes()).hexdigest()
(logs/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Linked and staged native browser; receipt:',logs/'receipt.json',flush=True)
