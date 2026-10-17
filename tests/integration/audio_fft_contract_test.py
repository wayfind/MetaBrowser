"""Reject aligned raw/summary FFT failures using independent references."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from audio_fft_acceptance import verify


class FftEvidence(unittest.TestCase):
    def test_capture(self):self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])
    def test_aligned_semantics(self):
        def row(r,i=0):return r['observations']['rows'][i]
        def high_error(r):
            p=row(r)['picks'][0];p['observed']+=1;p['error']=abs(p['observed']-p['expected'])
        def low_error(r):
            p=row(r,20)['picks'][0];p['observed']=0;p['error']=abs(p['observed']-p['expected'])
        def wrong_reference(r):
            p=row(r)['picks'][0];p['observed']+=3;p['expected']+=3
        mutations={
            'missing fft size':lambda r:r['observations']['rows'].pop(0),
            'duplicate size':lambda r:row(r,2).update(size=32),
            'buffer length wrong':lambda r:row(r).update(bufferLength=2048),
            'time domain wrong':lambda r:row(r).update(timeError=.1),
            'nan hidden as zero magnitude':lambda r:row(r).update(nanFrequencyBins=1),
            'positive infinity hidden':lambda r:row(r).update(positiveInfiniteFrequencyBins=1),
            'inconsistent finite count':lambda r:row(r).update(finiteFrequency=False,zeroMagnitudeBins=0),
            'byte conversion wrong':lambda r:row(r).update(maxByteError=2),
            'high signal spectrum wrong':high_error,
            'noise floor spectrum wrong':low_error,
            'reference and observed forged together':wrong_reference,
            'periodic wave amplitude lost':lambda r:row(r,24).update(maxError=.1),
            'forged zero maximum error':lambda r:row(r,24)['samples'].__setitem__(0,0),
            'sparse impulse sample corrupted':lambda r:row(r,22)['samples'].__setitem__(0,0),
            'copy differs':lambda r:row(r,22).update(copySha256='0'*64),
            'repeat changed':lambda r:row(r,1).update(timeHash='0'*64),
            'invalid setter mutated state':lambda r:r['observations']['invalid'][0].update(retained=32),
            'wrong setter error':lambda r:r['observations']['invalid'][0].update(error='TypeError'),
            'boolean model cost':lambda r:r.update(paid_model_calls=False),
            'false full privacy':lambda r:r.update(full_scope_complete=True),
            'disabled experiment not bound':lambda r:r.update(disable_rust_fft=True),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory(prefix='metabrowser-fft-contract-') as temp:
                root=Path(temp).resolve();(root/'.metabrowser-owned-fixture').write_text('persona-metadata')
                r=copy.deepcopy(REPORT);r['root']=str(root)
                r['command']=['--user-data-dir='+str(root/'browser') if x.startswith('--user-data-dir=') else x for x in r['command']]
                def persist():(root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(r['observations']),'stderr':''}))
                persist();self.assertTrue(verify(r,REPORT['framework_sha256'])['passed'])
                mutate(r);persist()
                with self.assertRaises((AssertionError,KeyError,ValueError)):verify(r,REPORT['framework_sha256'])
        print('Rejected aligned FFT variants:',len(mutations))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    a=p.parse_args();REPORT=json.loads(a.report.read_text());unittest.main(argv=[__file__])
