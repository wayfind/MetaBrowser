"""Semantic acceptance of collected native privacy probe JSON; never launches anything.

Usage: python3 tests/integration/privacy_acceptance_test.py baselineDir candidateDir
Inputs may be one report file or a directory of schema-1 reports from
fingerprint_probe.py /reports/ID (a {"report": ...} wrapper is also accepted).
Duplicate origins are repeat captures, and their selected evidence must agree.
The directories must contain only report JSON, not collector configuration.

Optional --profile-a defaults to candidateDir. --profile-b proves separate-profile
separation; --restart proves profile-a persistence; --otr proves separation from
profile-a; --otr-restart proves a fresh OTR session differs from --otr. Origins
must match across each comparison. Missing optional collections are explicitly
unverified. All output is JSON on stdout; exit 0 means the declared checks passed,
1 means failed evidence, 2 means invalid CLI. No network, MCP call, UI, provider,
subprocess, environment credentials, report edits, or app launch is performed.

This checks bounded native behavior and partition evidence, NOT anonymity,
chosen-content resistance, HDR, or complete fingerprint protection.
Shared/service worker canvas fields are validated when present; use
--require-persistent-workers to fail older captures missing either field.
--off and --site-exception accept baseline-mode captures after a full browser
restart. The site-exception directory must contain only exempted origins and
may be a subset of baseline origins. Explicit persist_sw fixtures must preserve
their own known registration; normal one-off fixtures must unregister it.
Registration reuse alone does not prove a browser process restart.
"""

import argparse
import hashlib
import itertools
import json
import math
import pathlib
import re
import sys
import unittest
import urllib.parse


MAX_REPORT_BYTES = 1024 * 1024
MAX_REPORTS = 64
HASH = re.compile(r"^[0-9a-f]{64}$")
DEBUG_EXTENSION = 'WEBGL_debug_renderer_info'
# Protected contexts read an Apple GPU-family cohort renderer (M1, M2, M3 and
# later -> M3) without tier names; an unmapped GPU keeps the extension hidden.
COHORT = re.compile(r'Apple M[123](?:,|\))')
TIER = re.compile(r'\b(?:Pro|Max|Ultra)\b')
DEVICE_CLASS_PATHS = ('probes.P4.main.hardwareConcurrency', 'probes.P4.main.deviceMemory')
INHERITED = ('initialEmpty', 'aboutBlank', 'srcdoc', 'documentWrite')
WORKERS = ('httpClassic', 'httpModule', 'blobClassic', 'nestedClassic')
# Explicitly selected stable behavior. Volatile environment measurements are
# disclosed below, never silently normalized out of a full-report comparison.
STATIC_PATHS = (
    'probes.P4.main.userAgent', 'probes.P4.main.appVersion',
    'probes.P4.main.appName', 'probes.P4.main.appCodeName',
    'probes.P4.main.platform', 'probes.P4.main.vendor',
    'probes.P4.main.product', 'probes.P4.main.language',
    'probes.P4.main.languages', 'probes.P4.main.hardwareConcurrency',
    'probes.P4.main.deviceMemory', 'probes.P4.main.maxTouchPoints',
    'probes.P4.main.webdriver', 'probes.P4.main.userAgentData',
    'probes.P4.main.plugins', 'probes.P4.main.mimeTypes',
    'probes.P4.main.features', 'probes.P5.screen', 'probes.P5.orientation',
    'probes.P5.media', 'probes.P6.fonts', 'probes.P9.apis',
    'probes.P9.navigatorAPIs', 'probes.P9.nativeStrings', 'probes.P9.css',
    'probes.P9.pdfViewer', 'probes.P9.secureContext',
    'probes.P9.crossOriginIsolated', 'probes.P10',
    'probes.P11.dateTime', 'probes.P11.number', 'probes.P11.collator',
    'probes.P11.winterOffset', 'probes.P11.summerOffset',
    'probes.P11.math', 'probes.P11.mathFixed15',
    'probes.P11.regexpLookbehind', 'probes.P12.storageAPIs',
)
UNASSESSED = (
    'run/collector headers; collection provenance only',
    'P4 connection/onLine runtime measurements',
    'P5 window/visualViewport/resizeSamples; viewport and UI environment',
    'P9 windowKeys; asynchronous page globals',
    'P11 stack/fixedDate; source locations and date formatting diagnostics',
    'P12 permission states/storage estimates; runtime grants and quotas',
    'P13 ICE opt-in evidence',
    'HDR, cached shared/service worker restart lifecycle, worklets, chosen-content averaging resistance',
)


class EvidenceError(ValueError):
    pass


