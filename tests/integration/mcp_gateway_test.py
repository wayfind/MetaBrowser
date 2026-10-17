"""Contract tests against the actual packaged native gateway (never a mock server).

Run after the main agent builds/launches an isolated native test profile:
  METABROWSER_MCP_TEST_URL=http://127.0.0.1:PORT/mcp \
  METABROWSER_MCP_TEST_TOKEN=... METABROWSER_MCP_TEST_ISOLATED=1 \
  python3 tests/integration/mcp_gateway_test.py -v

No build, browser launch, provider/model calls, CDP, or main-profile access occurs.
Mutations must require native approval, which this test deliberately never grants.
"""
import base64
import concurrent.futures
import http.client
import http.server
import json
import os
import pathlib
import select
import threading
import time
import unittest
import urllib.parse


class Client:
    def __init__(self, url, token):
        self.url = urllib.parse.urlsplit(url)
        self.token = token
        self.session = None
        self.sequence = 0

    def http(self, body=None, method="POST", headers=None, token=None, timeout=8, raw=None):
        connection = http.client.HTTPConnection(self.url.hostname, self.url.port, timeout=timeout)
        request_headers = {
            "Authorization": "Bearer " + (self.token if token is None else token),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        if self.session:
            request_headers["Mcp-Session-Id"] = self.session
        request_headers.update(headers or {})
        try:
            connection.request(method, self.url.path,
                               raw if raw is not None else json.dumps(body) if body is not None else None,
                               request_headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, dict((k.lower(), v) for k, v in response.getheaders()), json.loads(data) if data else None
        finally:
            connection.close()

    def rpc(self, method, params=None, request_id=None, **kwargs):
        self.sequence += 1
        request_id = self.sequence if request_id is None else request_id
        body = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        return self.http(body, **kwargs)

    def notify(self, method, params=None):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        return self.http(body)

    def initialize(self):
        status, headers, body = self.rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "native-gateway-contract", "version": "1"},
        })
        assert status == 200, (status, body)
        assert body["result"]["protocolVersion"] == "2025-03-26", body
        assert body["result"]["capabilities"] == {"tools": {"listChanged": False}}, body
        self.session = headers["mcp-session-id"]
        assert len(self.session) >= 32
        assert self.notify("notifications/initialized")[0] == 202
        return self

    def call(self, name, arguments=None, **kwargs):
        return self.rpc("tools/call", {"name": name, "arguments": arguments or {}}, **kwargs)


