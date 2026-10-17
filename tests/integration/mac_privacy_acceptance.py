"""Validate actual macOS probe collections, not just source presence.

Usage: python3 mac_privacy_acceptance.py STATE_JSON REPORT_DIRECTORY
Prints no host identifiers, tokens or canary font paths. Coverage is limited to
the stated assertions; passing does not certify anonymity or website acceptance.
"""
import argparse
import json
import math
import re
from pathlib import Path


def validate(state, directory, require_webgl=False, require_mac=False, require_review=False):
    assert state.get('completed') is True, 'Incomplete collection'
    assert state.get('font_installed_by_fixture') is False, 'Fixture font cleanup incomplete'
    assert not require_mac or require_webgl, 'Full Mac checks require WebGL coverage'
    if require_review:
        assert state.get('cleanup_errors') == [], 'Cleanup was not verified'
        digest_pattern = '[0-9a-f]{64}'
        assert re.fullmatch(digest_pattern, state.get('framework_sha256', '')), 'Missing engine provenance'
        assert all(state['reports'][n].get('clean_shutdown') is True for n in ('baseline','a','b','a_restart','strict')), 'Clean cold restart was not verified'
    reports = {}
    seen = set()
    def sample(value, length):
        assert isinstance(value, list) and len(value) == length, 'Truncated sample'
        assert all(type(v) in (int, float) and math.isfinite(v) for v in value), 'Invalid sample'
    def digest(value):
        assert isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'Missing or invalid digest'
    for name in ('baseline', 'a', 'b', 'a_restart', 'strict'):
        filename = state['reports'][name]['file']
        assert filename not in seen, 'Reused collection report'
        seen.add(filename)
        assert Path(filename).name == filename and filename.endswith('.json')
        file = directory / filename
        assert not file.is_symlink(), 'Report symlink is not allowed'
        assert file.stat().st_size <= 98304
        reports[name] = json.loads(file.read_text())
    baseline = reports['baseline']
    assert baseline['fonts']['localLoaded'] is True and baseline['fonts']['worker']['localLoaded'] is True, 'Canary was not visible in baseline'
    for name, report in reports.items():
        for key in ('cpu', 'fonts', 'hdr', 'audio', 'gpu', 'ice'):
            assert 'error' not in report[key], (name, key)
        cpu = report['cpu']
        assert set(cpu) == {'window', 'iframe', 'dedicated', 'module', 'nested', 'shared', 'service'}
        assert all(type(v) is int and v > 0 for v in cpu.values()), 'Invalid CPU values'
        assert len(set(cpu.values())) == 1, 'CPU realm mismatch'
        assert report['fonts']['remoteLoaded'] is True and report['fonts']['worker']['remoteLoaded'] is True
        assert report['fonts']['remoteWidth'] == report['fonts']['worker']['remoteWidth'] == 360
        assert report['fonts']['arialWidth'] == baseline['fonts']['arialWidth'], 'Stock font metrics changed'
        hdr = report['hdr']
        sample(hdr['sample'], 32)
        digest(hdr['hash'])
        assert hdr['type'] == 'Float16Array' and hdr['attributes']['colorType'] == 'float16'
        assert hdr['attributes']['colorSpace'] == 'display-p3'
        for key in ('stable', 'cropEqual', 'finite', 'alphaStable', 'pngStable', 'blob', 'offscreenBlob'):
            assert hdr[key] is True, (name, 'hdr', key)
        audio = report['audio']
        sample(audio['timeSample'], 16)
        digest(audio['timeHash'])
        digest(audio['freqHash'])
        for key in ('stable', 'freqStable', 'byteParity', 'freqByteParity', 'tailUntouched'):
            assert audio[key] is True, (name, 'audio', key)
        assert audio['worklet']['ok'] is True
        gpu = report['gpu']
        assert gpu['available'] is True and gpu['adapter'] is True, 'Real GPU fixture required'
        assert gpu['compute'] == [7, 8, 11, 16], 'GPU arithmetic corrupted'
        assert isinstance(report['ice'], list), 'Malformed ICE evidence'
        for candidate in report['ice']:
            assert isinstance(candidate, dict)
            assert candidate['protocol'] in ('udp','tcp')
            assert candidate['type'] in ('host','srflx','prflx','relay')
            assert type(candidate['hasRelatedAddress']) is bool and type(candidate['mdns']) is bool
            assert isinstance(candidate['addressClass'], str)
        if name == 'baseline':
            continue
        assert cpu['window'] in (1, 2, 4, 8) and cpu['window'] <= baseline['cpu']['window']
        assert report['fonts']['localLoaded'] is False and report['fonts']['worker']['localLoaded'] is False
        for info in (gpu['info'], gpu['deviceInfo']):
            assert info['vendor'] == baseline['gpu']['info']['vendor']
            assert all(info[key] == '' for key in ('architecture', 'device', 'description', 'driver', 'backend'))
            assert info['memoryHeaps'] == 0
        for index, value in enumerate(hdr['sample']):
            original = baseline['hdr']['sample'][index]
            assert math.isfinite(value)
            assert value == original if index % 4 == 3 else abs(value - original) <= .002
        for value, original in zip(audio['timeSample'], baseline['audio']['timeSample']):
            assert abs(value - original) <= 1.0e-7
        assert not any(c['hasRelatedAddress'] for c in report['ice']), 'Private related address exposed'
    for key, paths in (('hdr', ('hash',)), ('audio', ('timeHash', 'freqHash'))):
        for path in paths:
            for protected in ('a','b','a_restart','strict'):
                assert reports[protected][key][path] != baseline[key][path], (protected, key, path, 'baseline unchanged')
            assert reports['a'][key][path] != reports['b'][key][path], (key, path, 'identities not separated')
            assert reports['a'][key][path] == reports['a_restart'][key][path], (key, path, 'restart drift')
    assert state['reports']['baseline']['stun_requests'] > 0, 'STUN baseline unavailable'
    assert state['reports']['a']['stun_requests'] > 0, 'Public-interface STUN stopped working'
    assert state['reports']['strict']['stun_requests'] == 0, 'Strict policy leaked UDP'
    if require_webgl:
        realms = ('window', 'dedicated', 'module', 'shared', 'service')
        for name, report in reports.items():
            assert set(report['webgl']) == set(realms)
            for realm in realms:
                context = report['webgl'][realm]
                assert 'error' not in context, (name, realm)
                for version in ('webgl1', 'webgl2'):
                    gl = context[version]
                    sample(gl['sample'], 32)
                    digest(gl['hash'])
                    for check in ('stable', 'cropEqual', 'priorErrorPreserved'):
                        assert gl[check] is True, (name, realm, version, check)
                    if version == 'webgl2':
                        for check in ('packAndPadding', 'pboAndPadding', 'integerDataExact'):
                            assert gl[check] is True, (name, realm, version, check)
                        sab = baseline['webgl'][realm][version]['sharedArrayBuffer']
                        assert sab is True or sab == 'unavailable', 'Native SAB check failed'
                        assert gl['sharedArrayBuffer'] == sab, 'SAB capability or output regressed'
                        sample(gl['float']['sample'], 32)
                        digest(gl['float']['hash'])
                        assert gl['float']['stable'] is True and gl['float']['pboEqual'] is True
                    if name != 'baseline':
                        original = baseline['webgl'][realm][version]
                        for index, (value, old) in enumerate(zip(gl['sample'], original['sample'])):
                            assert value == old if index % 4 == 3 else abs(value - old) <= 1
                        if version == 'webgl2':
                            for i, (v, old) in enumerate(zip(gl['float']['sample'], original['float']['sample'])):
                                assert v == old if i % 4 == 3 else abs(v-old) <= max(1e-7,abs(old)*2**-23)
                        if version == 'webgl2':
                            assert gl['float']['hash'] != original['float']['hash'], 'Float output matches baseline'
                            assert gl['float']['hash'] == report['webgl']['window'][version]['float']['hash'], 'Float realm drift'
                        assert gl['hash'] != original['hash']
                        assert gl['hash'] == report['webgl']['window'][version]['hash'], 'Cross-realm WebGL drift'
        for realm in realms:
            for version in ('webgl1', 'webgl2'):
                a, b, restart = (reports[n]['webgl'][realm][version] for n in ('a', 'b', 'a_restart'))
                assert a['hash'] != b['hash'] and a['hash'] == restart['hash']
            a, b, restart = (reports[n]['webgl'][realm]['webgl2']['float'] for n in ('a', 'b', 'a_restart'))
            assert a['hash'] != b['hash'] and a['hash'] == restart['hash']
    if require_mac:
        assert baseline['fonts']['directWidth'] == 360
        assert baseline['fonts']['directPrivateGlyphWidth'] == 60, 'Private glyph canary was not active'
        for name, report in reports.items():
            assert 'error' not in report['display'] and 'error' not in report['speech']
            if name == 'baseline':
                continue
            font = report['fonts']
            for realm in (font, font['worker']):
                assert realm['directWidth'] == realm['genericWidth'], (name, 'font direct bypass')
                assert realm['privateGlyphFallbackWidth'] != 60, (name, 'font fallback bypass')
            assert font['directPrivateGlyphWidth'] != 60
            assert abs(font['svgDirectWidth'] - font['svgGenericWidth']) < .01
            assert font['stock'] == baseline['fonts']['stock'], (name, 'stock multilingual fonts changed')
            display = report['display']
            assert display['dpr'] == baseline['display']['dpr'], 'DPR changed'
            for field in ('innerWidth', 'innerHeight'):
                assert type(display[field]) is int and display[field] > 0, 'Invalid viewport'
            assert all(display[k] == display['iframe'][k] for k in ('width','height','dpr','colorDepth','orientation')), 'Display realm mismatch'
            for d in (display, display['iframe']):
                assert (d['width'], d['height']) in ((1440,900),(1680,1050),(1920,1200),(2560,1600))
                assert d['availWidth'] == d['width'] and d['availHeight'] == d['height'] - 24
                assert (d['x'],d['y'],d['availLeft'],d['availTop']) == (0,24,0,24)
                assert d['colorDepth'] == d['pixelDepth'] == 24
                assert d['orientation'] == 'landscape-primary' and d['angle'] == 0
                assert all(d[k] is True for k in ('cssDeviceWidth','cssDeviceHeight','color8','srgb'))
                assert all(d[k] is False for k in ('p3','hdr','extended'))
            voice = report['speech']
            assert voice['available'] is True
            assert type(voice['count']) is int and 0 <= voice['count'] <= 2
            assert isinstance(voice['languages'], list) and len(voice['languages']) == voice['count']
            assert all(isinstance(v, str) and v for v in voice['languages'])
            assert all(voice[k] is True for k in ('publicIdentityValid','uniqueLocales','nativeRoutingNotExposed'))
            assert len({v.lower() for v in voice['languages']}) == voice['count']
            assert all(lang.lower() in (voice['language'].lower(), 'en-us') for lang in voice['languages'])
            for realm, context in report['webgl'].items():
                formats = context['webgl2']['formats']
                expected_formats = baseline['webgl'][realm]['webgl2']['formats']
                required_formats = {'rgb565','rgba4444','rgba5551','rgb10a2','r11g11b10f','rgb9e5','rgba16f','r32f','rg32f'}
                assert required_formats <= set(expected_formats), 'Baseline missing required format coverage'
                assert set(formats) == set(expected_formats), 'Missing format coverage'
                for fmt, value in formats.items():
                    original = baseline['webgl'][realm]['webgl2']['formats'][fmt]
                    assert type(value['supported']) is bool and type(original['supported']) is bool
                    assert value['supported'] == original['supported'], (name, realm, fmt, 'capability changed')
                    if not value['supported']:
                        assert value == original, 'Native unsupported format behavior changed'
                        continue
                    digest(value['hash'])
                    assert value['hash'] != original['hash'], (name, realm, fmt, 'raw format output')
                    if value['invariant'] is not None:
                        digest(value['invariant'])
                    for check in ('stable', 'cropEqual', 'pboEqual', 'noError'):
                        assert value[check] is True, (name, realm, fmt, check)
                    assert value['invariant'] == original['invariant'], (name, realm, fmt, 'alpha/exponent changed')
                    assert value['hash'] == report['webgl']['window']['webgl2']['formats'][fmt]['hash']
        for fmt, value in reports['a']['webgl']['window']['webgl2']['formats'].items():
            if value['supported']:
                assert value['hash'] == reports['a_restart']['webgl']['window']['webgl2']['formats'][fmt]['hash']
                assert value['hash'] != reports['b']['webgl']['window']['webgl2']['formats'][fmt]['hash']
    if require_review:
        assert require_mac and require_webgl, 'Review coverage needs full Mac checks'
        for name, report in reports.items():
            for realm, context in report['webgl'].items():
                hdr = context['webgl2']['hdrFloat']
                sample(hdr['sample'], 32)
                digest(hdr['hash'])
                assert all(hdr[k] is True for k in ('stable','cropEqual','pboEqual','noError','withinBound','alphaStable'))
                if name == 'baseline':
                    assert hdr['sample'] == [1.5,-2.5,128.5,.75] * 8
                    assert hdr['changedByChannel'] == [False,False,False]
                    continue
                original = baseline['webgl'][realm]['webgl2']['hdrFloat']
                assert hdr['hash'] != original['hash'], 'HDR float baseline unchanged'
                for i, (value, old) in enumerate(zip(hdr['sample'], original['sample'])):
                    assert value == old if i % 4 == 3 else abs(value - old) <= max(5e-8, abs(old)*2**-23)
                assert hdr['changedByChannel'] == [True,True,True], 'HDR magnitude rounding bypass'
                assert hdr['hash'] == report['webgl']['window']['webgl2']['hdrFloat']['hash']
        for realm in reports['a']['webgl']:
            a, b, restart = (reports[n]['webgl'][realm]['webgl2']['hdrFloat']['hash'] for n in ('a','b','a_restart'))
            assert a != b and a == restart
    return {'passed': True, 'font_visibility_and_webfont_metrics': True,
            'cpu_seven_realms': True, 'hdr_float16_export_and_crop': True,
            'analyser_float_byte_parity_and_worklet': True,
            'webgpu_identifiers_and_real_compute': True,
            'profile_separation_and_cold_restart': True,
            'controlled_stun_udp_policy': True, 'paid_model_calls': 0,
            'webgl_readback_five_realms_pbo_shared_memory': require_webgl,
            'mac_font_source_display_formats_speech': require_mac,
            'hdr_webgl_float_magnitudes': require_review,
            'scope': 'specific local macOS surface invariants, not all fingerprint paths or websites'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    parser.add_argument('reports', type=Path)
    parser.add_argument('--require-webgl', action='store_true')
    parser.add_argument('--require-mac', action='store_true')
    parser.add_argument('--require-review', action='store_true')
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.state.read_text()), args.reports, args.require_webgl, args.require_mac, args.require_review), indent=2))


if __name__ == '__main__':
    main()
