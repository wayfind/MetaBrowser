"""Raw and summary agreement alone cannot establish DSP functionality."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from audio_vector_acceptance import verify


class AudioEvidence(unittest.TestCase):
    def test_capture(self): self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])
    def test_aligned_semantics(self):
        def row(r,i=0): return r['observations']['rows'][i]
        def ch(r,i=0): return row(r,i)['channels'][0]
        mutations = {
            'wrong rate':lambda r:row(r).update(bufferRate=48000),
            'wrong graph':lambda r:row(r).update(kind='compressor'),
            'missing graph':lambda r:r['observations']['rows'].pop(),
            'wrong duration':lambda r:row(r).update(duration=1),
            'wrong channels':lambda r:row(r).update(channelCount=1),
            'boolean channels':lambda r:row(r).update(channelCount=True),
            'event buffer not promise buffer':lambda r:row(r).update(eventBufferIdentity=False),
            'nonfinite samples':lambda r:ch(r).update(finite=False),
            'silence only':lambda r:ch(r).update(nonzero=0),
            'copy differs':lambda r:ch(r).update(copySha256='0'*64),
            'bad gain computation':lambda r:ch(r).update(maxError=.01),
            'bad convolution computation':lambda r:ch(r,4).update(maxError=.01),
            'repeat changed':lambda r:ch(r,1).update(sha256='0'*64,copySha256='0'*64),
            'boolean model cost':lambda r:r.update(paid_model_calls=False),
            'claimed full privacy':lambda r:r.update(full_scope_complete=True),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory(prefix='metabrowser-audio-contract-') as temp:
                root=Path(temp).resolve();(root/'.metabrowser-owned-fixture').write_text('persona-metadata')
                r=copy.deepcopy(REPORT);r['root']=str(root)
                r['command']=['--user-data-dir='+str(root/'browser') if s.startswith('--user-data-dir=') else s for s in r['command']]
                def persist(): (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(r['observations']),'stderr':''}))
                persist();self.assertTrue(verify(r,REPORT['framework_sha256'])['passed'])
                mutate(r);persist()
                with self.assertRaises((AssertionError,KeyError,ValueError)):verify(r,REPORT['framework_sha256'])
        print('Rejected aligned DSP variants:',len(mutations))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    a=p.parse_args();REPORT=json.loads(a.report.read_text());unittest.main(argv=[__file__])