def field(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise EvidenceError('Missing required field: ' + path)
        value = value[key]
    return value


def digest(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def reject_constant(value):
    raise EvidenceError('Non-finite JSON constant: ' + value)


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError('Non-finite JSON number')
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def load_collection(path):
    path = pathlib.Path(path)
    files = sorted(path.glob('*.json')) if path.is_dir() else [path]
    if not files or len(files) > MAX_REPORTS:
        raise EvidenceError('Expected 1..64 report JSON files: ' + str(path))
    groups, inventory = {}, []
    for source in files:
        with source.open('rb') as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise EvidenceError('Report exceeds 1 MiB: ' + str(source))
        value = json.loads(raw, parse_constant=reject_constant, parse_float=finite_float,
                           object_pairs_hook=unique_object)
        if isinstance(value, dict) and value.get('jsonrpc') == '2.0':
            if 'error' in value or not isinstance(value.get('result'), dict):
                raise EvidenceError('MCP JSON-RPC error or missing result: ' + str(source))
            value = value['result']
        if isinstance(value, dict) and ('content' in value or 'structuredContent' in value):
            if value.get('isError'):
                raise EvidenceError('MCP tool error: ' + str(source))
            if 'structuredContent' in value:
                value = value['structuredContent']
            else:
                blocks = value['content']
                if (not isinstance(blocks, list) or len(blocks) != 1
                        or not isinstance(blocks[0], dict) or blocks[0].get('type') != 'text'
                        or not isinstance(blocks[0].get('text'), str)):
                    raise EvidenceError('Expected one MCP JSON text block: ' + str(source))
                value = json.loads(blocks[0]['text'], parse_constant=reject_constant, parse_float=finite_float,
                                   object_pairs_hook=unique_object)
        if isinstance(value, dict) and 'report' in value:
            value = value['report']
        if (not isinstance(value, dict) or type(value.get('schema')) is not int
                or value['schema'] != 1 or not isinstance(value.get('probes'), dict)):
            raise EvidenceError('Expected schema-1 probe report: ' + str(source))
        origin = value.get('origin')
        if not isinstance(origin, str):
            raise EvidenceError('Missing report origin: ' + str(source))
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            raise EvidenceError('Expected HTTP(S) origin, without path: ' + origin)
        # Accessing port also rejects malformed/out-of-range ports.
        _ = parsed.port
        groups.setdefault(origin, []).append(value)
        inventory.append({'file': str(source), 'origin': origin,
                          'sha256': hashlib.sha256(raw).hexdigest()})
    return groups, inventory


class Checker:
    def __init__(self):
        self.checks = []

    def check(self, condition, name, detail=''):
        self.checks.append({'check': name, 'passed': bool(condition), 'detail': detail})

    def equal(self, left, right, name):
        self.check(type(left) is type(right) and left == right, name,
                   '' if type(left) is type(right) and left == right else 'Values differ')

    def hash(self, value, name):
        self.check(digest(value), name, 'Required SHA-256 digest')
        return value

    def healthy(self, value, name):
        """Unexpected errors/unsupported markers fail in required probe scopes."""
        if isinstance(value, dict):
            for key in ('error', 'unsupported', 'excluded', 'skipped'):
                if key in value and value[key] not in (False, None, 0):
                    self.check(False, name + '.' + key, str(value[key])[:240])
            for key, child in value.items():
                self.healthy(child, name + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.healthy(child, name + '.' + str(index))

    def canvas(self, value, name, html=True, repeat_blobs=True, size=(240, 60)):
        if not isinstance(value, dict):
            raise EvidenceError(name + ': expected canvas object')
        # P6 embeds other probes, including one deliberately expected exception.
        # Validate those separately instead of exempting arbitrary errors.
        self.healthy({k: v for k, v in value.items() if k not in
                      ('workers', 'offscreenMain', 'inheritedRealms',
                       'readRegressions', 'parity', 'sharedWorker', 'serviceWorker')}, name)
        self.equal(field(value, 'width'), size[0], name + '.width')
        self.equal(field(value, 'height'), size[1], name + '.height')
        a = self.hash(field(value, 'pixels1'), name + '.pixels1')
        b = self.hash(field(value, 'pixels2'), name + '.pixels2')
        self.equal(a, b, name + '.repeatedPixels')
        self.equal(field(value, 'checks.pixelsRepeat'), True, name + '.pixelCheck')
        if html:
            e = self.hash(field(value, 'export1'), name + '.export1')
            self.hash(field(value, 'export2'), name + '.export2')
            self.equal(e, value['export2'], name + '.repeatedExport')
            self.equal(field(value, 'checks.exportsRepeat'), True, name + '.exportCheck')
        else:
            self.equal(field(value, 'toDataURLAvailable'), False, name + '.offscreenAPI')
            self.equal(field(value, 'export1'), None, name + '.noDataURL1')
            self.equal(field(value, 'export2'), None, name + '.noDataURL2')
        blob = self.hash(field(value, 'blobHash1' if repeat_blobs else 'blobHash'),
                         name + '.blobHash')
        if repeat_blobs:
            self.hash(field(value, 'blobHash2'), name + '.blobHash2')
            self.equal(blob, value['blobHash2'], name + '.repeatedBlob')
            self.equal(field(value, 'checks.blobsRepeat'), True, name + '.blobCheck')
        if html:
            self.equal(blob, value['export1'], name + '.blobMatchesDataURL')
            self.equal(field(value, 'checks.blobMatchesDataURL'), True,
                       name + '.blobDataURLCheck')
        return a

    def raw_canvas(self, value, name, size):
        self.healthy(value, name)
        self.equal(field(value, 'width'), size[0], name + '.width')
        self.equal(field(value, 'height'), size[1], name + '.height')
        for first, second in (('pixels1', 'pixels2'), ('export1', 'export2')):
            self.hash(field(value, first), name + '.' + first)
            self.hash(field(value, second), name + '.' + second)
            self.equal(value[first], value[second], name + '.' + first + 'Stable')
        self.equal(field(value, 'checks.pixelsRepeat'), True, name + '.pixelCheck')
        self.equal(field(value, 'checks.exportsRepeat'), True, name + '.exportCheck')

    def service_worker_cleanup(self, value, origin, name):
        persistent = value.get('persistent', False)
        self.check(type(persistent) is bool, name + '.persistentModeBoolean')
        cleanup = field(value, 'cleanup')
        self.equal(field(cleanup, 'ownRegistrationOnly'), True, name + '.ownCleanupOnly')
        if persistent is True:
            # Only the explicit, known cached-restart fixture may retain a
            # registration. A generic failed unregister must still fail.
            self.equal(field(value, 'scope'), '/privacy-probe-sw-cached-v1/',
                       name + '.persistentFixtureScope')
            self.equal(field(value, 'scriptURL'),
                       origin + '/privacy-worker-service.js?fixture_version=1',
                       name + '.persistentFixtureScript')
            self.equal(field(value, 'transport'), 'http-service-worker', name + '.transport')
            self.check(type(field(value, 'reusedRegistration')) is bool,
                       name + '.reusedRegistrationBoolean')
            self.equal(field(cleanup, 'preservedForCachedRestart'), True,
                       name + '.preservedForCachedRestart')
            unregistered = field(cleanup, 'unregistered')
            self.check(unregistered is None or unregistered is False,
                       name + '.persistentNotUnregistered',
                       'Persistent fixture must retain its registration; null/false only')
        else:
            self.equal(cleanup.get('preservedForCachedRestart', False), False,
                       name + '.notPreserved')
            self.equal(field(cleanup, 'unregistered'), True, name + '.unregistered')

    def regressions(self, value, name, candidate):
        for key in ('croppedAndTiled', 'transparency'):
            self.healthy(field(value, key), name + '.' + key)
        tiles = field(value, 'croppedAndTiled')
        self.hash(field(tiles, 'fullHash'), name + '.fullHash')
        self.hash(field(tiles, 'stitchedHash'), name + '.stitchedHash')
        self.equal(tiles['fullHash'], tiles['stitchedHash'], name + '.stitchedMatchesFull')
        pieces = field(tiles, 'pieces')
        if not isinstance(pieces, list) or len(pieces) < 2:
            raise EvidenceError(name + ': missing crop/tile evidence')
        for index, piece in enumerate(pieces):
            label = name + '.piece' + str(index)
            for key in ('fullCropHash', 'subrectHash', 'repeatHash'):
                self.hash(field(piece, key), label + '.' + key)
            self.equal(piece['fullCropHash'], piece['subrectHash'], label + '.cropEquality')
            self.equal(piece['subrectHash'], piece['repeatHash'], label + '.repeatEquality')
            for key in ('matchesFullCrop', 'repeat'):
                self.equal(field(piece, 'checks.' + key), True, label + '.' + key)
        for key in ('allSubrectsMatch', 'allSubrectsRepeat', 'stitchedMatchesFull'):
            self.equal(field(tiles, 'checks.' + key), True, name + '.' + key)
        alpha = field(value, 'transparency')
        for key in ('insideHashes', 'outsideHashes'):
            hashes = field(alpha, key)
            self.check(isinstance(hashes, list) and len(hashes) == 2
                       and all(digest(h) for h in hashes) and hashes[0] == hashes[1],
                       name + '.' + key)
        for key in ('alphaMatchesKnownCoverage', 'alphaRepeat', 'outsideAlphaZero',
                    'insideTransparentAlphaZero'):
            self.equal(field(alpha, 'checks.' + key), True, name + '.' + key)
        budget = field(value, 'sourceSizeBudget')
        width, height = field(budget, 'source.width'), field(budget, 'source.height')
        self.check(type(width) is int and type(height) is int and width > 0
                   and height > 0 and width * height > 4 * 1024 * 1024,
                   name + '.oversizedSource')
        self.equal(field(budget, 'source.pixels'), width * height, name + '.sourceArea')
        self.equal(field(budget, 'read.width'), 1, name + '.tinyReadWidth')
        self.equal(field(budget, 'read.height'), 1, name + '.tinyReadHeight')
        actual = field(budget, 'actual')
        if candidate:
            # This precise expected exception is not a general error exemption.
            self.equal(field(actual, 'status'), 'exception', name + '.budgetRejected')
            self.equal(field(actual, 'error'), 'NotSupportedError', name + '.budgetError')
        else:
            self.healthy(actual, name + '.baselineBudget')
            self.equal(field(actual, 'status'), 'completed', name + '.baselineBudgetCompleted')
            self.equal(field(actual, 'width'), 1, name + '.baselineReadWidth')
            self.equal(field(actual, 'height'), 1, name + '.baselineReadHeight')
            self.hash(field(actual, 'hash'), name + '.baselineBudgetHash')

    def report(self, report, name, candidate):
        self.equal(report['schema'], 1, name + '.schema')
        p6 = field(report, 'probes.P6')
        main = self.canvas(p6, name + '.canvas', repeat_blobs=False)
        for key in ('sourceBefore', 'sourceAfter'):
            self.hash(field(p6, key), name + '.' + key)
            self.equal(p6[key], main, name + '.' + key + 'MatchesPixels')
        self.equal(field(p6, 'checks.sourceCopyUnchanged'), True, name + '.sourceUnchanged')
        offscreen = field(p6, 'offscreenMain')
        self.equal(self.canvas(offscreen, name + '.offscreen', html=False), main,
                   name + '.mainOffscreenPixels')
        self.equal(field(p6, 'parity.mainOffscreen'), True, name + '.offscreenParityCheck')
        for worker in WORKERS:
            value = field(p6, 'workers.' + worker)
            # Navigator unsupported fields are platform diagnostics, not canvas
            # omissions. Canvas and outer worker errors are checked explicitly.
            self.healthy({k: v for k, v in value.items() if k not in ('navigator', 'nested')},
                         name + '.' + worker)
            canvas = field(value, 'canvas')
            self.equal(self.canvas(canvas, name + '.' + worker + '.canvas', html=False),
                       main, name + '.' + worker + '.pixelParity')
            self.equal(field(p6, 'parity.workers.' + worker + '.pixels'), True,
                       name + '.' + worker + '.parityCheck')
            if worker == 'nestedClassic':
                nested = field(value, 'nested.canvas')
                self.equal(self.canvas(nested, name + '.nested.canvas', html=False), main,
                           name + '.nested.pixelParity')
                self.equal(field(p6, 'parity.workers.nestedClassic.nestedPixels'), True,
                           name + '.nested.parityCheck')
        for kind in ('sharedWorker', 'serviceWorker'):
            if kind not in p6:
                continue
            value = p6[kind]
            if not isinstance(value, dict):
                raise EvidenceError(name + '.' + kind + ': expected worker object')
            self.healthy({k: v for k, v in value.items() if k != 'navigator'}, name + '.' + kind)
            self.equal(self.canvas(field(value, 'canvas'), name + '.' + kind + '.canvas', html=False),
                       main, name + '.' + kind + '.pixelParity')
            self.equal(field(p6, 'parity.' + kind), True, name + '.' + kind + '.parityCheck')
            if kind == 'serviceWorker':
                self.service_worker_cleanup(value, report['origin'], name + '.serviceWorker')
        inherited = field(p6, 'inheritedRealms')
        parent = field(inherited, 'parent')
        self.equal(self.canvas(parent, name + '.inheritedParent'), main,
                   name + '.inheritedParentParity')
        for kind in INHERITED:
            value = field(inherited, 'observations.' + kind)
            self.healthy(value, name + '.' + kind)
            self.equal(field(value, 'effectiveOrigin'), report['origin'],
                       name + '.' + kind + '.effectiveOrigin')
            for key in ('own', 'parentToChild', 'childToParent'):
                item = field(value, key)
                self.equal(self.canvas(item, name + '.' + kind + '.' + key), main,
                           name + '.' + kind + '.' + key + '.pixelParity')
                self.equal(item['export1'], p6['export1'],
                           name + '.' + kind + '.' + key + '.exportParity')
            for key in ('ownPixels', 'ownExport', 'parentToChildPixels', 'childToParentPixels'):
                self.equal(field(value, 'parity.' + key), True, name + '.' + kind + '.' + key)
        opaque = field(inherited, 'observations.opaqueSandboxSrcdoc')
        self.healthy(opaque, name + '.opaque')
        self.equal(field(opaque, 'reportedOrigin'), 'null', name + '.opaqueOrigin')
        self.equal(field(opaque, 'url'), 'about:srcdoc', name + '.opaqueURL')
        self.raw_canvas(field(opaque, 'own'), name + '.opaque.own', (240, 60))
        self.raw_canvas(field(opaque, 'solid'), name + '.opaque.solid', (16, 16))
        self.canvas(field(opaque, 'parentSolid'), name + '.opaque.parentSolid', size=(16, 16))
        expected = self.hash(field(opaque, 'rawExpectedSolidPixels'), name + '.rawSentinel')
        self.equal(expected, hashlib.sha256(bytes([17, 34, 51, 255]) * 256).hexdigest(),
                   name + '.independentRawSentinel')
        self.check((opaque['solid']['pixels1'] != expected) is candidate,
                   name + '.rawSentinelExposure', 'Candidate differs; baseline equals known raw RGBA')
        for key in ('originOpaque', 'canonicalStable', 'solidStable', 'canonicalExportsStable'):
            self.equal(field(opaque, 'checks.' + key), True, name + '.opaque.' + key)
        for key in ('canonicalDistinctFromParent', 'solidDistinctFromParent', 'rawExpectedNotExposed'):
            self.equal(field(opaque, 'checks.' + key), candidate, name + '.opaque.' + key)
        self.check((opaque['own']['pixels1'] != main) is candidate,
                   name + '.opaqueCanonicalSeparation')
        self.check((opaque['solid']['pixels1'] != opaque['parentSolid']['pixels1']) is candidate,
                   name + '.opaqueSolidSeparation')
        self.regressions(field(p6, 'readRegressions'), name + '.readRegressions', candidate)
        audio = field(report, 'probes.P8')
        self.healthy(audio, name + '.audio')
        hashes = field(audio, 'hashes')
        self.check(isinstance(hashes, list) and len(hashes) == 4
                   and all(digest(h) for h in hashes) and len(set(hashes)) == 1,
                   name + '.audioReadAndCopyParity')
        for key in ('finite', 'getChannelRepeat', 'copyRepeat', 'getMatchesCopy'):
            self.equal(field(audio, 'checks.' + key), True, name + '.audio.' + key)
        samples = field(audio, 'samples4500to4510')
        self.check(isinstance(samples, list) and len(samples) == 10
                   and all(type(n) in (int, float) and math.isfinite(n) for n in samples),
                   name + '.audioFiniteSamples')
        for key, expected_value in (('sampleRate', 44100), ('length', 5000), ('channels', 1)):
            self.equal(field(audio, key), expected_value, name + '.audio.' + key)
        self.check(type(field(audio, 'duration')) in (int, float)
                   and math.isclose(audio['duration'], 5000 / 44100, rel_tol=1e-12),
                   name + '.audioDuration')
        energy = field(audio, 'sumAbsolute4500to5000')
        self.check(type(energy) in (int, float) and math.isfinite(energy) and energy > 0,
                   name + '.audioNonSilentFiniteEnergy')
        for kind in ('webgl', 'webgl2'):
            gl = field(report, 'probes.P7.' + kind)
            self.healthy({k: v for k, v in gl.items() if k != 'unmasked'}, name + '.' + kind)
            extensions = field(gl, 'extensions')
            self.check(isinstance(extensions, list) and all(isinstance(e, str) for e in extensions)
                       and len(set(extensions)) == len(extensions), name + '.' + kind + '.extensions')
            unmasked = field(gl, 'unmasked')
            absent = isinstance(unmasked, dict) and unmasked == {'unsupported': True}
            self.equal(DEBUG_EXTENSION not in extensions, absent,
                       name + '.' + kind + '.listGetExtensionConsistency')
            if candidate:
                if absent:
                    self.check(DEBUG_EXTENSION not in extensions,
                               name + '.' + kind + '.debugExtensionHidden')
                else:
                    renderer = field(unmasked, 'renderer')
                    self.check(isinstance(renderer, str) and COHORT.search(renderer) is not None
                               and TIER.search(renderer) is None,
                               name + '.' + kind + '.rendererCohort')
                    self.check(isinstance(field(unmasked, 'vendor'), str) and bool(unmasked['vendor']),
                               name + '.' + kind + '.vendor')
            else:
                self.healthy(unmasked, name + '.' + kind + '.baselineUnmasked')
                self.check(DEBUG_EXTENSION in extensions and not absent,
                           name + '.' + kind + '.baselineDebugExtensionAvailable')
                for key in ('vendor', 'renderer'):
                    self.check(isinstance(field(unmasked, key), str) and bool(unmasked[key]),
                               name + '.' + kind + '.' + key)
            render = field(gl, 'render')
            for key in ('first', 'second'):
                self.hash(field(render, key), name + '.' + kind + '.' + key)
            self.equal(render['first'], render['second'], name + '.' + kind + '.renderStable')
            self.equal(field(render, 'repeat'), True, name + '.' + kind + '.repeatCheck')
            self.equal(field(render, 'error'), 0, name + '.' + kind + '.noGLError')


def selected(report):
    """Explicit arrays make evidence for persistence/isolation reviewable."""
    return {
        'canvas': [field(report, 'probes.P6.' + k) for k in ('pixels1', 'export1', 'blobHash')],
        'audio': field(report, 'probes.P8.hashes'),
        'static': [{'path': p, 'value': field(report, p)} for p in STATIC_PATHS],
    }


def protected_device_class(cores, memory):
    """Native policy: cores bucket down to 1/2/4/8; memory <= 2 GiB per bucketed core."""
    bucket = 8 if cores >= 8 else 4 if cores >= 4 else 2 if cores >= 2 else 1
    return [bucket, min(memory, 2 * bucket)]


def renderer_cohort(renderer):
    """Python mirror of the engine's MetaBrowserRendererCohort mapping."""
    match = re.search(r'Apple M(\d+)', renderer) if isinstance(renderer, str) else None
    if not match or not int(match.group(1)):
        return None
    generation = int(match.group(1))
    chip = 'Apple M1' if generation == 1 else 'Apple M2' if generation == 2 else 'Apple M3'
    end = renderer.find(',', match.end())
    return renderer[:match.start()] + chip + (renderer[end:] if end != -1 else '')


def functionality(checker, left, right, name, audio_delta=1e-7):
    # Only the unprotected baseline against a protected capture changes the
    # device class and the unmasked renderer; every other pairing is exact.
    protected_pair = name.startswith('baselineToCandidate.')
    for path in STATIC_PATHS:
        if protected_pair and path in DEVICE_CLASS_PATHS:
            continue
        checker.equal(field(left, path), field(right, path), name + '.' + path)
    if protected_pair:
        cores, memory = (field(left, path) for path in DEVICE_CLASS_PATHS)
        checker.check(type(cores) is int and cores > 0 and type(memory) in (int, float) and memory > 0,
                      name + '.baselineDeviceClass')
        if type(cores) is int and type(memory) in (int, float):
            checker.equal([field(right, path) for path in DEVICE_CLASS_PATHS],
                          protected_device_class(cores, memory), name + '.protectedDeviceClass')
        for kind in ('webgl', 'webgl2'):
            base = field(left, 'probes.P7.' + kind + '.unmasked')
            protected = field(right, 'probes.P7.' + kind + '.unmasked')
            expected = renderer_cohort(base.get('renderer')) if isinstance(base, dict) else None
            if expected:
                checker.equal(protected, {'vendor': base.get('vendor'), 'renderer': expected},
                              name + '.' + kind + '.rendererCohortFromBaseline')
            else:
                checker.equal(protected, {'unsupported': True}, name + '.' + kind + '.unmappedRendererHidden')
    for key in ('sampleRate', 'length', 'duration', 'channels'):
        checker.equal(field(left, 'probes.P8.' + key), field(right, 'probes.P8.' + key),
                      name + '.audio.' + key)
    a = field(left, 'probes.P8.samples4500to4510')
    b = field(right, 'probes.P8.samples4500to4510')
    checker.check(all(abs(x - y) <= audio_delta + 1e-12 for x, y in zip(a, b)),
                  name + '.audioSamplePerturbationBound')
    checker.check(abs(field(left, 'probes.P8.sumAbsolute4500to5000')
                      - field(right, 'probes.P8.sumAbsolute4500to5000')) <= 500 * audio_delta + 1e-10,
                  name + '.audioEnergyPerturbationBound')
    for kind in ('webgl', 'webgl2'):
        for key in ('limits', 'precision', 'contextAttributes'):
            checker.equal(field(left, 'probes.P7.' + kind + '.' + key),
                          field(right, 'probes.P7.' + kind + '.' + key),
                          name + '.' + kind + '.' + key)
        a = field(left, 'probes.P7.' + kind + '.extensions')
        b = field(right, 'probes.P7.' + kind + '.extensions')
        checker.equal(sorted(e for e in a if e != DEBUG_EXTENSION),
                      sorted(e for e in b if e != DEBUG_EXTENSION),
                      name + '.' + kind + '.otherExtensionsUnchanged')


def compare_sets(checker, left, right, name, same, subset=False):
    if subset:
        checker.check(bool(right) and right.keys() <= left.keys(), name + '.originCoverage')
    else:
        checker.equal(sorted(left), sorted(right), name + '.originCoverage')
    for origin in sorted(left.keys() & right.keys()):
        a, b = left[origin][0], right[origin][0]
        # Two independently perturbed profiles may differ by twice the
        # baseline-to-protected bound. Same-profile persistence must be exact.
        tolerance = 0 if same else 1e-7 if name == 'baselineToCandidate' else 2e-7
        functionality(checker, a, b, name + '.' + origin, audio_delta=tolerance)
        for surface in ('canvas', 'audio'):
            for index, (x, y) in enumerate(zip(selected(a)[surface], selected(b)[surface])):
                checker.check((x == y) is same,
                              name + '.' + origin + '.' + surface + '.' + str(index),
                              'Expected ' + ('stable evidence' if same else 'different partition evidence'))


def evaluate(paths):
    checker, collections, inventory, evidence = Checker(), {}, {}, {}
    for label, path in paths.items():
        if path is None or label == 'require_persistent_workers':
            continue
        try:
            groups, inventory[label] = load_collection(path)
            collections[label] = groups
            for origin, reports in groups.items():
                for index, report in enumerate(reports):
                    try:
                        protected = label not in ('baseline', 'off', 'site_exception')
                        checker.report(report, f'{label}.{origin}[{index}]', protected)
                        if paths.get('require_persistent_workers'):
                            for kind in ('sharedWorker', 'serviceWorker'):
                                checker.check(kind in report['probes']['P6'],
                                              f'{label}.{origin}[{index}].requires.{kind}')
                        selected(report)
                    except (EvidenceError, TypeError, IndexError, KeyError, AttributeError) as error:
                        checker.check(False, f'{label}.{origin}[{index}].requiredEvidence', str(error))
                    if index:
                        try:
                            checker.equal(selected(reports[0]), selected(report),
                                          f'{label}.{origin}[{index}].repeatCaptureStable')
                            if label not in ('baseline', 'off', 'site_exception'):
                                checker.check(field(reports[0], 'probes.P6.inheritedRealms.observations.opaqueSandboxSrcdoc.own.pixels1')
                                              != field(report, 'probes.P6.inheritedRealms.observations.opaqueSandboxSrcdoc.own.pixels1'),
                                              f'{label}.{origin}[{index}].opaqueEphemeral')
                        except EvidenceError as error:
                            checker.check(False, label + '.repeatCaptureEvidence', str(error))
                try:
                    evidence.setdefault(label, []).append({'origin': origin, **selected(reports[0])})
                except EvidenceError:
                    pass
        except (OSError, ValueError, TypeError, RecursionError) as error:
            checker.check(False, label + '.input', str(error))
    # Do not manufacture secondary comparisons after structural failures.
    if all(c['passed'] for c in checker.checks) and {'baseline', 'candidate'} <= collections.keys():
        baseline, candidate = collections['baseline'], collections['candidate']
        compare_sets(checker, baseline, candidate, 'baselineToCandidate', same=False)
        for label, groups in collections.items():
            if label in ('baseline', 'off', 'site_exception'):
                continue
            for a, b in itertools.combinations(sorted(groups), 2):
                # Origin is part of the native partition, including ports.
                for surface in ('canvas', 'audio'):
                    checker.check(all(x != y for x, y in zip(selected(groups[a][0])[surface], selected(groups[b][0])[surface])),
                                  label + '.crossOrigin.' + a + '->' + b + '.' + surface,
                                  'Different-origin partition evidence; not a universal unlinkability claim')
        reference = collections.get('profile_a', candidate)
        for label, same in (('profile_b', False), ('restart', True), ('otr', False)):
            if label in collections:
                compare_sets(checker, reference, collections[label], label, same)
        if 'otr_restart' in collections:
            if 'otr' not in collections:
                checker.check(False, 'otr_restart.requiresOTR', '--otr is required')
            else:
                compare_sets(checker, collections['otr'], collections['otr_restart'], 'otr_restart', False)
        for label in ('off', 'site_exception'):
            if label in collections:
                compare_sets(checker, baseline, collections[label], label, True,
                             subset=label == 'site_exception')
    failed = sum(not c['passed'] for c in checker.checks)
    return {
        'status': 'failed' if failed or not checker.checks else 'passed',
        'purpose': 'Native privacy semantic acceptance; not full fingerprint protection or anonymity',
        'summary': {'checks': len(checker.checks), 'failed': failed},
        'checks': checker.checks, 'inputs': inventory, 'selectedEvidence': evidence,
        'optionalCoverage': {k: 'supplied' if paths.get(k) else 'not_verified'
                             for k in ('profile_a', 'profile_b', 'restart', 'otr', 'otr_restart',
                                       'off', 'site_exception')},
        'crossOriginCoverage': {k: {'origins': len(v), 'pairs': len(v) * (len(v) - 1) // 2,
                                  'status': 'supplied' if len(v) > 1 else 'not_verified'}
                                for k, v in collections.items()},
        'comparisonPolicy': {'stableFunctionalityPaths': list(STATIC_PATHS),
                             'explicitlyUnassessed': list(UNASSESSED),
                             'expectedDifferences': ['canvas/audio partition hashes',
                                                     'WEBGL_debug_renderer_info renderer as Apple GPU-family cohort (hidden when unmapped)',
                                                     'hardwareConcurrency/deviceMemory as protected device class',
                                                     'oversized source read rejected',
                                                     'opaque raw sentinel no longer exposed']},
        'persistentWorkerCoverage': {
            label: [{'origin': origin,
                     'sharedWorker': 'collected' if 'sharedWorker' in report['probes']['P6'] else 'not_verified',
                     'serviceWorker': (
                         {'mode': 'persistent_fixture' if report['probes']['P6']['serviceWorker'].get('persistent') is True else 'one_off',
                          'registrationReused': report['probes']['P6']['serviceWorker'].get('reusedRegistration'),
                          'processRestart': 'not_verified'}
                         if isinstance(report['probes']['P6'].get('serviceWorker'), dict)
                         else 'not_verified'),
                     'cachedWorkerRestart': 'not_verified'}
                    for origin, reports in groups.items() for report in reports
                    if isinstance(report['probes'].get('P6'), dict)]
            for label, groups in collections.items()},
    }


class AcceptanceCheckerTests(unittest.TestCase):
    """Checker regressions only; synthetic evidence is never browser evidence."""

    @staticmethod
    def sample(candidate=False, identity='profile-a', origin='http://localhost:8765'):
        h = lambda text: hashlib.sha256(text.encode()).hexdigest()
        key = identity + origin if candidate else 'baseline'
        pixel, png = h('pixels:' + key), h('png:' + key)

        def canvas(p=pixel, e=png, html=True):
            return {'width': 240, 'height': 60, 'pixels1': p, 'pixels2': p,
                    'export1': e if html else None, 'export2': e if html else None,
                    'blobHash1': e, 'blobHash2': e, 'toDataURLAvailable': html,
                    'checks': {'pixelsRepeat': True, 'exportsRepeat': True if html else None,
                               'blobsRepeat': True, 'blobMatchesDataURL': True if html else None}}

        report = {'schema': 1, 'run': 'synthetic-test-only', 'origin': origin, 'probes': {}}
        for path in STATIC_PATHS:
            node = report
            keys = path.split('.')
            for name in keys[:-1]:
                node = node.setdefault(name, {})
            node[keys[-1]] = {'syntheticStableValue': True}
        # A device class the protected policy leaves unchanged (8 cores, 8 GiB).
        report['probes']['P4']['main'].update(hardwareConcurrency=8, deviceMemory=8)
        p6 = report['probes']['P6']
        p6.update(canvas())
        p6['blobHash'] = p6.pop('blobHash1')
        p6.pop('blobHash2')
        p6.update(sourceBefore=pixel, sourceAfter=pixel,
                  offscreenMain=canvas(html=False),
                  parity={'mainOffscreen': True, 'workers': {}}, workers={})
        p6['checks']['sourceCopyUnchanged'] = True
        for worker in WORKERS:
            p6['workers'][worker] = {'canvas': canvas(html=False),
                                     'navigator': {'plugins': {'unsupported': True}}}
            p6['parity']['workers'][worker] = {'pixels': True, 'nestedPixels': None}
        p6['workers']['nestedClassic']['nested'] = {'canvas': canvas(html=False),
                                                          'navigator': {'plugins': {'unsupported': True}}}
        p6['parity']['workers']['nestedClassic']['nestedPixels'] = True
        for kind in ('sharedWorker', 'serviceWorker'):
            p6[kind] = {'canvas': canvas(html=False), 'navigator': {}}
            p6['parity'][kind] = True
        p6['serviceWorker']['cleanup'] = {'ownRegistrationOnly': True, 'unregistered': True}
        observations = {}
        for kind in INHERITED:
            observations[kind] = {'effectiveOrigin': origin, 'own': canvas(),
                                  'parentToChild': canvas(), 'childToParent': canvas(),
                                  'parity': {k: True for k in ('ownPixels', 'ownExport',
                                                             'parentToChildPixels', 'childToParentPixels')}}
        raw = hashlib.sha256(bytes([17, 34, 51, 255]) * 256).hexdigest()
        solid = canvas(h('opaque-solid:' + key) if candidate else raw, h('opaque-solid-png:' + key))
        solid.update(width=16, height=16)
        own = canvas(h('opaque:' + key) if candidate else pixel, h('opaque-png:' + key))
        parent_solid = canvas(h('parent-solid:' + key) if candidate else raw, h('parent-solid-png:' + key))
        parent_solid.update(width=16, height=16)
        observations['opaqueSandboxSrcdoc'] = {
            'reportedOrigin': 'null', 'url': 'about:srcdoc', 'own': own, 'solid': solid,
            'parentSolid': parent_solid, 'rawExpectedSolidPixels': raw,
            'checks': {'originOpaque': True, 'canonicalStable': True, 'solidStable': True,
                       'canonicalExportsStable': True, 'canonicalDistinctFromParent': candidate,
                       'solidDistinctFromParent': candidate, 'rawExpectedNotExposed': candidate}}
        p6['inheritedRealms'] = {'parent': canvas(), 'observations': observations}
        crop = {'fullHash': pixel, 'stitchedHash': pixel, 'pieces': [
            {'fullCropHash': h('piece' + str(i)), 'subrectHash': h('piece' + str(i)),
             'repeatHash': h('piece' + str(i)), 'checks': {'matchesFullCrop': True, 'repeat': True}}
            for i in range(2)], 'checks': {'allSubrectsMatch': True,
                                            'allSubrectsRepeat': True, 'stitchedMatchesFull': True}}
        p6['readRegressions'] = {
            'croppedAndTiled': crop,
            'transparency': {'insideHashes': [pixel, pixel], 'outsideHashes': [pixel, pixel],
                             'checks': {k: True for k in ('alphaMatchesKnownCoverage', 'alphaRepeat',
                                                         'outsideAlphaZero', 'insideTransparentAlphaZero')}},
            'sourceSizeBudget': {'source': {'width': 4097, 'height': 1024, 'pixels': 4097 * 1024},
                                 'read': {'width': 1, 'height': 1},
                                 'actual': {'status': 'exception', 'error': 'NotSupportedError'} if candidate
                                 else {'status': 'completed', 'width': 1, 'height': 1, 'hash': pixel}}}
        report['probes']['P8'] = {'sampleRate': 44100, 'length': 5000, 'channels': 1,
                                  'duration': 5000 / 44100, 'samples4500to4510': [0.125] * 10,
                                  'sumAbsolute4500to5000': 62.5, 'hashes': [h('audio:' + key)] * 4,
                                  'checks': {k: True for k in ('finite', 'getChannelRepeat',
                                                              'copyRepeat', 'getMatchesCopy')}}
        report['probes']['P7'] = {kind: {
            'extensions': ['EXT_example'] + ([] if candidate else [DEBUG_EXTENSION]),
            'unmasked': {'unsupported': True} if candidate else {'vendor': 'native', 'renderer': 'native'},
            'limits': {'MAX_TEXTURE_SIZE': 4096}, 'precision': {}, 'contextAttributes': {},
            'render': {'first': h('shader'), 'second': h('shader'), 'repeat': True, 'error': 0}}
            for kind in ('webgl', 'webgl2')}
        return report

    def validate(self, report, candidate=True):
        checker = Checker()
        try:
            checker.report(report, 'synthetic', candidate)
        except (EvidenceError, TypeError, KeyError, AttributeError, IndexError) as error:
            checker.check(False, 'structure', str(error))
        return checker

    def test_complete_semantic_samples(self):
        for candidate in (False, True):
            checker = self.validate(self.sample(candidate), candidate)
            self.assertTrue(all(c['passed'] for c in checker.checks),
                            [c for c in checker.checks if not c['passed']])

    def test_bad_evidence_fails_even_when_flags_claim_success(self):
        cases = {
            'pixel repeat': ('probes.P6.pixels2', '0' * 64),
            'blob export': ('probes.P6.blobHash', '0' * 64),
            'source mutation': ('probes.P6.sourceAfter', '0' * 64),
            'worker mismatch': ('probes.P6.workers.httpModule.canvas.pixels1', '0' * 64),
            'nested unsupported': ('probes.P6.workers.nestedClassic.nested.canvas', {'unsupported': True}),
            'inherited mismatch': ('probes.P6.inheritedRealms.observations.initialEmpty.own.pixels1', '0' * 64),
            'opaque raw leak': ('probes.P6.inheritedRealms.observations.opaqueSandboxSrcdoc.solid.pixels1',
                               hashlib.sha256(bytes([17, 34, 51, 255]) * 256).hexdigest()),
            'audio copy mismatch': ('probes.P8.hashes', ['0' * 64, '1' * 64, '0' * 64, '0' * 64]),
            'budget wrong error': ('probes.P6.readRegressions.sourceSizeBudget.actual.error', 'RangeError'),
            'budget silently succeeds': ('probes.P6.readRegressions.sourceSizeBudget.actual.status', 'completed'),
            'crop mismatch': ('probes.P6.readRegressions.croppedAndTiled.stitchedHash', '0' * 64),
            'alpha mutation': ('probes.P6.readRegressions.transparency.checks.alphaMatchesKnownCoverage', False),
            'extension inconsistency': ('probes.P7.webgl.extensions', [DEBUG_EXTENSION]),
            'GL error': ('probes.P7.webgl2.render.error', 1282),
            'shared worker error': ('probes.P6.sharedWorker', {'error': 'SecurityError'}),
            'SW raw read': ('probes.P6.serviceWorker.canvas.pixels1', '0' * 64),
        }
        for description, (path, value) in cases.items():
            with self.subTest(description=description):
                report = self.sample(True)
                node = report
                keys = path.split('.')
                for key in keys[:-1]:
                    node = node[key]
                node[keys[-1]] = value
                self.assertTrue(any(not c['passed'] for c in self.validate(report).checks))

    def test_profile_persistence_and_separation(self):
        origin = 'http://localhost:8765'
        a = self.sample(True)
        b = self.sample(True, identity='profile-b')
        for other, same, expected in ((a, True, True), (b, False, True),
                                      (b, True, False), (a, False, False)):
            checker = Checker()
            compare_sets(checker, {origin: [a]}, {origin: [other]}, 'profiles', same)
            self.assertEqual(expected, all(c['passed'] for c in checker.checks))

    def test_persistent_sw_requires_explicit_preservation_and_normal_sw_cleanup(self):
        for candidate in (False, True):
            for reused in (False, True):
                report = self.sample(candidate)
                worker = report['probes']['P6']['serviceWorker']
                worker.update(persistent=True, reusedRegistration=reused,
                              scope='/privacy-probe-sw-cached-v1/',
                              scriptURL=report['origin'] + '/privacy-worker-service.js?fixture_version=1',
                              transport='http-service-worker')
                worker['cleanup'].update(preservedForCachedRestart=True, unregistered=None)
                self.assertTrue(all(c['passed'] for c in self.validate(report, candidate).checks))
                worker['cleanup']['unregistered'] = False
                self.assertTrue(all(c['passed'] for c in self.validate(report, candidate).checks))
                for description, obj, key, bad in (
                    ('retained flag missing', worker['cleanup'], 'preservedForCachedRestart', False),
                    ('actually unregistered', worker['cleanup'], 'unregistered', True),
                    ('wrong scope', worker, 'scope', '/unrelated/'),
                    ('wrong script', worker, 'scriptURL', 'https://unrelated.invalid/worker.js'),
                    ('wrong owner', worker['cleanup'], 'ownRegistrationOnly', False),
                    ('truthy mode is not explicit', worker, 'persistent', 'true'),
                ):
                    with self.subTest(candidate=candidate, reused=reused, case=description):
                        previous = obj[key]
                        obj[key] = bad
                        self.assertTrue(any(not c['passed'] for c in self.validate(report, candidate).checks))
                        obj[key] = previous
        for unregistered in (None, False):
            report = self.sample(True)
            report['probes']['P6']['serviceWorker']['cleanup']['unregistered'] = unregistered
            self.assertTrue(any(not c['passed'] for c in self.validate(report).checks),
                            'Normal one-off failed cleanup must not be exempted')

    def test_static_functionality_differences_fail(self):
        a, b = self.sample(), self.sample(True)
        b['probes']['P4']['main']['userAgent'] = 'unexpected replacement'
        checker = Checker()
        functionality(checker, a, b, 'static')
        self.assertTrue(any(not c['passed'] for c in checker.checks))

    def test_protected_device_class_and_renderer_cohort(self):
        apple = 'ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Max, Unspecified Version)'
        def pair(cores=16, memory=32, protected=(8, 16), unmasked=None):
            a, b = self.sample(), self.sample(True)
            a['probes']['P4']['main'].update(hardwareConcurrency=cores, deviceMemory=memory)
            b['probes']['P4']['main'].update(hardwareConcurrency=protected[0], deviceMemory=protected[1])
            for kind in ('webgl', 'webgl2'):
                a['probes']['P7'][kind]['unmasked'] = {'vendor': 'Google Inc. (Apple)', 'renderer': apple}
                b['probes']['P7'][kind]['unmasked'] = unmasked or {
                    'vendor': 'Google Inc. (Apple)', 'renderer': apple.replace('M4 Max', 'M3')}
            checker = Checker()
            functionality(checker, a, b, 'baselineToCandidate.origin')
            return all(c['passed'] for c in checker.checks)
        self.assertTrue(pair())
        self.assertTrue(pair(cores=8, memory=8, protected=(8, 8)))
        self.assertFalse(pair(protected=(8, 32)), 'deviceMemory above the device class')
        self.assertFalse(pair(protected=(16, 16)), 'unbucketed cores')
        self.assertFalse(pair(unmasked={'unsupported': True}), 'hidden extension on Apple Silicon (pre-v20n)')
        self.assertFalse(pair(unmasked={'vendor': 'Google Inc. (Apple)', 'renderer': apple}), 'real tier exposed')
        self.assertEqual(renderer_cohort(apple.replace('M4 Max', 'M1 Pro')), apple.replace('M4 Max', 'M1'))
        self.assertIsNone(renderer_cohort('ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))'))

    def test_audio_damage_is_not_accepted_as_privacy(self):
        a, b = self.sample(), self.sample(True)
        b['probes']['P8']['samples4500to4510'][0] += 0.01
        checker = Checker()
        functionality(checker, a, b, 'audio')
        self.assertTrue(any(not c['passed'] for c in checker.checks))

    def test_file_directory_mcp_envelopes_and_fail_closed_inputs(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='privacy-checker-unit-') as directory:
            root = pathlib.Path(directory)
            baseline = root / 'baseline.json'
            candidate_dir = root / 'candidate'
            candidate_dir.mkdir()
            baseline.write_text(encode({'report': self.sample()}))
            captured = {'jsonrpc': '2.0', 'result': {'content': [
                {'type': 'text', 'text': encode(self.sample(True))}]}}
            candidate = candidate_dir / 'capture.json'
            candidate.write_text(encode(captured))
            paths = {'baseline': baseline, 'candidate': candidate_dir,
                     'require_persistent_workers': True}
            result = evaluate(paths)
            self.assertEqual('passed', result['status'],
                             [c for c in result['checks'] if not c['passed']])
            candidate.write_text(encode({'jsonrpc': '2.0', 'result': {'isError': True, 'content': []}}))
            self.assertEqual('failed', evaluate(paths)['status'])
            candidate.write_text('{"schema":1,"schema":1}')
            self.assertEqual('failed', evaluate(paths)['status'])
            candidate.write_text('{"schema":1,"probes":{},"bad":1e999}')
            self.assertEqual('failed', evaluate(paths)['status'])
            candidate.unlink()
            self.assertEqual('failed', evaluate(paths)['status'])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('baseline', type=pathlib.Path)
    parser.add_argument('candidate', type=pathlib.Path)
    for flag in ('profile-a', 'profile-b', 'restart', 'otr', 'otr-restart', 'off', 'site-exception'):
        parser.add_argument('--' + flag, type=pathlib.Path)
    parser.add_argument('--require-persistent-workers', action='store_true')
    args = parser.parse_args()
    result = evaluate(vars(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
