"""Native Browser Broker acceptance over authenticated MCP, standard library only.

Explicit opt-in (the browser must already be built and launched by its owner):
  METABROWSER_BROKER_TEST_URL=http://127.0.0.1:PORT/mcp
  METABROWSER_BROKER_TEST_TOKEN=...
  METABROWSER_BROKER_TEST_PROFILE=/temporary/isolated/profile
Optional native prompt clicking (only the explicitly verified fixture process):
  METABROWSER_BROKER_TEST_AUTOAPPROVE=1 METABROWSER_BROKER_TEST_PID=12345
  Build tests/integration/panel_ui.swift as /tmp/metabrowser-panel-ui first.

The profile must contain .browser-broker-fixture-profile with the exact text
browser-broker-fixture-only. This is an operator attestation that the running
browser uses that disposable profile; this suite never launches a browser.
Run: python3 -m unittest discover -s tests/integration -p browser_broker_test.py
"""
import base64
import concurrent.futures
import struct
import json
import os
import pathlib
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

from browser_broker_fixture import BrowserBrokerFixture


class RPCError(AssertionError):
    def __init__(self, error):
        self.error = error
        super().__init__('MCP protocol error: ' + json.dumps(error))


class MCPClient:
    def __init__(self, url, token):
        self.url, self.token = url, token
        self.session = None
        self.next_id = 0
        self.protocol = '2025-03-26'

    def request(self, method, params=None, notification=False):
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        if not notification:
            self.next_id += 1
            payload['id'] = self.next_id
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self.protocol}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        request = urllib.request.Request(self.url, json.dumps(payload).encode(), headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            self.session = response.headers.get('Mcp-Session-Id', self.session)
            raw = response.read().decode()
            content_type = response.headers.get('Content-Type', '')
        if notification:
            return None
        if 'text/event-stream' in content_type:
            messages = []
            for event in raw.replace('\r\n', '\n').split('\n\n'):
                data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
                if data:
                    messages.append(json.loads(data))
            matches = [m for m in messages if m.get('id') == payload['id']]
            if len(matches) != 1:
                raise AssertionError('MCP response ID missing or duplicated')
            result = matches[0]
        else:
            result = json.loads(raw)
        if result.get('jsonrpc') != '2.0' or result.get('id') != payload['id']:
            raise AssertionError('Invalid JSON-RPC response envelope')
        if 'error' in result:
            raise RPCError(result['error'])
        return result['result']

    def initialize(self):
        result = self.request('initialize', {'protocolVersion': self.protocol,
                              'capabilities': {}, 'clientInfo': {
                                  'name': 'browser-broker-acceptance', 'version': '1'}})
        self.protocol = result['protocolVersion']
        self.request('notifications/initialized', notification=True)
        return self.request('tools/list')['tools']

    def call(self, tool_name, **arguments):
        result = self.request('tools/call', {'name': tool_name, 'arguments': arguments})
        self.last_content = result.get('content', [])
        if 'structuredContent' in result:
            body = result['structuredContent']
        else:
            chunks = [c['text'] for c in result.get('content', []) if c.get('type') == 'text']
            if len(chunks) != 1:
                raise AssertionError('Expected one JSON tool result')
            try:
                body = json.loads(chunks[0])
            except json.JSONDecodeError:
                if not result.get('isError'):
                    raise
                body = {'status': 'rejected', 'reason': chunks[0]}
        if not isinstance(body, dict):
            raise AssertionError('Expected object tool result')
        if result.get('isError'):
            body = dict(body, _mcp_error=True)
        self.last_body_bytes = len(chunks[0].encode('utf-8')) if 'structuredContent' not in result else len(json.dumps(body, ensure_ascii=False).encode())
        return body


URL = os.environ.get('METABROWSER_BROKER_TEST_URL')
TOKEN = os.environ.get('METABROWSER_BROKER_TEST_TOKEN')
PROFILE = os.environ.get('METABROWSER_BROKER_TEST_PROFILE')


@unittest.skipUnless(URL and TOKEN and PROFILE, 'requires explicit fixture gateway URL, token and isolated profile')
class BrowserBrokerAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = urllib.parse.urlsplit(URL)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path != '/mcp':
            raise AssertionError('Acceptance gateway must be a loopback HTTP /mcp endpoint')
        marker = pathlib.Path(PROFILE).resolve() / '.browser-broker-fixture-profile'
        if not marker.is_file() or marker.read_text().strip() != 'browser-broker-fixture-only':
            raise AssertionError('Missing fixture-only disposable-profile attestation')
        cls.fixture_pid = os.environ.get('METABROWSER_BROKER_TEST_PID')
        if os.environ.get('METABROWSER_BROKER_TEST_AUTOAPPROVE') == '1':
            if not cls.fixture_pid or not cls.fixture_pid.isdecimal():
                raise AssertionError('Autoapproval requires explicit fixture PID')
            command = subprocess.check_output(['ps', '-p', cls.fixture_pid, '-o', 'command='], text=True)
            if '--user-data-dir=' + str(pathlib.Path(PROFILE).resolve()) not in command:
                raise AssertionError('Fixture PID must use the attested isolated profile')
            if not pathlib.Path('/tmp/metabrowser-panel-ui').is_file():
                raise AssertionError('Build /tmp/metabrowser-panel-ui before enabling autoapproval')
        cls.client = MCPClient(URL, TOKEN)
        cls.tools = {t['name']: t for t in cls.client.initialize()}
        cls.fixture = BrowserBrokerFixture().__enter__()
        cls.addClassCleanup(cls.fixture.__exit__, None, None, None)

    def call(self, tool_name, **args):
        if tool_name in ('browser_navigate', 'browser_execute') and 'document_id' not in args:
            status_args = {'tab_id': args['tab_id']} if 'tab_id' in args else {}
            status = self.client.call('browser_status', **status_args)
            self.assert_success(status)
            args['document_id'] = status['document_id']
        mutation = not self.tools[tool_name].get('annotations', {}).get('readOnlyHint', False)
        if not mutation or os.environ.get('METABROWSER_BROKER_TEST_AUTOAPPROVE') != '1':
            return self.client.call(tool_name, **args)
        stopped = threading.Event()
        failures = []
        def approve():
            try:
                while not stopped.wait(.1):
                    inspected = subprocess.run(['/tmp/metabrowser-panel-ui', self.fixture_pid,
                                                'inspect', '允许本次操作'], capture_output=True, text=True, timeout=3)
                    buttons = []
                    if inspected.returncode == 0:
                        for line in inspected.stdout.splitlines():
                            value = json.loads(line)
                            rows = value if isinstance(value, list) else [value]
                            buttons.extend(row for row in rows if isinstance(row, dict)
                                           and 'AXPress' in row.get('actions', [])
                                           and (row.get('title') == '允许本次操作'
                                                or row.get('description') == '允许本次操作'))
                    if buttons:
                        pressed = subprocess.run(['/tmp/metabrowser-panel-ui', self.fixture_pid,
                                                  'press', '允许本次操作'], capture_output=True, timeout=3)
                        if pressed.returncode:
                            failures.append('Native approval helper failed')
                        return
            except Exception as error:
                failures.append(str(error))
        thread = threading.Thread(target=approve, daemon=True)
        thread.start()
        try:
            return self.client.call(tool_name, **args)
        finally:
            stopped.set()
            thread.join(timeout=7)
            if failures:
                self.fail('; '.join(failures))

    def setUp(self):
        self.tab_id = None
        opened = self.call('browser_tab_open', url=self.fixture.url)
        self.tab_id = opened['tab_id']
        self.addCleanup(self.close_tab)
        self.ready()
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='element',
                                     name='Fixture name', role='textField', timeout_ms=5000))

    def close_tab(self):
        if self.tab_id is not None:
            self.call('browser_tab_close', tab_id=self.tab_id)
            self.tab_id = None

    def ready(self):
        result = self.call('browser_wait', tab_id=self.tab_id, condition='ready', timeout_ms=5000)
        self.assert_success(result)

    def observe(self, **args):
        deadline = time.monotonic() + 5
        while True:
            result = self.call('browser_observe', tab_id=self.tab_id, **args)
            if result.get('status') != 'not_ready' or time.monotonic() >= deadline:
                break
            time.sleep(.1)
        self.assertIn('observation_id', result)
        self.assertIn('coverage', result, 'coverage must be explicit even for empty/partial trees')
        return result

    def node(self, observation, name):
        matches = [n for n in observation['nodes'] if n.get('name') == name]
        controls = [n for n in matches if n.get('role') in ('button', 'textField', 'link')]
        matches = controls or matches
        self.assertEqual(len(matches), 1, name)
        return matches[0]

    def act(self, observation, node, op='click', **args):
        return self.call('browser_act', tab_id=self.tab_id,
                         observation_id=observation['observation_id'], target=node['ref'], op=op, **args)

    def assert_success(self, result):
        self.assertFalse(result.get('_mcp_error'), result)
        self.assertNotIn('error', result)
        if 'status' in result:
            self.assertIn(result['status'], ('completed', 'dispatched', 'local_goal_completed'), result)

    def assert_rejected(self, result):
        self.assertTrue(result.get('_mcp_error') or result.get('error') or
                        result.get('status') in ('rejected', 'handoff_required', 'stale', 'cancelled', 'timeout', 'ambiguous'), result)

    def test_tool_directory_and_authentication(self):
        self.assertTrue({'browser_tabs', 'browser_tab_open', 'browser_tab_close', 'browser_navigate',
                         'browser_observe', 'browser_inspect', 'browser_extract', 'browser_wait',
                         'browser_act', 'browser_execute'} <= self.tools.keys())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            MCPClient(URL, 'invalid-fixture-token').initialize()
        self.assertIn(caught.exception.code, (401, 403))
        caught.exception.close()
        tabs = self.call('browser_tabs')
        self.assertIn(self.tab_id, json.dumps(tabs))

    def test_duplicate_controls_and_consumed_observation(self):
        obs = self.observe()
        nodes = [n for n in obs['nodes'] if n.get('name') == 'Duplicate action' and n.get('role') == 'button']
        self.assertEqual(len(nodes), 2)
        self.assertNotEqual(nodes[0]['ref'], nodes[1]['ref'])
        self.assert_success(self.act(obs, nodes[0]))
        self.assert_rejected(self.act(obs, nodes[1]))

    def test_password_hidden_disabled_and_inspect(self):
        obs = self.observe()
        self.assertNotIn('fixture-password-do-not-expose', json.dumps(obs))
        self.assertFalse(any(n.get('name') == 'Hidden action' for n in obs['nodes']))
        target = self.node(obs, 'Fixture name')
        inspected = self.call('browser_inspect', tab_id=self.tab_id,
                              observation_id=obs['observation_id'], target=target['ref'])
        self.assert_success(inspected)
        disabled = [n for n in obs['nodes'] if n.get('name') == 'Disabled action']
        disabled = [n for n in disabled if n.get('role') == 'button']
        self.assertEqual(len(disabled), 1)
        self.assertTrue(disabled[0]['disabled'])
        self.assert_rejected(self.act(obs, disabled[0]))

    def test_budgets_query_and_tail(self):
        small = self.observe(max_nodes=12, max_bytes=8192)
        self.assertLessEqual(len(small['nodes']), 12)
        self.assertLessEqual(self.client.last_body_bytes, 8192)
        self.assertTrue(small['possibly_truncated'])
        tail = self.observe(query='Tail beyond 512', max_nodes=64, max_bytes=16384)
        self.node(tail, 'Tail beyond 512')
        compact = self.observe(compact=True, max_nodes=12, max_bytes=8192)
        self.assertLessEqual(len(compact['nodes']), 12)

    def test_offscreen_tail_activation_auto_scrolls_and_verifies(self):
        # The target follows 700 rows. No test-side scrolling or action retry:
        # the broker must make the observed target visible and validate its hit.
        observation = self.observe(query='Tail beyond 512', interactive=True)
        target = self.node(observation, 'Tail beyond 512')
        with self.fixture.lock:
            event_start = len(self.fixture.events)
        dispatched = self.act(observation, target)
        self.assert_success(dispatched)
        self.assertEqual(dispatched['status'], 'dispatched')
        self.assertFalse(dispatched['verified'])
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Clicked tail', timeout_ms=5000))
        verified = self.observe(query='Clicked tail')
        self.assertTrue(any(n.get('name') == 'Clicked tail' for n in verified['nodes']))
        # The HTTP event corroborates that the page handler ran exactly once.
        # Its fetch may finish after the AX status update, so wait for evidence
        # without issuing any additional input to the browser.
        deadline = time.monotonic() + 3
        while True:
            with self.fixture.lock:
                clicks = [event for event in self.fixture.events[event_start:]
                          if event.get('clicked') == ['tail']]
            if clicks or time.monotonic() >= deadline:
                break
            time.sleep(.02)
        self.assertEqual(len(clicks), 1)

    def test_delta_requires_explicit_baseline(self):
        before = self.observe()
        baseline = before.get('baseline_id', before['observation_id'])
        self.fixture.trigger('text')
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Delayed fixture complete', timeout_ms=5000))
        delta = self.observe(mode='delta', baseline_id=baseline)
        self.assertIn('Delayed fixture complete', json.dumps(delta))
        self.assertEqual(delta['mode'], 'delta')
        self.assertEqual(delta['baseline_id'], baseline)
        self.assertIsInstance(delta['removed_refs'], list)
        fallback = self.observe(mode='delta', baseline_id='fixture-invalid-baseline')
        self.assertEqual(fallback['mode'], 'semantic')
        self.assertIn('delta_fallback', fallback)
        self.assertNotIn('removed_refs', fallback)

    def test_extract_and_scope(self):
        obs = self.observe()
        for kind, expected in [('text', 'Browser Broker fixture ready'),
                               ('links', 'Fixture destination link'), ('table', 'Apples')]:
            result = self.call('browser_extract', tab_id=self.tab_id,
                               observation_id=obs['observation_id'], kind=kind)
            self.assert_success(result)
            self.assertIsInstance(result['records'], list)
            self.assertTrue(any(expected in r.get('name', '') for r in result['records']))
            self.assertEqual(result['observation_id'], obs['observation_id'])
            self.assertIn('coverage', result)
        scope = self.node(obs, 'Replaceable action')
        scoped = self.call('browser_extract', tab_id=self.tab_id,
                           observation_id=obs['observation_id'], target=scope['ref'], kind='text')
        self.assertTrue(scoped['records'])
        self.assertEqual(scoped['records'][0]['ref'], scope['ref'])
        self.assertTrue(all(r.get('name', '') in ('', 'Replaceable action') for r in scoped['records']))
        self.assertTrue(all(r['role'] in ('button', 'staticText', 'inlineTextBox', 'genericContainer')
                            for r in scoped['records']))
        self.assertEqual(scoped['records'][0]['role'], 'button')
        self.assertEqual(scoped['observation_id'], obs['observation_id'])
        self.assertIn('coverage', scoped)

    def test_frames_have_explicit_coverage(self):
        obs = self.observe(max_nodes=2048, max_bytes=65536)
        frames = obs.get('frames', [])
        self.assertGreaterEqual(len(frames), 3, obs['coverage'])
        frame_text = []
        self.assertEqual({f['origin'] for f in frames}, {self.fixture.url.rstrip('/'), self.fixture.cross_url.rstrip('/')})
        for frame in frames:
            self.assertTrue(frame['available'])
            part = self.observe(frame_id=frame['frame_id'], max_nodes=64, max_bytes=16384)
            frame_text.append(json.dumps(part))
        self.assertIn('same frame marker', '\n'.join(frame_text))
        self.assertIn('cross frame marker', '\n'.join(frame_text))

    def test_replacement_and_navigation_invalidate_refs(self):
        obs = self.observe()
        target = self.node(obs, 'Replaceable action')
        self.fixture.trigger('replace')
        # Waiting for the controller event alone does not prove DOM replacement;
        # use a newly observed document state before testing the old handle.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.observe()
            replacement = self.node(current, 'Replaceable action')
            if replacement['ref'] != target['ref']:
                break
            time.sleep(.05)
        else:
            self.fail('Replacement did not produce a distinct live target')
        self.assert_rejected(self.act(obs, target))
        fresh = self.observe()
        button = self.node(fresh, 'Apply fixture')
        self.assert_success(self.call('browser_navigate', tab_id=self.tab_id, url=self.fixture.url + 'next'))
        self.ready()
        self.assert_rejected(self.act(fresh, button))

    def test_wait_timeout_busy_and_document_cancellation(self):
        start = time.monotonic()
        timeout = self.call('browser_wait', tab_id=self.tab_id, condition='text',
                            text='Never present fixture marker', timeout_ms=200)
        self.assertEqual(timeout['status'], 'timeout')
        self.assertGreaterEqual(timeout['elapsed_ms'], 200)
        self.assertLess(time.monotonic() - start, 3)
        waiter = MCPClient(URL, TOKEN)
        waiter.initialize()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(waiter.call, 'browser_wait', tab_id=self.tab_id,
                                      condition='text', text='Never present fixture marker', timeout_ms=10000)
            time.sleep(.2)
            self.assertFalse(pending.done())
            with self.assertRaises(RPCError) as busy:
                self.call('browser_tabs')
            self.assertEqual(busy.exception.error['code'], -32000)
            self.assertIn('busy', busy.exception.error['message'].lower())
            self.fixture.trigger('navigate')
            cancelled = pending.result(timeout=3)
            self.assertEqual(cancelled['status'], 'stale')

    def test_closed_tab_rejects_observation_and_action(self):
        obs = self.observe()
        target = self.node(obs, 'Apply fixture')
        closed = self.tab_id
        self.close_tab()
        self.assert_rejected(self.call('browser_observe', tab_id=closed))
        self.assert_rejected(self.call('browser_act', tab_id=closed,
                                       observation_id=obs['observation_id'], target=target['ref'], op='click'))

    def test_child_document_invalidates_target(self):
        obs = self.observe(query='Frame action')
        cross = next(f['frame_id'] for f in obs['frames']
                     if f['origin'] == self.fixture.cross_url.rstrip('/'))
        old = next(n for n in obs['nodes'] if n['frame_id'] == cross and n['name'] == 'Frame action')
        main_document = obs['document_id']
        self.fixture.trigger('child_navigate')
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Navigation destination', timeout_ms=5000))
        current = self.observe(query='Destination action')
        self.assertEqual(current['document_id'], main_document)
        self.node(current, 'Destination action')
        self.assertEqual(self.act(obs, old)['status'], 'stale')

    def test_utf8_output_budget(self):
        obs = self.observe(query='多字节', max_bytes=8192)
        self.assertLessEqual(self.client.last_body_bytes, 8192)
        button = next(n for n in obs['nodes'] if n['role'] == 'button')
        self.assertTrue(button['name'].startswith('多字节🙂'))
        self.assertNotIn('\ufffd', button['name'])
        self.assertLessEqual(len(button['name'].encode('utf-8')), 1024)
        self.assertTrue(obs['possibly_truncated'])

    def test_delta_replacement_removed_refs(self):
        before = self.observe(query='Replaceable action')
        old = self.node(before, 'Replaceable action')
        self.fixture.trigger('replace')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            delta = self.observe(query='Replaceable action', mode='delta',
                                 baseline_id=before['observation_id'])
            self.assertEqual(delta['mode'], 'delta')
            if old['ref'] in delta['removed_refs']:
                break
            time.sleep(.05)
        else:
            self.fail('Delta did not report removed replacement target')
        new = self.node(delta, 'Replaceable action')
        self.assertNotEqual(new['ref'], old['ref'])
        rebuilt = {n['ref']: n for n in before['nodes']}
        for ref in delta['removed_refs']:
            rebuilt.pop(ref)
        rebuilt.update({n['ref']: n for n in delta['nodes']})
        full = self.observe(query='Replaceable action')
        self.assertEqual(rebuilt, {n['ref']: n for n in full['nodes']})

    def short_page(self):
        self.assert_success(self.call('browser_navigate', tab_id=self.tab_id,
                                     url=self.fixture.url + 'short'))
        self.ready()
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='element',
                                     name='Fixture name', role='textField', timeout_ms=5000))

    def test_execute_fill_requires_equal_expected_value(self):
        self.short_page()
        result = self.call('browser_execute', tab_id=self.tab_id, steps=[
            {'op': 'fill', 'name': 'Fixture name', 'role': 'textField',
             'text': 'must-not-be-filled', 'expect_text': 'different-value'}])
        self.assert_rejected(result)
        fresh = self.observe(query='Fixture name')
        self.assertEqual(self.node(fresh, 'Fixture name')['value'], '')

    def test_execute_nonfill_existing_postcondition_hands_off(self):
        self.short_page()
        result = self.call('browser_execute', tab_id=self.tab_id, steps=[
            {'op': 'click', 'name': 'Apply fixture', 'role': 'button',
             'expect_text': 'fixture-plan globally already visible'}])
        self.assertEqual(result['status'], 'handoff_required')
        self.assertEqual(result['effects_dispatched'], 0)
        self.assertEqual(result['checks'], [])
        fresh = self.observe(query='Waiting for update')
        self.assertTrue(fresh['nodes'], 'Existing postcondition must not cause a click')
        changed = self.observe(query='Applied ')
        self.assertEqual(changed['nodes'], [])

    def test_unknown_arguments_rejected_without_effect(self):
        for name, arguments in [
            ('browser_observe', {'tab_id': self.tab_id, 'unknown_fixture_argument': True}),
            ('browser_act', {'tab_id': self.tab_id, 'observation_id': 'invalid',
                             'target': 1, 'op': 'click', 'x': 1, 'y': 1}),
            ('browser_execute', {'tab_id': self.tab_id, 'steps': [
                {'op': 'fill', 'name': 'Fixture name', 'role': 'textField',
                 'text': 'unexpected', 'expect_text': 'unexpected', 'unknown': True}]})]:
            with self.subTest(tool=name):
                with self.assertRaises(RPCError) as invalid:
                    self.call(name, **arguments)
                self.assertEqual(invalid.exception.error['code'], -32602)
        fresh = self.observe(query='Fixture name')
        self.assertEqual(self.node(fresh, 'Fixture name')['value'], '')

    def test_fragment_and_normal_navigation_ready(self):
        before = self.observe(query='Fixture name')
        for suffix in ('#section', 'next'):
            destination = self.fixture.url + suffix
            self.assert_success(self.call('browser_navigate', tab_id=self.tab_id, url=destination))
            start = time.monotonic()
            self.ready()
            self.assertLess(time.monotonic() - start, 6)
            status = self.call('browser_status', tab_id=self.tab_id)
            self.assertTrue(status['ready'])
            self.assertEqual(status['url'], destination)
            if suffix.startswith('#'):
                self.assertEqual(status['document_id'], before['document_id'])
            else:
                self.assertNotEqual(status['document_id'], before['document_id'])
        closed = self.tab_id
        self.close_tab()
        self.assertEqual(self.call('browser_wait', tab_id=closed, condition='ready',
                                   timeout_ms=500)['status'], 'stale')

    def test_delta_reorder_and_extract_document_order(self):
        before = self.observe(query='Order ', interactive=True)
        original = [n['ref'] for n in before['nodes']]
        self.assertEqual(len(original), 3)
        self.fixture.trigger('reorder')
        deadline = time.monotonic() + 5
        while True:
            delta = self.observe(query='Order ', interactive=True, mode='delta',
                                 baseline_id=before['observation_id'])
            self.assertEqual(delta['mode'], 'delta')
            if delta['ordered_refs'] != original:
                break
            if time.monotonic() >= deadline:
                self.fail('Existing DOM controls never reordered')
            time.sleep(.1)
        self.assertEqual(delta['removed_refs'], [])
        self.assertEqual(delta['nodes'], [], 'Reordering preserves node identity and attributes')
        self.assertEqual(delta['ordered_refs'], [original[2], original[0], original[1]])
        mapping = {n['ref']: n for n in before['nodes']}
        for ref in delta['removed_refs']:
            mapping.pop(ref)
        mapping.update({n['ref']: n for n in delta['nodes']})
        reconstructed = [mapping[ref] for ref in delta['ordered_refs']]
        current = self.observe(query='Order ', interactive=True)
        self.assertEqual(reconstructed, current['nodes'])
        extracted = self.call('browser_extract', tab_id=self.tab_id,
                              observation_id=current['observation_id'], kind='text')
        self.assertEqual([r['ref'] for r in extracted['records']], delta['ordered_refs'])
        self.assertEqual([r['name'] for r in extracted['records']],
                         ['Order gamma', 'Order alpha', 'Order beta'])

    def test_execute_requires_explicit_tab(self):
        with self.assertRaises(RPCError) as invalid:
            self.client.call('browser_execute', steps=[{'op': 'fill', 'name': 'Fixture name',
                      'role': 'textField', 'text': 'unbound', 'expect_text': 'unbound'}])
        self.assertEqual(invalid.exception.error['code'], -32602)
        fresh = self.observe(query='Fixture name')
        self.assertEqual(self.node(fresh, 'Fixture name')['value'], '')

    def test_mutations_require_current_document(self):
        self.short_page()
        step = {'op': 'fill', 'name': 'Fixture name', 'role': 'textField',
                'text': 'must-not-change', 'expect_text': 'must-not-change'}
        for name, args in [('browser_navigate', {'url': self.fixture.url + 'next'}),
                           ('browser_execute', {'steps': [step]})]:
            with self.subTest(tool=name):
                with self.assertRaises(RPCError) as missing:
                    self.client.call(name, tab_id=self.tab_id, **args)
                self.assertEqual(missing.exception.error['code'], -32602)
                rejected = self.call(name, tab_id=self.tab_id,
                                     document_id='fixture-stale-document', **args)
                self.assertEqual(rejected['status'], 'stale')
        status = self.call('browser_status', tab_id=self.tab_id)
        self.assertEqual(status['url'], self.fixture.url + 'short')
        obs = self.observe(query='Fixture name')
        self.assertEqual(self.node(obs, 'Fixture name')['value'], '')

    def test_same_and_cross_origin_frame_actions(self):
        coverage = self.observe(query='Frame action')
        frames = [f for f in coverage['frames'] if any(
            n['frame_id'] == f['frame_id'] and n.get('role') == 'button'
            and n.get('name') == 'Frame action' for n in coverage['nodes'])]
        self.assertEqual(len(frames), 2)
        for frame in frames:
            obs = self.observe(frame_id=frame['frame_id'], query='Frame action')
            button = self.node(obs, 'Frame action')
            self.assert_success(self.act(obs, button, op='scroll_into_view'))
            fresh = self.observe(frame_id=frame['frame_id'], query='Frame action')
            self.assert_success(self.act(fresh, self.node(fresh, 'Frame action')))
            self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                         text='Frame clicked', timeout_ms=5000))
            verified = self.observe(frame_id=frame['frame_id'], query='Frame clicked')
            self.node(verified, 'Frame clicked')

    def test_overlay_blocks_activation_then_uncovered_action_verifies(self):
        self.short_page()
        self.fixture.trigger('overlay_on')
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Overlay enabled', timeout_ms=5000))
        obs = self.observe(query='Guarded fixture action')
        with self.fixture.lock:
            previous = len(self.fixture.events)
        blocked = self.act(obs, self.node(obs, 'Guarded fixture action'))
        self.assertEqual(blocked['status'], 'rejected')
        self.assertFalse(blocked['verified'])
        with self.fixture.lock:
            self.assertEqual(len(self.fixture.events), previous)
        self.fixture.trigger('overlay_off')
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Overlay disabled', timeout_ms=5000))
        fresh = self.observe(query='Guarded fixture action')
        self.assert_success(self.act(fresh, self.node(fresh, 'Guarded fixture action')))
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Clicked guarded', timeout_ms=5000))

    def test_typed_visual_annotations_exclude_protected_targets(self):
        self.short_page()
        semantic = self.observe(interactive=True)
        protected = [n for n in semantic['nodes'] if n.get('protected')]
        self.assertTrue(protected)
        self.assertTrue(all(n.get('detail_omitted') for n in protected))
        metadata = self.call('browser_observe', tab_id=self.tab_id, mode='visual',
                             annotate=True, observation_id=semantic['observation_id'])
        self.assert_success(metadata)
        content = self.client.last_content
        self.assertEqual([c['type'] for c in content], ['image', 'text'])
        self.assertEqual(content[0]['mimeType'], 'image/png')
        png = base64.b64decode(content[0]['data'], validate=True)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', png[16:24]), (metadata['width'], metadata['height']))
        self.assertNotIn('data', metadata)
        self.assertTrue(metadata['annotated'])
        self.assertEqual(metadata['observation_id'], semantic['observation_id'])
        self.assertEqual(metadata['viewport']['unit'], 'DIP')
        self.assertAlmostEqual(metadata['scale_x'], metadata['width'] / metadata['viewport']['width'])
        self.assertAlmostEqual(metadata['scale_y'], metadata['height'] / metadata['viewport']['height'])
        eligible = {n['ref'] for n in semantic['nodes']
                    if not n.get('protected') and not n.get('detail_omitted')}
        self.assertTrue(metadata['annotations'])
        self.assertLessEqual(len(metadata['annotations']), metadata['annotation_limit'])
        for mark in metadata['annotations']:
            self.assertIn(mark['ref'], eligible)
            self.assertGreater(mark['width'], 0)
            self.assertGreater(mark['height'], 0)
            self.assertGreaterEqual(mark['x'], 0)
            self.assertGreaterEqual(mark['y'], 0)
            self.assertLessEqual(mark['x'] + mark['width'], metadata['width'])
            self.assertLessEqual(mark['y'] + mark['height'], metadata['height'])
        self.assertEqual(self.call('browser_observe', tab_id=self.tab_id, mode='visual',
                                  annotate=True, observation_id='invalid-fixture-observation')['status'], 'stale')

    def test_annotation_geometry_matches_independent_dom_report(self):
        # A unique fixture URL prevents reports from previous tabs/documents
        # from satisfying the geometry checks. No renderer/debugger API is used.
        url = self.fixture.url + 'short?geometry=' + uuid.uuid4().hex
        self.assert_success(self.call('browser_navigate', tab_id=self.tab_id, url=url))
        self.ready()
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='element',
                                     name='Guarded fixture action', role='button', timeout_ms=5000))

        def geometry(after):
            deadline = time.monotonic() + 5
            while True:
                with self.fixture.lock:
                    reports = [r.copy() for r in self.fixture.geometry_reports
                               if r['url'] == url and r['received_at'] > after]
                if len(reports) >= 2:
                    previous, current = reports[-2:]
                    fields = ('x', 'y', 'width', 'height', 'innerWidth', 'innerHeight',
                              'scrollX', 'scrollY', 'devicePixelRatio')
                    if all(previous[k] == current[k] for k in fields):
                        self.assertGreater(current['sequence'], previous['sequence'])
                        self.assertLess(time.monotonic() - current['received_at'], 1)
                        return current
                if time.monotonic() >= deadline:
                    self.fail('No recent stable fixture DOM geometry report')
                time.sleep(.02)

        before = geometry(time.monotonic())
        semantic = self.observe(query='Guarded fixture action', interactive=True)
        target = self.node(semantic, 'Guarded fixture action')
        capture_started = time.monotonic()
        metadata = self.call('browser_observe', tab_id=self.tab_id, mode='visual',
                             annotate=True, observation_id=semantic['observation_id'])
        self.assert_success(metadata)
        after = geometry(time.monotonic())
        self.assertLess(before['received_at'], capture_started)
        for field in ('x', 'y', 'width', 'height', 'innerWidth', 'innerHeight',
                      'scrollX', 'scrollY', 'devicePixelRatio'):
            self.assertEqual(before[field], after[field], 'Geometry changed during capture: ' + field)
        annotations = [a for a in metadata['annotations'] if a['ref'] == target['ref']]
        self.assertEqual(len(annotations), 1)
        mark = annotations[0]
        self.assertGreater(before['innerWidth'], 0)
        self.assertGreater(before['innerHeight'], 0)
        # Require the control fully within the viewport; clipping would change
        # the comparison and could conceal an origin/conversion error.
        self.assertGreaterEqual(before['x'], 0)
        self.assertGreaterEqual(before['y'], 0)
        self.assertLessEqual(before['x'] + before['width'], before['innerWidth'])
        self.assertLessEqual(before['y'] + before['height'], before['innerHeight'])
        sx = metadata['width'] / before['innerWidth']
        sy = metadata['height'] / before['innerHeight']
        for field, scale in (('x', sx), ('y', sy), ('width', sx), ('height', sy)):
            self.assertAlmostEqual(mark[field], before[field] * scale, delta=2,
                                   msg='Annotation differs from independent DOM ' + field)

    def test_execute_reconciles_preparatory_scroll_after_covered_tail_rejection(self):
        self.assert_success(self.call('browser_navigate', tab_id=self.tab_id,
                                     url=self.fixture.url + 'covered-tail'))
        self.ready()
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='element',
                                     name='Covered offscreen tail action', role='button', timeout_ms=5000))
        before = self.observe(max_nodes=2048, max_bytes=65536)
        self.assertFalse(before['possibly_truncated'])
        self.assertLess(len(before['nodes']), 64)
        self.node(before, 'Covered offscreen tail action')
        self.assertFalse(any('Covered tail activated' in n.get('name', '')
                             or 'Covered tail activated' in n.get('value', '')
                             for n in before['nodes']))
        with self.fixture.lock:
            event_start = len(self.fixture.events)
        # One execution and one activation attempt. Product preparation must
        # scroll, then reject the overlay without dispatching the activation.
        result = self.call('browser_execute', tab_id=self.tab_id, steps=[{
            'op': 'click', 'name': 'Covered offscreen tail action', 'role': 'button',
            'expect_text': 'Covered tail activated'}])
        self.assert_rejected(result)
        self.assertEqual(result['status'], 'handoff_required')
        self.assertEqual(result['effects_dispatched'], 0)
        self.assertEqual(result['preparatory_scrolls_dispatched'], 1)
        self.assertTrue(result['needs_reconciliation'])
        self.assertEqual(result['checks'], [])
        action = result['last_action']
        self.assertIsInstance(action, dict)
        self.assertEqual(action['status'], 'rejected')
        self.assertTrue(action['preparatory_scroll_dispatched'])
        self.assertFalse(action['activation_dispatched'])
        self.assertFalse(action['verified'])
        fresh = self.observe(query='No tail activation')
        self.assertTrue(fresh['nodes'])
        with self.fixture.lock:
            self.assertFalse(any(e.get('clicked') == ['covered-tail']
                                 for e in self.fixture.events[event_start:]))

    def test_execute_and_delayed_wait(self):
        self.assert_success(self.call('browser_navigate', tab_id=self.tab_id, url=self.fixture.url + 'short'))
        self.ready()
        executed = self.call('browser_execute', tab_id=self.tab_id, steps=[
            {'op': 'fill', 'name': 'Fixture name', 'role': 'textField', 'text': 'fixture-plan', 'expect_text': 'fixture-plan'},
            {'op': 'click', 'name': 'Apply fixture', 'role': 'button', 'expect_text': 'Applied fixture-plan'}])
        self.assert_success(executed)
        self.assertEqual(executed['status'], 'local_goal_completed')
        self.assertEqual(executed['effects_dispatched'], 2)
        self.assertEqual(len(executed['checks']), 2)
        fresh = self.observe(query='Fixture name')
        self.assertEqual(self.node(fresh, 'Fixture name')['value'], 'fixture-plan')
        self.fixture.trigger('text', delay_ms=150)
        self.assert_success(self.call('browser_wait', tab_id=self.tab_id, condition='text',
                                     text='Delayed fixture complete', timeout_ms=5000))


if __name__ == '__main__':
    unittest.main()
