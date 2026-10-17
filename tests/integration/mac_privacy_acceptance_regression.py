"""Reject corrupted Mac probe evidence using an explicit passing collection.

Usage: python3 mac_privacy_acceptance_regression.py STATE_JSON REPORT_DIRECTORY
Only copies the supplied reports into a temporary directory. No browser,
network, user profile, SDK or original evidence is modified.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

from mac_privacy_acceptance import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    parser.add_argument('reports', type=Path)
    parser.add_argument('--require-review', action='store_true')
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    reports = args.reports
    validate(state, reports, require_webgl=True, require_mac=True, require_review=args.require_review)
    cases = {
        'unfinished collection': lambda s, r: s.update(completed=False),
        'unremoved fixture font': lambda s, r: s.update(font_installed_by_fixture=True),
        'reused report': lambda s, r: s['reports']['strict'].update(file=s['reports']['b']['file']),
        'truncated HDR sample': lambda s, r: r['a']['hdr'].update(sample=[]),
        'truncated audio sample': lambda s, r: r['a']['audio'].update(timeSample=[]),
        'truncated GL sample': lambda s, r: r['a']['webgl']['window']['webgl1'].update(sample=[]),
        'missing GPU identifier': lambda s, r: r['a']['gpu']['info'].pop('driver'),
        'malformed digest': lambda s, r: r['a']['hdr'].update(hash='not-a-digest'),
        'invalid CPU boolean': lambda s, r: r['a'].update(cpu={k: True for k in r['a']['cpu']}),
        'mismatched display realm': lambda s, r: r['a']['display']['iframe'].update(width=r['a']['display']['width']+1),
        'native unsupported behavior drift': lambda s, r: r['a']['webgl']['window']['webgl2']['formats'].update(
            rgb9e5={'supported': False, 'reason': 'changed'}),
        'empty format coverage': lambda s, r: [ctx['webgl2'].update(formats={}) for name in ('a','b','a_restart','strict') for ctx in r[name]['webgl'].values()],
        'corrupt float colors': lambda s, r: r['a']['webgl']['window']['webgl2']['float'].update(sample=[1e200]*32),
        'false native SAB result': lambda s, r: [ctx['webgl2'].update(sharedArrayBuffer=False) for report in r.values() for ctx in report['webgl'].values()],
        'string success flag': lambda s, r: r['a']['hdr'].update(stable='false'),
        'profile B raw HDR': lambda s, r: r['b'].update(hdr=copy.deepcopy(r['baseline']['hdr'])),
        'distinct profile HDR collision': lambda s, r: r['b'].update(hdr=copy.deepcopy(r['a']['hdr'])),
        'profile B raw audio': lambda s, r: r['b'].update(audio=copy.deepcopy(r['baseline']['audio'])),
        'malformed ICE list': lambda s, r: r['a'].update(ice={}),
        'invalid GPU flags': lambda s, r: r['a']['gpu'].update(available='false',adapter='false'),
        'negative speech count': lambda s, r: r['a']['speech'].update(count=-1,languages=[]),
        'inconsistent speech count': lambda s, r: r['a']['speech'].update(count=2,languages=[]),
        'profile B raw GL float': lambda s, r: [r['b']['webgl'][realm]['webgl2'].update(float=copy.deepcopy(r['baseline']['webgl'][realm]['webgl2']['float'])) for realm in r['b']['webgl']],
        'profile B raw formats': lambda s, r: [r['b']['webgl'][realm]['webgl2'].update(formats=copy.deepcopy(r['baseline']['webgl'][realm]['webgl2']['formats'])) for realm in r['b']['webgl']],
        'GL float realm drift': lambda s, r: [r[name]['webgl']['dedicated']['webgl2']['float'].update(hash='0'*64) for name in ('a','a_restart')],
        'strict UDP regression': lambda s, r: s['reports']['strict'].update(stun_requests=1),
    }
    if args.require_review:
        cases.update({
            'unclean cold restart': lambda s, r: s['reports']['a_restart'].update(clean_shutdown=False),
            'failed fixture cleanup': lambda s, r: s.update(cleanup_errors=['failed']),
            'missing engine provenance': lambda s, r: s.pop('framework_sha256'),
            'raw review HDR hash': lambda s, r: r['b']['webgl']['window']['webgl2']['hdrFloat'].update(hash=r['baseline']['webgl']['window']['webgl2']['hdrFloat']['hash']),
            'HDR rounding bypass': lambda s, r: r['a']['webgl']['window']['webgl2']['hdrFloat'].update(changedByChannel=[False,False,False]),
            'HDR alpha corruption': lambda s, r: r['a']['webgl']['window']['webgl2']['hdrFloat'].update(alphaStable=False),
        })
    with tempfile.TemporaryDirectory(prefix='metabrowser-evidence-regression-') as temporary:
        directory = Path(temporary)
        original = {name: json.loads((reports / record['file']).read_text())
                    for name, record in state['reports'].items()}
        for label, mutate in cases.items():
            modified, values = copy.deepcopy(state), copy.deepcopy(original)
            mutate(modified, values)
            # Distinct original filenames prevent mutated metadata from
            # accidentally overwriting a different report during preparation.
            for name, value in values.items():
                (directory / state['reports'][name]['file']).write_text(json.dumps(value))
            try:
                validate(modified, directory, require_webgl=True, require_mac=True, require_review=args.require_review)
            except (AssertionError, KeyError, ValueError):
                continue
            raise AssertionError('Invalid evidence accepted: ' + label)
    print(json.dumps({'passed': True, 'valid_collection_accepted': True,
                      'corrupted_collections_rejected': len(cases)}))


if __name__ == '__main__':
    main()
