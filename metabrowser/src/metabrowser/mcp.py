"""Minimal, dependency-free MCP server (tools only).

One transport-agnostic handler serves:
  * stdio NDJSON           `metabrowser mcp --standalone` (browser in-process)
  * Streamable HTTP (JSON) daemon `POST /mcp`
  * stdio -> HTTP bridge   `metabrowser mcp` (what metacodes' `mcp_servers` launches)

Protocol versions match what the metacodes MCP client negotiates.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

from . import __version__
from .tools.base import ToolError, ToolRegistry

SUPPORTED_VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26")
INSTRUCTIONS = (
    "MetaBrowser controls a real (stealth) Chromium shared with the user. Prefer the cheapest layer: "
    "site_<pack>_* tools (L3 recipes) > L2 semantic tools (page_read, data_extract_table, form_fill, "
    "data_collect_pages, net_capture_*) > L1 primitives (page_snapshot + page_click/page_type by [eN] ref). "
    "Use page_screenshot only for visual checks. Never ask for or type the user's passwords: use "
    "auth_ensure_login and let the user log in. Submit/irreversible actions may require user approval."
)


def tool_result_to_mcp(result) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if result.text:
        content.append({"type": "text", "text": result.text})
    if result.image_b64:
        content.append({"type": "image", "data": result.image_b64, "mimeType": result.image_mime})
    if not content:
        content.append({"type": "text", "text": "ok"})
    return {"content": content, "isError": False}


class McpHandler:
    def __init__(self, registry: ToolRegistry, layers: Optional[set[str]] = None, extra_tools: Optional[dict] = None):
        self.registry = registry
        self.layers = layers
        # name -> (describe dict, async fn(args, session) -> result) for non-registry tools (agent.run_task)
        self.extra_tools = extra_tools or {}

    async def handle(self, msg: dict[str, Any], session_id: str) -> Optional[dict[str, Any]]:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification
            return None
        try:
            result = await self._dispatch(method, msg.get("params") or {}, session_id)
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}

    async def _dispatch(self, method: str, params: dict[str, Any], session_id: str) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            return {
                "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[2],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "metabrowser", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            tools = [s.describe() for s in self.registry.list(self.layers)]
            tools += [d for d, _ in self.extra_tools.values()]
            return {"tools": tools}
        if method == "tools/call":
            name, args = params.get("name", ""), params.get("arguments") or {}
            try:
                if name in self.extra_tools:
                    result = await self.extra_tools[name][1](args, session_id)
                else:
                    result = await self.registry.call(name, args, session_id=session_id)
                return tool_result_to_mcp(result)
            except ToolError as e:
                return {"content": [{"type": "text", "text": json.dumps(e.to_dict(), ensure_ascii=False)}],
                        "isError": True}
        raise _RpcError(-32601, f"method not found: {method}")


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


async def _stdin_lines():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            return
        if line.strip():
            yield line


def _write(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def serve_stdio(handler: McpHandler, session_id: str) -> None:
    pending: set[asyncio.Task] = set()

    async def one(msg):
        resp = await handler.handle(msg, session_id)
        if resp is not None:
            _write(resp)

    async for line in _stdin_lines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        # Tool calls run concurrently (metacodes may issue parallel calls); responses carry ids.
        task = asyncio.create_task(one(msg))
        pending.add(task)
        task.add_done_callback(pending.discard)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def bridge_stdio_to_http(url: str, token: str, session_id: str) -> None:
    """stdio MCP <-> daemon /mcp. Keeps metacodes' MCP subprocess tiny and stateless."""

    def post(body: bytes) -> Optional[dict]:
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "content-type": "application/json", "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {token}", "x-metabrowser-session": session_id})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return {"_http_error": f"{e.code} {e.read()[:200]!r}"}
        except OSError as e:
            return {"_http_error": str(e)}

    loop = asyncio.get_running_loop()
    pending: set[asyncio.Task] = set()

    async def one(line: bytes):
        resp = await loop.run_in_executor(None, post, line)
        if resp and "_http_error" in resp:
            try:
                mid = json.loads(line).get("id")
            except Exception:
                mid = None
            if mid is not None:
                _write({"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32000, "message": f"metabrowser daemon unreachable: {resp['_http_error']}"}})
        elif resp is not None:
            _write(resp)

    async for line in _stdin_lines():
        task = asyncio.create_task(one(line))
        pending.add(task)
        task.add_done_callback(pending.discard)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
