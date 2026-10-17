#!/usr/bin/env python3
"""Bind unmodified HRTF data and supporting source inputs across the two roots."""
from pathlib import Path
import hashlib,json,os,sys
mac=Path(sys.argv[1]).resolve(strict=True);root=Path(sys.argv[2]).resolve(strict=True)
p=root/'.metabrowser-owned-linux-reference-snapshot.json';marker=json.loads(p.read_text())
assert marker['schema_version']==2 and marker['state']=='source-snapshot-complete' and marker['destination']==str(root)
folder=Path('third_party/blink/renderer/platform/audio');names=set()
for glob in ('hrtf*.cc','hrtf*.h','fft_convolver*','audio_bus.cc','audio_bus.h','resources/*'):
 names.update(str(f.relative_to(mac)) for f in (mac/folder).glob(glob) if f.is_file())
assert len(names)>200
hashes={}
for name in sorted(names):
 source=mac/name;destination=root/name
 assert source.is_file() and destination.is_file()
 want=hashlib.sha256(source.read_bytes()).hexdigest();assert hashlib.sha256(destination.read_bytes()).hexdigest()==want,name
 hashes[name]=want
marker['domain_source_sha256']=hashes
new=p.with_name(p.name+'.audio-new');new.write_text(json.dumps(marker,indent=2)+'\n');os.replace(new,p)
print(json.dumps({'domain_sources_bound':len(hashes),'wave_files':sum(name.endswith('.wav') for name in hashes),'all_source_bytes_equal':True}))
