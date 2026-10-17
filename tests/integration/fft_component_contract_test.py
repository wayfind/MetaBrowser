"""Equal files must still contain the requested numeric test corpus."""
import argparse
from pathlib import Path
import struct
import unittest
from fft_component_acceptance import parse


class NumericArtifact(unittest.TestCase):
    def test_actual(self):self.assertEqual(parse(RAW)['cases'],110)
    def test_invalid_equal_payloads(self):
        def word(offset,value):
            b=bytearray(RAW);struct.pack_into('<I',b,offset,value);return b
        def sample(offset,value):
            b=bytearray(RAW);struct.pack_into('<f',b,offset,value);return b
        bad={'empty':b'','magic':b'BADFFT00'+RAW[8:], 'case count':word(8,0),
             'wrong transform size':word(12,3),'wrong packed count':word(20,2),
             'input replaced':sample(24,0),'DC packing lost':sample(32,0),
             'Nyquist packing lost':sample(36,1),'inverse buffer lost':sample(40,0),
             'nonfinite samples':sample(24,float('nan')),'truncated':RAW[:-1],'trailing data':RAW+b'\0'}
        for name,data in bad.items():
            with self.subTest(name=name),self.assertRaises((AssertionError,struct.error)):
                parse(data)
        print('Rejected identical-but-invalid numeric artifacts:',len(bad))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('artifact',type=Path)
    a=p.parse_args();RAW=a.artifact.read_bytes();unittest.main(argv=[__file__])
