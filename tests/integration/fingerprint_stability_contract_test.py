"""A summary counter cannot stand in for 100 real raw collections."""
import copy
from pathlib import Path
import unittest
from fingerprint_stability_acceptance import verify
from fingerprint_stability_runner import signature


def declared_run():
    return {'completed':True,'requirement_100_met':True,'paid_model_calls':0,'active_pid':None,'framework_sha256':'a'*64,'target_count':100,'iterations':[{'index':i,'pid':1000+i,'root_secret_sha256':'b'*64,'signature':'c'*64} for i in range(1,101)]}


class StabilityContract(unittest.TestCase):
    def rejects(self,data):
        with self.assertRaises((AssertionError,KeyError,ValueError)):
            verify(data,Path('/tmp'),'a'*64)

    def test_counter_without_iterations_rejected(self):
        d=declared_run();d['iterations']=[];self.rejects(d)

    def test_99_is_not_100(self):
        d=declared_run();d['iterations'].pop();d['target_count']=99;self.rejects(d)

    def test_process_reuse_rejected(self):
        d=declared_run();d['iterations'][1]['pid']=d['iterations'][0]['pid'];self.rejects(d)

    def test_identity_rotation_rejected(self):
        d=declared_run();d['iterations'][5]['root_secret_sha256']='d'*64;self.rejects(d)

    def test_drift_despite_claimed_success_rejected(self):
        d=declared_run();d['iterations'][5]['signature']='e'*64;self.rejects(d)

    def test_incomplete_rendering_not_a_stable_signature(self):
        with self.assertRaises((KeyError,ValueError)):
            signature({'realms':{n:{} for n in ['window','iframe','dedicated','shared','service']}})


if __name__=='__main__':unittest.main()
