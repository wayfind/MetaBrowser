"""Real plugin/SDK browser TOOL image wire contract; loopback provider only.

Run from any directory: python3 tests/integration/browser_visual_provider_test.py -v
Uses zig-out/lib/libmetabrowser_metacodes.dylib unless the explicit environment
METABROWSER_VISUAL_TEST_PLUGIN overrides it. Never launches a browser or model.
Host response buffers use libc malloc; ownership transfers to the plugin, whose
release callback frees them. Callback objects remain alive through destroy.
"""
import base64
import ctypes as C
import http.server
import json
import os
import pathlib
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB5kAAAAASUVORK5CYII='
EVENT = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint64)
REQUEST = C.CFUNCTYPE(C.c_uint32, C.c_void_p, C.c_uint32, C.c_char_p,
                    C.c_void_p, C.c_uint64, C.POINTER(C.c_void_p), C.POINTER(C.c_uint64))


class Config(C.Structure):
    _fields_ = [('size', C.c_uint32), ('abi', C.c_uint32), ('endpoint', C.c_char_p),
                ('model', C.c_char_p), ('key', C.c_char_p), ('workspace', C.c_char_p),
                ('event', EVENT), ('context', C.c_void_p), ('provider', C.c_uint32),
                ('protocol', C.c_uint32), ('shell', C.c_uint32), ('turns', C.c_uint32),
                ('request', REQUEST), ('home', C.c_char_p), ('checkpoint', C.c_char_p)]


