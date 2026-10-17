#!/usr/bin/env python3
"""Read the actual packed HRTF FLAC with Chromium's own GRIT pack parser."""
import argparse,hashlib,json,re,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--app',type=Path);p.add_argument('--payload-output',type=Path);a=p.parse_args()
root=a.source.resolve(strict=True);out=a.out.resolve(strict=True)
sys.dont_write_bytecode=True;sys.path.insert(0,str(root/'tools/grit'))
from grit.format import data_pack
resource=root/'third_party/blink/renderer/platform/audio/resources/Composite.flac'
header=out/'gen/third_party/blink/public/resources/grit/blink_resources.h'
match=re.search(r'^#define IDR_AUDIO_SPATIALIZATION_COMPOSITE (\d+)\s*$',header.read_text(),re.M);assert match
identifier=int(match.group(1));raw=resource.read_bytes();assert raw.startswith(b'fLaC')
search=a.app.resolve(strict=True) if a.app else out
found=[]
packs=search.rglob('*.pak') if a.app else search.glob('*.pak')
for pack in packs:
 if pack.is_symlink():continue
 values=data_pack.ReadDataPack(str(pack)).resources
 if identifier not in values:continue
 payload=values[identifier]
 if payload!=raw:continue
 found.append({'pack':str(pack),'pack_sha256':hashlib.sha256(pack.read_bytes()).hexdigest(),'resource_id':identifier,'payload_sha256':hashlib.sha256(payload).hexdigest(),'payload_bytes':len(payload)})
assert found,'Actual HRTF FLAC payload not found in packaged resources'
if a.payload_output:
 a.payload_output.parent.mkdir(parents=True,exist_ok=True)
 packed_payload=data_pack.ReadDataPack(found[0]['pack']).resources[identifier]
 assert packed_payload==raw
 a.payload_output.write_bytes(packed_payload)
print(json.dumps({'source_flac':str(resource),'source_sha256':hashlib.sha256(raw).hexdigest(),'source_bytes':len(raw),'packed_matches':found,'full_scope_complete':False},indent=2))
