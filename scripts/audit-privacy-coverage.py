#!/usr/bin/env python3
"""Completion gate for the declared fingerprint scope; incomplete returns 1."""
import argparse
import hashlib
import json
from pathlib import Path
import re

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--ledger',type=Path,default=Path('docs/privacy-requirements.json'))
a=p.parse_args();d=json.loads(a.ledger.read_text());errors=[]
source=Path(d['source']['path'])
if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=d['source']['sha256']:
    errors.append('Original checklist missing or changed; re-audit scope')
else:
    original={'SRC-'+m.group(1) for m in re.finditer(r'^###? ((?:\d+\.)*\d+)\.?\s+(.+)$',source.read_text(),re.M) if m.group(1) in ('0','0.5') or int(m.group(1).split('.')[0])<=13}
    recorded={r['id'] for r in d['requirements']}
    if original-recorded:errors.append('Source sections absent: '+','.join(sorted(original-recorded)))
requirements=d['requirements'];ids=[r['id'] for r in requirements]
if len(ids)!=len(set(ids)):errors.append('Duplicate requirement IDs')
if set(d['required_probe_ids'])!={'P'+str(i) for i in range(1,15)}:errors.append('P1-P14 scope incomplete')
for r in requirements:
    if r.get('status') not in ('unverified','partial','verified','blocked'):errors.append('Unknown status: '+r['id'])
    for ref in r.get('evidence',[]):
        path=Path(ref if isinstance(ref,str) else ref['path'])
        if not path.is_file():errors.append('Missing evidence: '+str(path))
    if r.get('status')=='verified':
        refs=r.get('evidence',[])
        if not refs or any(not isinstance(ref,dict) for ref in refs):
            errors.append('Verified requirement needs content-addressed assertions: '+r['id']);continue
        for ref in refs:
            path=Path(ref['path'])
            if not path.is_file():continue
            if ref.get('sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():errors.append('Evidence hash mismatch: '+r['id']);continue
            try:
                body=json.loads(path.read_text());value=body
                for key in ref['pointer'].strip('/').split('/'):
                    value=value[int(key)] if isinstance(value,list) else value[key.replace('~1','/').replace('~0','~')]
                if value is not True:errors.append('Assertion is not true: '+r['id'])
                if not ref.get('framework_sha256') or body.get('framework_sha256')!=ref['framework_sha256']:errors.append('Unbound engine evidence: '+r['id'])
            except (KeyError,ValueError,TypeError,IndexError):errors.append('Invalid evidence assertion: '+r['id'])
incomplete=[r['id'] for r in requirements if r.get('status')!='verified']
probes=[name for name in d['required_probe_ids'] if d['probe_status'].get(name)!='verified']
passed=bool(requirements) and not errors and not incomplete and not probes
print(json.dumps({'scope_ledger_valid':not errors,'completion_proven':passed,'requirement_count':len(requirements),'incomplete_requirements':incomplete,'incomplete_probes':probes,'errors':errors,'note':'A green ledger still requires scope/claim review; partial observations cannot complete a whole surface.'},ensure_ascii=False,indent=2))
raise SystemExit(0 if passed else 1)