def text_fields(value):
    """Only ordinary provider text, never image_url's native data URI."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'image_url':
                continue
            if key in ('text', 'content') and isinstance(child, str):
                yield child
            else:
                yield from text_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from text_fields(child)


def image_urls(value):
    if isinstance(value, dict):
        if value.get('type') == 'image_url':
            yield value['image_url']['url']
        for child in value.values():
            yield from image_urls(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_urls(child)


class BrowserVisualProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('METABROWSER_VISUAL_TEST_PLUGIN',
                              str(ROOT / 'zig-out/lib/libmetabrowser_metacodes.dylib'))
        cls.lib = C.CDLL(path)
        cls.lib.mb_mc_create.argtypes = [C.POINTER(Config)]
        cls.lib.mb_mc_create.restype = C.c_void_p
        cls.lib.mb_mc_run_input.argtypes = [C.c_void_p, C.c_uint64, C.c_char_p]
        cls.lib.mb_mc_run_input.restype = C.c_uint32
        cls.lib.mb_mc_destroy.argtypes = [C.c_void_p]
        cls.lib.mb_mc_destroy.restype = None
        cls.libc = C.CDLL(None)
        cls.libc.malloc.argtypes = [C.c_size_t]
        cls.libc.malloc.restype = C.c_void_p

    def setUp(self):
        self.requests, self.events, self.calls, self.failures = [], [], [], []
        self.probes = []
        self.response = self.valid_image()
        test = self

        class Provider(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                test.probes.append(self.path)
                if self.path != '/v1/models':
                    self.send_error(404)
                    return
                self.send_json({'data': [{'id': 'gpt-4.1-mini', 'capabilities': {
                    'image_input': {'supported': True}}}]})

            def send_json(self, value):
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                try:
                    if self.path != '/v1/chat/completions':
                        raise AssertionError('Unexpected provider path ' + self.path)
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    test.requests.append(body)
                    if body['model'] != 'gpt-4.1-mini':
                        raise AssertionError('Unexpected model')
                    # A synthetic image-result user message is deliberately not
                    # used as a turn boundary: the input prompt is text only.
                    users = [i for i, m in enumerate(body['messages'])
                             if m['role'] == 'user' and m.get('content') == 'visual-tool-fixture']
                    if not users:
                        raise AssertionError('Missing original text-only input')
                    tools = [m for m in body['messages'][users[-1] + 1:] if m['role'] == 'tool']
                    if tools:
                        delta, finish = {'content': 'visual-tool-wire-complete'}, 'stop'
                    else:
                        delta = {'tool_calls': [{'index': 0, 'id': 'fixture-visual-call',
                            'type': 'function', 'function': {'name': 'browser_observe',
                            'arguments': '{"mode":"visual"}'}}]}
                        finish = 'tool_calls'
                    chunks = [{'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                              {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}]
                    payload = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks)
                    data = (payload + 'data: [DONE]\n\n').encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as error:
                    test.failures.append(repr(error))
                    self.send_error(500)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.directory = tempfile.TemporaryDirectory(prefix='metabrowser-visual-provider-')
        self.addCleanup(self.directory.cleanup)

        @EVENT
        def event(_, kind, data, size):
            try:
                self.events.append((kind, C.string_at(data, size).decode('utf-8')))
            except Exception as error:
                self.failures.append(repr(error))

        @REQUEST
        def request(_, kind, name, data, size, output, length):
            # Every callback, including rejection paths, initializes ownership.
            output[0], length[0] = None, 0
            try:
                arguments = json.loads(C.string_at(data, size))
                if kind != 1 or name.decode() != 'browser_observe':
                    raise AssertionError('Unexpected host/UI callback')
                self.calls.append(arguments)
                if arguments != {'mode': 'visual'}:
                    raise AssertionError('Unexpected observation arguments')
                payload = json.dumps(self.response, ensure_ascii=False).encode('utf-8')
                pointer = self.libc.malloc(len(payload))
                if not pointer:
                    raise MemoryError('Fixture malloc failed')
                C.memmove(pointer, payload, len(payload))
                output[0], length[0] = pointer, len(payload)
                # Do not free here: ownership passes to plugin execute/release.
                return 0
            except Exception as error:
                self.failures.append(repr(error))
                return 2

        self.event_callback, self.request_callback = event, request
        work = self.directory.name.encode()
        self.config = Config(C.sizeof(Config), 2,
            ('http://127.0.0.1:%d/v1/chat/completions' % self.server.server_port).encode(),
            b'gpt-4.1-mini', b'local-fixture-only', work, event, None, 2, 0, 2, 4,
            request, work, None)
        self.session = self.lib.mb_mc_create(C.byref(self.config))
        self.assertTrue(self.session, self.events)
        self.addCleanup(self.lib.mb_mc_destroy, self.session)
        self.run_id = 0

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @staticmethod
    def valid_image():
        return {'type': 'image', 'media_type': 'image/png', 'data': PNG,
                'tab_id': 'fixture-tab', 'document_id': 'fixture-document',
                'observation_id': 'fixture-observation', 'width': 1, 'height': 1,
                'scale': 1.0, 'scale_x': 1.0, 'scale_y': 1.0,
                'viewport': {'width': 1, 'height': 1, 'unit': 'DIP'},
                'coordinate_space': 'viewport image; not an authorized coordinate target',
                'annotated': True, 'annotations': [{'ref': 17, 'x': 0, 'y': 0,
                                                  'width': 1, 'height': 1}]}

    def run_turn(self):
        start, calls = len(self.requests), len(self.calls)
        self.run_id += 1
        status = self.lib.mb_mc_run_input(self.session, self.run_id,
                                         b'{"text":"visual-tool-fixture"}')
        self.assertFalse(self.failures, self.failures)
        self.assertEqual(status, 0, self.events)
        self.assertEqual(len(self.calls) - calls, 1)
        requests = self.requests[start:]
        self.assertEqual(len(requests), 2, 'Exactly one tool call and one completion expected')
        self.assertEqual(list(image_urls(requests[0]['messages'])), [], 'Input must be text-only')
        return requests[1]

    def assert_native_image_and_metadata(self, request):
        urls = list(image_urls(request['messages']))
        self.assertEqual(urls, ['data:image/png;base64,' + PNG])
        self.assertEqual(base64.b64decode(urls[0].split(',', 1)[1], validate=True),
                         base64.b64decode(PNG))
        ordinary = list(text_fields(request['messages']))
        for text in ordinary:
            self.assertNotIn(PNG, text)
            self.assertNotIn('data:image/', text)
        expected = {k: v for k, v in self.valid_image().items()
                    if k not in ('type', 'media_type', 'data')}
        metadata = []
        for text in ordinary:
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get('observation_id') == 'fixture-observation':
                metadata.append(value)
        self.assertEqual(metadata, [expected], 'Image provenance must survive as ordinary JSON text')

    def test_tool_image_native_wire_and_flat_metadata(self):
        self.assert_native_image_and_metadata(self.run_turn())

    def test_invalid_mime_rejected_without_payload_leak(self):
        self.assert_rejected_image({'media_type': 'text/html'}, 'text/html')

    def test_invalid_base64_rejected_without_payload_leak(self):
        self.assert_rejected_image({'data': 'fixture-invalid-base64!'}, 'fixture-invalid-base64!')

    def test_oversized_metadata_rejected_without_payload_leak(self):
        marker = 'fixture-oversized-metadata-'
        self.assert_rejected_image({'fixture_extra': marker * 1500}, marker)

    def test_oversized_image_rejected_without_payload_leak(self):
        marker = base64.b64encode(b'fixture-image-byte-' * 180000).decode()
        self.assert_rejected_image({'data': marker}, marker[:128])

    def assert_rejected_image(self, overrides, forbidden):
        self.response.update(overrides)
        request = self.run_turn()
        self.assertEqual(list(image_urls(request['messages'])), [])
        ordinary = list(text_fields(request['messages']))
        for text in ordinary:
            self.assertNotIn(forbidden, text)
            self.assertNotIn(PNG, text)
        errors = [m for m in request['messages'] if m.get('role') == 'tool']
        self.assertTrue(errors)
        self.assertTrue(any('reject' in str(m.get('content', '')).lower()
                            or 'invalid' in str(m.get('content', '')).lower() for m in errors),
                        'Rejected images need explicit tool error evidence')
        # Reuse the same native session: failure must not poison it or leave a
        # dangling host-result buffer. A fresh tool image must still traverse it.
        self.response = self.valid_image()
        self.assert_native_image_and_metadata(self.run_turn())


if __name__ == '__main__':
    unittest.main()
