"""Scripted Anthropic Messages API (SSE) for driving the embedded agent loop in tests.

A script is a callable(request_json, turn_index) -> list of blocks:
    {"text": "..."}                                   assistant text
    {"tool_use": {"name": "page_navigate", "input": {...}}}
Each POST /v1/messages consumes one turn. Requests are recorded for assertions.
"""

from __future__ import annotations

import itertools
import json
from typing import Any, Callable

from aiohttp import web

Script = Callable[[dict, int], list[dict]]


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class MockLLM:
    def __init__(self, script: Script):
        self.script = script
        self.requests: list[dict] = []
        self._ids = itertools.count(1)
        self.runner = None
        self.url = ""

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/v1/messages", self.messages)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/v1/messages"
        return self.url

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()

    async def messages(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        turn = len(self.requests)
        self.requests.append(body)
        blocks = self.script(body, turn)
        resp = web.StreamResponse(headers={"content-type": "text/event-stream"})
        await resp.prepare(request)
        msg_id = f"msg_{next(self._ids)}"
        await resp.write(_sse("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": body.get("model", "mock"),
            "content": [], "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 0}}}))
        stop = "end_turn"
        for i, b in enumerate(blocks):
            if "text" in b:
                await resp.write(_sse("content_block_start", {"type": "content_block_start", "index": i,
                                                              "content_block": {"type": "text", "text": ""}}))
                await resp.write(_sse("content_block_delta", {"type": "content_block_delta", "index": i,
                                                              "delta": {"type": "text_delta", "text": b["text"]}}))
            else:
                tu = b["tool_use"]
                stop = "tool_use"
                await resp.write(_sse("content_block_start", {"type": "content_block_start", "index": i,
                                                              "content_block": {"type": "tool_use",
                                                                                "id": f"toolu_{next(self._ids)}",
                                                                                "name": tu["name"], "input": {}}}))
                await resp.write(_sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(tu.get("input", {}))}}))
            await resp.write(_sse("content_block_stop", {"type": "content_block_stop", "index": i}))
        await resp.write(_sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop},
                                                "usage": {"output_tokens": 5}}))
        await resp.write(_sse("message_stop", {"type": "message_stop"}))
        await resp.write_eof()
        return resp


def last_tool_result(body: dict) -> str:
    """Text of the most recent tool_result block sent back by the agent."""
    for msg in reversed(body.get("messages", [])):
        content = msg.get("content")
        if isinstance(content, list):
            for block in reversed(content):
                if block.get("type") == "tool_result":
                    c = block.get("content")
                    if isinstance(c, list):
                        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
                    return str(c)
    return ""


def tool_result_containing(body: dict, needle: str) -> str:
    """Most recent tool_result whose text contains `needle` (results of earlier turns included)."""
    for msg in reversed(body.get("messages", [])):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if block.get("type") != "tool_result":
                continue
            c = block.get("content")
            text = "".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c)
            if needle in text:
                return text
    return ""


def tool_names(body: dict) -> list[str]:
    return [t.get("name") for t in body.get("tools", [])]


def scripted(turns: list[Any]) -> Script:
    """Static script: each entry is a block list or callable(body)->block list."""

    def run(body: dict, turn: int) -> list[dict]:
        if turn >= len(turns):
            return [{"text": "done"}]
        t = turns[turn]
        return t(body) if callable(t) else t

    return run
