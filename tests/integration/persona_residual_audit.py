"""Enumerate observed cross-platform residuals; never declares persona parity."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest


def audit(candidate, reference):
    assert candidate['completed'] is True and reference['completed'] is True
    assert candidate['persona'] == 'linux-x86_64-software-v1'
    left = candidate['observations']['realms']
    right = reference['observations']['realms']
    differences = {}
    def walk(a, b, prefix):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    differences[prefix+'.'+key] = {'candidate_present':key in a, 'reference_present':key in b}
                else: walk(a[key], b[key], prefix+'.'+key)
        elif a != b:
            differences[prefix] = {'candidate':a, 'reference':b}
    # Sampled stable/functional fields only. Platform and build flags may
    # legitimately change availability. Each discrepancy needs its own review.
    for realm in sorted(set(left) & set(right)):
        for key in ('platform','api','globals','math'):
            walk(left[realm][key], right[realm][key], realm+'.'+key)
    for key in ('metrics','audio','webgl'):
        walk(left['window']['rendering'][key], right['window']['rendering'][key], 'window.rendering.'+key)
    return {'framework_sha256':candidate['framework_sha256'],
            'reference_version':reference['reference_version'],
            'same_version_reference':reference['same_version_baseline_proven'],
            'reference_default_configuration':reference['official_default_configuration_proven'],
            'differences':differences, 'observed_difference_count':len(differences),
            'full_emulated_persona_proven':False, 'full_scope_complete':False,
            'scope':'Diagnostic only: patch/headed/OS/build/environment differ; privacy noise also changes outputs. Equal sampled values do not prove complete API/font/Math/media/GPU parity.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate', type=Path); p.add_argument('reference', type=Path)
    a = p.parse_args()
    result = audit(json.loads(a.candidate.read_text()), json.loads(a.reference.read_text()))
    result['input_sha256'] = {str(f):digest(f) for f in (a.candidate,a.reference,Path(__file__))}
    print(json.dumps(result, ensure_ascii=False, indent=2))
