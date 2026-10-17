"""Original two graph configurations: full payload, four reads, repeat and frequency."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct


def verify_graphs(data):
    rows=data['rows'];assert len(rows)==6
    expected={(variant,repeat) for variant in ('identity-default','checklist-p8') for repeat in range(3)}
    seen={};fingerprints={}
    for row in rows:
        key=(row['variant'],row['repeat']);assert key in expected and key not in seen;seen[key]=row
        frames=44100 if key[0]=='identity-default' else 5000
        assert row['frames']==row['length']==frames and row['rate']==44100 and row['channelCount']==1
        assert abs(row['duration']-frames/44100)<1e-14
        assert row['frequency']==10000 and row['oscillatorType']=='triangle' and row['eventBufferIdentity'] is True
        params={'threshold':-24,'knee':30,'ratio':12,'attack':.003,'release':.25} if key[0]=='identity-default' else {'threshold':-50,'knee':40,'ratio':12,'attack':0,'release':.25}
        assert set(row['parameters'])==set(params)
        assert all(math.isfinite(row['parameters'][p]) and abs(row['parameters'][p]-v)<1e-8 for p,v in params.items())
        raw=base64.b64decode(row['float32Base64'],validate=True);assert len(raw)==frames*4
        values=struct.unpack('<'+'f'*frames,raw);digest=hashlib.sha256(raw).hexdigest()
        assert all(row[name]==digest for name in ('sha256','copySha256','repeatGetSha256','repeatCopySha256'))
        assert row['finite'] is True and all(math.isfinite(x) for x in values)
        assert row['peak']==max(map(abs,values)) and .01<row['peak']<2
        assert row['nonzero']==sum(x!=0 for x in values) and row['nonzero']>frames*.8
        assert row['sample4500to4510']==list(values[4500:4510])
        for end in (4510,5000):
            total=sum(abs(v) for v in values[4500:end]);actual=row['sumAbsolute4500to'+str(end)]
            assert math.isfinite(actual) and actual==total and actual>0
        samples=values[1000:];crossings=[i-1-samples[i-1]/(samples[i]-samples[i-1]) for i in range(1,len(samples)) if samples[i-1]<=0<samples[i]]
        assert len(crossings)>100
        frequency=(len(crossings)-1)*44100/(crossings[-1]-crossings[0]);assert abs(frequency-10000)<10
        fingerprints.setdefault(key[0],row['sumAbsolute4500to5000'])
    assert set(seen)==expected
    for variant in ('identity-default','checklist-p8'):
        baseline=dict(seen[variant,0]);baseline.pop('repeat')
        for repeat in (1,2):
            other=dict(seen[variant,repeat]);other.pop('repeat');assert baseline==other
    return {'graph_renders':6,'full_float_values':147300,'original_graph_variants':2,'read_paths_per_render':4,'fingerprints':fingerprints,'full_scope_complete':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);a=p.parse_args()
    r=json.loads(a.report.read_text());assert r['completed'] and r['clean_shutdown'] and not r.get('error')
    result=verify_graphs(r['observations']);result['report_sha256']=hashlib.sha256(a.report.read_bytes()).hexdigest();print(json.dumps(result))
