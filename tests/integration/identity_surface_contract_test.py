"""Reject missing, false-typed or contradictory privacy evidence."""
import copy
import unittest
from identity_surface_runner import validate, validate_passive, validate_version_policy


def protected_trace():
    link={'effectiveType':'4g','rtt':0,'downlink':10,'saveData':False}
    battery={'charging':True,'level':1,'chargingTime':0,'dischargingTime':'Infinity'}
    return {'passiveSignalTrace':[{'phase':name,'observed':{'window':copy.deepcopy(link),'worker':copy.deepcopy(link),'retained':copy.deepcopy(link),'battery':copy.deepcopy(battery),'retainedBattery':copy.deepcopy(battery),'events':0,'batteryEvents':0,'batteryPromiseIdentity':True,'online':name!='offline'}} for name in ['before','slow','fast','offline']]}


class EvidenceContract(unittest.TestCase):
    def test_empty_collection_never_passes(self):
        self.assertFalse(validate({})['consistency_passed'])
        self.assertFalse(validate_passive({},True)['passed'])

    def test_complete_control_states_required(self):
        data=protected_trace();self.assertTrue(validate_passive(data,True)['passed'])
        data['passiveSignalTrace'].pop();self.assertFalse(validate_passive(data,True)['passed'])

    def test_retained_owner_cannot_reopen_network(self):
        data=protected_trace();data['passiveSignalTrace'][2]['observed']['retained']['rtt']=750
        self.assertFalse(validate_passive(data,True)['passed'])

    def test_hidden_change_events_are_not_protection(self):
        data=protected_trace();data['passiveSignalTrace'][3]['observed']['events']=1
        self.assertFalse(validate_passive(data,True)['passed'])

    def test_boolean_numeric_substitution_rejected(self):
        for key,field in [('window','rtt'),('worker','downlink'),('battery','level'),('retainedBattery','chargingTime')]:
            data=protected_trace();data['passiveSignalTrace'][0]['observed'][key][field]=field=='level'
            self.assertFalse(validate_passive(data,True)['passed'],(key,field))

    def test_masking_all_modes_is_not_a_valid_control(self):
        self.assertFalse(validate_passive(protected_trace(),False)['passed'])

    def test_metadata_policy_requires_all_realms_and_actual_header(self):
        data={'realms':{n:{'uaData':{'high':{'platformVersion':'26.0.0'}}} for n in ['window','iframe','dedicated','shared','service']},'headers':{'headers':[['Sec-CH-UA-Platform-Version','"26.0.0"']]}}
        self.assertTrue(validate_version_policy(data,'26.6.2','major')['passed'])
        bad=copy.deepcopy(data);bad['realms']['shared']['uaData']['high']['platformVersion']='26.6.2'
        self.assertFalse(validate_version_policy(bad,'26.6.2','major')['passed'])
        bad=copy.deepcopy(data);bad['headers']['headers'][0][1]='"26.6.2"'
        self.assertFalse(validate_version_policy(bad,'26.6.2','major')['passed'])
        self.assertFalse(validate_version_policy({},'26.6.2','major')['passed'])
        self.assertFalse(validate_version_policy(data,'26.6.2','system')['passed'])

    def test_offline_boolean_must_remain_truthful(self):
        data=protected_trace();data['passiveSignalTrace'][3]['observed']['online']=True
        self.assertFalse(validate_passive(data,True)['passed'])


if __name__=='__main__':unittest.main()