class Fixture(http.server.BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).hits += 1
        payload = b"<!doctype html><title>MCP must not open without approval</title>fixture"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class GatewayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get("METABROWSER_MCP_TEST_URL")
        cls.token = os.environ.get("METABROWSER_MCP_TEST_TOKEN")
        if not cls.url or not cls.token:
            raise unittest.SkipTest("packaged native gateway URL/token not supplied")
        if os.environ.get("METABROWSER_MCP_TEST_ISOLATED") != "1":
            raise RuntimeError("explicit isolated test profile attestation required")
        parsed = urllib.parse.urlsplit(cls.url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path != "/mcp" or parsed.query or parsed.fragment or parsed.username:
            raise RuntimeError("expected explicit http://127.0.0.1:PORT/mcp")
        if len(cls.token) < 32:
            raise RuntimeError("test gateway bearer must have at least 32 characters")

    @unittest.skipUnless(os.environ.get("METABROWSER_MCP_TEST_DEADLINE") == "1",
                         "opt in to the real 60-second native approval deadline")
    def test_native_approval_deadline(self):
        client = Client(self.url, self.token).initialize()
        try:
            started = time.monotonic()
            status, _, result = client.call(
                "browser_tab_open", {"url": "http://127.0.0.1:9/must-not-navigate"}, timeout=70)
            self.assertEqual(status, 200)
            self.assertTrue(result["result"]["isError"], result)
            error = json.loads(result["result"]["content"][0]["text"])
            self.assertEqual(error["status"], "timeout")
            self.assertEqual(error["outcome"], "unconfirmed")
            self.assertIn("deadline exceeded", error["reason"])
            self.assertGreaterEqual(time.monotonic() - started, 59)
            deadline = time.monotonic() + 5
            while True:
                _, _, after = client.call("browser_tabs")
                if "result" in after or time.monotonic() >= deadline:
                    break
                self.assertEqual(after["error"]["code"], -32000)
                time.sleep(0.05)
            self.assertFalse(after["result"]["isError"], after)
        finally:
            client.http(method="DELETE")

    def test_keepalive_completion_and_disconnect_ownership(self):
        owner = Client(self.url, self.token).initialize()
        observer = Client(self.url, self.token).initialize()
        connection = http.client.HTTPConnection(owner.url.hostname, owner.url.port, timeout=8)
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "Mcp-Session-Id": owner.session}

        def send(tool, arguments, request_id):
            connection.request("POST", "/mcp", json.dumps({"jsonrpc": "2.0", "id": request_id,
                               "method": "tools/call", "params": {"name": tool, "arguments": arguments}}), headers)

        def wait_lane(busy):
            deadline = time.monotonic() + 5
            while True:
                _, _, response = observer.call("browser_tabs")
                is_busy = response.get("error", {}).get("code") == -32000
                if is_busy == busy:
                    return response
                self.assertLess(time.monotonic(), deadline, "native direct lane did not settle")
                time.sleep(0.02)

        try:
            # Multiple completed calls on the same persistent HTTP connection
            # must retire their pending request before the next request arrives.
            for request_id in ("completed-one", "completed-two"):
                send("browser_tabs", {}, request_id)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertEqual(result["id"], request_id)
                self.assertFalse(result["result"]["isError"], result)
            tabs = json.loads(result["result"]["content"][0]["text"])["tabs"]
            active = next(tab for tab in tabs if tab["active"])
            _, _, status_result = owner.call("browser_status", {"tab_id": active["tab_id"]})
            self.assertFalse(status_result["result"]["isError"], status_result)
            document_id = json.loads(status_result["result"]["content"][0]["text"])["document_id"]
            # A valid nested array reaches the same native mutation approval lane.
            send("browser_execute", {"tab_id": active["tab_id"], "document_id": document_id, "steps": [{
                "name": "__mcp_never_approve__", "role": "button", "op": "click",
                "expect_text": "__mcp_no_effect_expected__"}]}, "owned-execute")
            wait_lane(True)
            self.assertFalse(select.select([connection.sock], [], [], 0.2)[0],
                             "execute returned before native approval")
            self.assertEqual(owner.notify("notifications/cancelled", {"requestId": "completed-two"})[0], 202)
            self.assertFalse(select.select([connection.sock], [], [], 0.2)[0],
                             "a completed request ID cancelled the next request")
            owner.notify("notifications/cancelled", {"requestId": "owned-execute"})
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(result["id"], "owned-execute")
            self.assertTrue(result["result"]["isError"])
            self.assertEqual(json.loads(result["result"]["content"][0]["text"])["status"], "cancelled")
            wait_lane(False)
            # Closing a connection after its replied request is harmless.
            connection.close()
            self.assertFalse(wait_lane(False)["result"]["isError"])
            # Closing the connection of a genuinely pending approval cancels
            # only that direct request and must release the lane after cleanup.
            send("browser_tab_open", {"url": "http://127.0.0.1:9/must-not-navigate"}, "disconnect-owned")
            wait_lane(True)
            connection.close()
            self.assertFalse(wait_lane(False)["result"]["isError"])
        finally:
            connection.close()
            for client in (owner, observer):
                client.http(method="DELETE")

    def test_native_image_content(self):
        client = Client(self.url, self.token).initialize()
        try:
            _, _, response = client.call("browser_tabs")
            self.assertFalse(response["result"]["isError"], response)
            tabs = json.loads(response["result"]["content"][0]["text"])["tabs"]
            active = next((tab for tab in tabs if tab["active"]), None)
            if not active or urllib.parse.urlsplit(active["url"]).scheme not in ("http", "https"):
                self.skipTest("main agent must stage a visible isolated HTTP fixture for screenshot coverage")
            status, _, response = client.call("browser_observe", {"tab_id": active["tab_id"], "mode": "visual"})
            self.assertEqual(status, 200)
            self.assertFalse(response["result"]["isError"], response)
            content = response["result"]["content"]
            image = next(part for part in content if part["type"] == "image")
            self.assertEqual(image["mimeType"], "image/png")
            decoded = base64.b64decode(image["data"], validate=True)
            self.assertTrue(decoded.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertLessEqual(len(decoded), 3 * 1024 * 1024)
            metadata = json.loads(next(part["text"] for part in content if part["type"] == "text"))
            self.assertNotIn("data", metadata)
            self.assertEqual(metadata["tab_id"], active["tab_id"])
            self.assertTrue(metadata["document_id"])
            self.assertGreater(metadata["width"], 0)
            self.assertGreater(metadata["height"], 0)
            self.assertLessEqual(len(json.dumps(response).encode()), 5 * 1024 * 1024)
            if os.environ.get("METABROWSER_MCP_TEST_LARGE_IMAGE") == "1":
                self.assertGreater(len(image["data"]), 1024 * 1024,
                                   "stage a noisy fixture so image regression exceeds the old 1 MiB bound")
        finally:
            client.http(method="DELETE")

    def test_official_python_client(self):
        # Target the official MCP 2.3 API. Missing dependencies or removed SDK
        # symbols are test errors, never silently reported as skipped coverage.
        import asyncio
        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        async def verify():
            async with create_mcp_http_client(
                    headers={"Authorization": "Bearer " + self.token}) as http:
                async with streamable_http_client(self.url, http_client=http) as transport:
                    async with ClientSession(transport[0], transport[1]) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.protocol_version, "2025-03-26")
                        catalog = await session.list_tools()
                        self.assertIn("browser_tabs", {tool.name for tool in catalog.tools})
                        self.assertEqual(len(catalog.tools), 12)
                        result = await session.call_tool("browser_tabs", {})
                        self.assertFalse(result.is_error, result)
                        self.assertIsInstance(json.loads(result.content[0].text)["tabs"], list)

        asyncio.run(verify())

    def test_packaged_gateway(self):
        a = Client(self.url, self.token)
        self.assertEqual(a.rpc("ping", token="invalid")[0], 401)
        self.assertEqual(a.rpc("ping", headers={"Origin": "http://evil.invalid"})[0], 403)
        self.assertEqual(a.rpc("ping", headers={"Host": "evil.invalid"})[0], 403)
        self.assertEqual(a.rpc("ping")[0], 400)
        self.assertEqual(a.http([], headers={"Host": "127.0.0.1:" + str(a.url.port)})[2]["error"]["code"], -32600)
        self.assertEqual(a.http(raw="{")[2]["error"]["code"], -32700)
        self.assertEqual(a.http(raw="null")[2]["error"]["code"], -32600)
        self.assertEqual(a.rpc("ping", headers={"Content-Type": "application/json-evil"})[0], 400)
        self.assertEqual(a.rpc("ping", headers={"Accept": "text/plain"})[0], 406)
        self.assertEqual(a.rpc("ping", headers={"Accept": "application/json-evil, text/event-stream"})[0], 406)
        self.assertEqual(a.rpc("ping", headers={"Accept": "application/json;q=0, text/event-stream"})[0], 406)
        self.assertEqual(a.http(raw=" " * (128 * 1024 + 1))[0], 400)
        a.initialize()
        b = Client(self.url, self.token).initialize()
        self.assertNotEqual(a.session, b.session)
        try:
            self.assertEqual(a.http(method="GET")[0], 405)
            self.assertEqual(a.http({"jsonrpc": "2.0", "method": "notifications/ignored", "params": []})[::2], (202, None))
            self.assertEqual(a.rpc("ping", headers={"MCP-Protocol-Version": "invalid"})[0], 400)
            status, _, body = a.rpc("tools/list", {})
            self.assertEqual(status, 200)
            tools = {tool["name"]: tool for tool in body["result"]["tools"]}
            self.assertTrue({"browser_tabs", "browser_status", "browser_observe", "browser_tab_open"} <= tools.keys())
            native_catalog = (pathlib.Path(__file__).resolve().parents[2] /
                              "chromium/metabrowser/browser_tool_catalog.inc").read_text()
            expected = json.loads(native_catalog.split('R"MBTOOLS(', 1)[1].rsplit(')MBTOOLS"', 1)[0])
            self.assertEqual(body["result"]["tools"], expected,
                             "MCP must expose the entire unchanged native catalogue")
            self.assertTrue({"browser_execute", "browser_inspect", "browser_extract", "browser_wait"} <= tools.keys())
            for tool in tools.values():
                schema = tool["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
            status, _, result = a.call("browser_tabs")
            self.assertEqual(status, 200)
            self.assertFalse(result["result"]["isError"], result)
            baseline = json.loads(result["result"]["content"][0]["text"])["tabs"]
            self.assertIsInstance(baseline, list)
            active_id = next(tab["tab_id"] for tab in baseline if tab["active"])
            _, _, page_status = a.call("browser_status", {"tab_id": active_id})
            self.assertFalse(page_status["result"]["isError"], page_status)
            page_identity = json.loads(page_status["result"]["content"][0]["text"])
            self.assertEqual(page_identity["tab_id"], active_id)
            binding = {"tab_id": active_id, "document_id": page_identity["document_id"]}
            valid_step = {"name": "fixture", "role": "button", "op": "click", "expect_text": "fixture"}
            for name, args in [("browser_execute", {}),
                               ("browser_navigate", {"url": "http://127.0.0.1:9/must-not-navigate"}),
                               ("browser_execute", {"steps": [valid_step]}),
                               ("browser_execute", {"tab_id": active_id, "steps": [valid_step]}),
                               ("browser_navigate", {"tab_id": active_id, "url": "http://127.0.0.1:9/must-not-navigate"}),
                               ("browser_navigate", {"document_id": binding["document_id"], "url": "http://127.0.0.1:9/must-not-navigate"}),
                               ("browser_execute", {**binding, "steps": []}),
                               ("browser_execute", {**binding, "steps": [valid_step] * 13}),
                               ("browser_execute", {**binding, "steps": [dict(valid_step, expect_text=1)]}),
                               ("browser_execute", {**binding, "steps": [dict(valid_step, script="1")]}),
                               ("browser_execute", {**binding, "steps": [dict(valid_step, expect_text="")]}),
                               ("browser_execute", {**binding, "steps": ["not an object"]}),
                               ("browser_wait", {"condition": "ready", "timeout_ms": 10001}),
                               ("browser_observe", {"max_nodes": 2049}),
                               ("browser_extract", {"observation_id": "stale", "kind": "cookies"}),
                               ("browser_eval", {"script": "1"}),
                               ("browser_tabs", {"profile": "/tmp/no"}),
                               ("browser_tab_open", {}), ("browser_tab_open", {"url": 123}),
                               ("browser_act", {"observation_id": "stale", "target": "bad", "op": "click"})]:
                with self.subTest(tool=name, args=args):
                    self.assertEqual(a.call(name, args)[2]["error"]["code"], -32602)
            fixture = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
            Fixture.hits = 0
            thread = threading.Thread(target=fixture.serve_forever, daemon=True)
            thread.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(a.call, "browser_tab_open",
                                          {"url": f"http://127.0.0.1:{fixture.server_port}/approval-fixture"},
                                          request_id="approval-owned", timeout=12)
                    # Native approval must remain pending without an answer. This
                    # is a bounded observation window, not a fake approval event.
                    deadline = time.monotonic() + 5
                    while True:
                        self.assertFalse(pending.done(), "mutation completed without native approval")
                        _, _, lane = b.call("browser_tabs")
                        if lane.get("error", {}).get("code") == -32000:
                            break
                        self.assertLess(time.monotonic(), deadline, "direct tool lane never acquired")
                        time.sleep(0.02)
                    with self.assertRaises(concurrent.futures.TimeoutError):
                        pending.result(timeout=0.2)
                    self.assertEqual(b.notify("notifications/cancelled", {"requestId": "approval-owned"})[0], 202)
                    with self.assertRaises(concurrent.futures.TimeoutError):
                        pending.result(timeout=0.2)
                    self.assertEqual(b.call("browser_tabs")[2]["error"]["code"], -32000)
                    self.assertEqual(a.notify("notifications/cancelled", {"requestId": "approval-owned"})[0], 202)
                    status, _, cancelled = pending.result(timeout=5)
                    self.assertEqual(status, 200)
                    self.assertTrue(cancelled["result"]["isError"])
                    error = json.loads(cancelled["result"]["content"][0]["text"])
                    self.assertEqual(error["status"], "cancelled")
                    self.assertEqual(error["outcome"], "unconfirmed")
                    self.assertIs(error["business_outcome_verified"], False)
                # Native cancellation acknowledgement must free the direct lane.
                deadline = time.monotonic() + 5
                while True:
                    _, _, after = b.call("browser_tabs")
                    if "result" in after or time.monotonic() >= deadline:
                        break
                    self.assertEqual(after["error"]["code"], -32000)
                    time.sleep(0.05)
                self.assertFalse(after["result"]["isError"], after)
                tabs = json.loads(after["result"]["content"][0]["text"])["tabs"]
                self.assertEqual({t["tab_id"] for t in tabs}, {t["tab_id"] for t in baseline})
                self.assertEqual(Fixture.hits, 0, "cancelled approval still navigated")
            finally:
                fixture.shutdown()
                fixture.server_close()
                thread.join(timeout=2)
        finally:
            for client in (a, b):
                self.assertEqual(client.http(method="DELETE")[0], 204)
                self.assertEqual(client.rpc("ping")[0], 404)


if __name__ == "__main__":
    unittest.main()
