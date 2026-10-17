#!/usr/bin/env python3
"""Rebuild the actual pinned Settings WebUI/pak on H200, without engine rebuild.

All commands come from GN/Ninja. No generated JS or binary resource patching.
"""
import argparse,hashlib,json,pathlib,shutil,subprocess
p=argparse.ArgumentParser();p.add_argument('source',type=pathlib.Path);a=p.parse_args()
root=a.source.resolve();out=root/'out/metabrowser-mac-arm64';ninja=root/'third_party/ninja/ninja'
logs=out/'metabrowser-integration';logs.mkdir(exist_ok=True)
targets=[
    'gen/chrome/browser/resources/settings/preprocessed/privacy_page/personalization_options.html',
    'gen/chrome/browser/resources/settings/preprocessed/people_page/people_page.html.ts',
    'gen/chrome/browser/resources/settings/preprocessed/privacy_page/personalization_options.html.ts',
    'gen/chrome/browser/resources/settings/tsc/people_page/people_page.html.js',
    'gen/chrome/browser/resources/settings/bundled/settings.rollup.js',
    'gen/chrome/browser/resources/settings/minified/settings.rollup.js',
    'gen/chrome/settings_resources.pak',
    'gen/repack/resources.pak',
]
commands=[]
for target in targets:
    r=subprocess.run([str(ninja),'-C',str(out),'-t','commands','-s',target],capture_output=True,text=True)
    if r.returncode or not r.stdout.strip():raise SystemExit('Missing pinned Settings build rule: '+target+' '+r.stderr[:300])
    command=r.stdout.splitlines()[-1]
    if command not in commands:commands.append(command)
for index,command in enumerate(commands):
    path=logs/f'settings-{index}.log'
    with path.open('wb') as log:result=subprocess.run(command,shell=True,cwd=out,stdout=log,stderr=log)
    if result.returncode:raise SystemExit(path.read_text()[-5000:])
    print('Settings build step',index+1,'/',len(commands),'passed',flush=True)
dest=out/'Chromium.app/Contents/Frameworks/Chromium Framework.framework/Versions/154.0.8037.97/Resources/resources.pak'
if not dest.parent.is_dir():raise SystemExit('Pinned framework resources layout changed')
if not dest.samefile(out/'gen/repack/resources.pak'):
    shutil.copy2(out/'gen/repack/resources.pak',dest)
sources=['chrome/browser/resources/settings/people_page/people_page.html.ts','chrome/browser/resources/settings/people_page/people_page_index.html.ts','chrome/browser/resources/settings/privacy_page/personalization_options.html']
receipt={'kind':'native-metask-settings-source-build','resource_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'steps':len(commands),'sources':{s:hashlib.sha256((root/s).read_bytes()).hexdigest() for s in sources}}
(logs/'settings-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Built and staged Metask account Settings resources',flush=True)
