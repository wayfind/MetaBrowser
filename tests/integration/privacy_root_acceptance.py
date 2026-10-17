"""Replay bounded damaged-profile evidence; never a full privacy claim."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def verify(report, framework_sha256):
    assert report['completed'] is True and report['passed'] is True
    assert not report.get('error') and report['paid_model_calls'] == 0
    assert report['framework_sha256'] == framework_sha256
    cases = {'base64', 'short', 'empty', 'wrong_type', 'json_parse', 'json_type'}
    assert set(report['cases']) == cases
    directory = Path(report['root']).resolve(strict=True)
    for name, row in report['cases'].items():
        for flag in ['explicit_native_error', 'site_not_contacted',
                     'damaged_root_preserved', 'explicit_restore_recovers_navigation',
                     'restored_root_preserved', 'rejected_profile_picker_ready', 'rejected_clean_shutdown']:
            assert row[flag] is True
        assert row['rejected_exit_code'] == 0
        assert row['blocked_requests'] == []
        assert '/' + name + '/restored' in row['restored_requests']
        assert all('/blocked' not in path for path in row['restored_requests'])
        original = directory / (name + '-rejected-input.private.bin')
        assert not original.is_symlink() and digest(original) == row['rejected_input_sha256']
        raw = original.read_bytes()
        if name == 'json_parse':
            try:
                json.loads(raw)
            except ValueError:
                pass
            else:
                raise AssertionError('Parse-error case was valid JSON')
        elif name == 'json_type':
            assert isinstance(json.loads(raw), list)
        else:
            value = json.loads(raw)['metabrowser']['privacy']['root_secret']
            expected = {'base64': 'not-base64', 'short': base64.b64encode(b'short').decode(),
                        'empty': '', 'wrong_type': False}[name]
            assert type(value) is type(expected) and value == expected
        text = directory / (name + '-dialog.private.json')
        assert not text.is_symlink() and digest(text) == row['dialog_text_sha256']
        body = json.loads(text.read_text())['accessibility']
        assert '身份配置无法读取或校验' in ''.join(body.split()) and '原身份未更换' in body
        assert row['evidence_method'] in ('native-accessibility', 'owned-window-image-and-Vision-OCR')
        if row['evidence_method'] == 'owned-window-image-and-Vision-OCR':
            image = directory / (name + '-dialog.png')
            assert not image.is_symlink() and digest(image) == row['dialog_image_sha256']
        else:
            assert row['dialog_image_sha256'] is None, 'AX-only evidence cannot claim an image digest'
        if 'rejection_launches' in report:
            count = report['rejection_launches']
            assert type(count) is int and count in (1, 2, 3)
            attempts = row['rejection_attempts']
            assert len(attempts) == count
            for index, attempt in enumerate(attempts):
                assert attempt['index'] == index
                prefix = name if index == count - 1 else name + '-repeat-' + str(index)
                assert attempt['artifact_prefix'] == prefix
                assert attempt['exit_code'] == 0 and attempt['picker_ready'] is True
                assert attempt['blocked_requests'] == []
                text = directory / (prefix + '-dialog.private.json')
                assert not text.is_symlink() and digest(text) == attempt['dialog_text_sha256']
                body = json.loads(text.read_text())['accessibility']
                assert '身份配置无法读取或校验' in ''.join(body.split()) and '原身份未更换' in body
                assert attempt['evidence_method'] in ('native-accessibility', 'owned-window-image-and-Vision-OCR')
                if attempt['evidence_method'] == 'native-accessibility':
                    assert attempt['dialog_image_sha256'] is None
                else:
                    image = directory / (prefix + '-dialog.png')
                    assert not image.is_symlink() and digest(image) == attempt['dialog_image_sha256']
        pref = directory / name / 'Default/Preferences'
        restored = json.loads(pref.read_text())['metabrowser']['privacy']['root_secret']
        assert restored == base64.b64encode(b'r' * 32).decode()
    return {'passed': True, 'cases': len(cases), 'framework_sha256': framework_sha256,
            'scope': 'Six owned malformed-input/recovery scenarios; other storage/configuration failures unproven.',
            'full_privacy_proven': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    p.add_argument('--app', type=Path, required=True)
    a = p.parse_args()
    data = json.loads(a.report.read_text())
    for name, sha in data['probe_sha256'].items():
        assert digest(Path(name)) == sha, 'Probe changed: ' + name
    framework = a.app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    print(json.dumps(verify(data, digest(framework)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
