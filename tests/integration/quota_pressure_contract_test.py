"""Pressure denial cannot replace normal writes, rollback and recovery evidence."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from quota_pressure_acceptance import verify


class QuotaEvidence(unittest.TestCase):
    def test_actual(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_corruptions_rejected(self):
        def sample(r,index):return r['observations']['samples'][index]
        cases={
            'incomplete':lambda r:r.update(completed=False),
            'unclean quit':lambda r:r.update(clean_shutdown=False),
            'engine mismatch':lambda r:r.update(framework_sha256='0'*64),
            'paid model':lambda r:r.update(paid_model_calls=1),
            'summary without samples':lambda r:r['observations'].update(samples=[]),
            'no reset control':lambda r:r['observations']['samples'].pop(3),
            'override not active':lambda r:sample(r,2)['backend'].update(overrideActive=False),
            'wrong imposed quota':lambda r:sample(r,2)['backend'].update(quota=8*1024**3),
            'not fresh origin':lambda r:sample(r,2)['backend'].update(usage=1234),
            'wrong pressure origin':lambda r:sample(r,2).update(origin='http://127.0.0.1:18878'),
            'wrong pressure payload':lambda r:sample(r,2).update(bytes=4096),
            'missing worker':lambda r:sample(r,2)['realms'].pop('dedicated'),
        }
        for realm in ('window','dedicated'):
            for store in ('opfs','indexedDB','cacheStorage'):
                def result(r,index,realm=realm,store=store):
                    return sample(r,index)['realms'][realm]['stores'][store]
                cases[realm+store+' interior payload corruption']=lambda r,result=result:result(r,2).update(sha256='0'*64)
                cases[realm+store+' normal write denied']=lambda r,result=result:result(r,1)['write'].update(completed=False,error='QuotaExceededError')
                cases[realm+store+' pressure did not enforce']=lambda r,result=result:result(r,2)['write'].update(completed=True)
                cases[realm+store+' wrong error']=lambda r,result=result:result(r,2)['write'].update(error='SecurityError')
                cases[realm+store+' failed write corrupted old data']=lambda r,result=result:result(r,2).update(size=0,first=None)
                cases[realm+store+' reset did not recover']=lambda r,result=result:result(r,3)['write'].update(completed=False,error='QuotaExceededError')
                cases[realm+store+' bucket pressure ignored']=lambda r,result=result:result(r,5)['write'].update(completed=True)
        print('Negative evidence mutations:',len(cases))
        for name,mutate in cases.items():
            with self.subTest(name=name):
                report=copy.deepcopy(REPORT);mutate(report)
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(report,REPORT['framework_sha256'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    args=p.parse_args();REPORT=json.loads(args.report.read_text())
    unittest.main(argv=[__file__])
