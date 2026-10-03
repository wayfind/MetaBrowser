"""Append-only, hash-chained trajectory log.

One NDJSON file per daemon run under ~/.metabrowser/traces/. Each event carries
``prev`` (hash of the previous event) and ``hash`` = sha256(prev + canonical
event body), so any edit, deletion or reordering is detected by ``verify``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

GENESIS = "0" * 64
FORMAT = "metabrowser-trace/v1"


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()


def _digest(prev: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(prev.encode() + _canonical(body)).hexdigest()


class TraceRecorder:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self._lock = threading.Lock()
        self._seq = 0
        self._prev = GENESIS
        self._listeners: list = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():  # resume the chain
                for event in read_events(path):
                    self._seq, self._prev = event["seq"], event["hash"]
            else:
                self._write({"type": "header", "format": FORMAT, "ts": time.time()})

    def subscribe(self, callback) -> None:
        """callback(event) for live views (side panel)."""
        self._listeners.append(callback)

    def record(self, **fields: Any) -> dict[str, Any]:
        return self._write({"type": "tool_call", **{k: v for k, v in fields.items() if v is not None}})

    def note(self, session: str, kind: str, **fields: Any) -> dict[str, Any]:
        """Non-tool events: approvals, session start/stop, user takeover."""
        return self._write({"type": kind, "session": session, **fields})

    def _write(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            body = {"seq": self._seq, "ts": body.pop("ts", time.time()), **body}
            event = {**body, "prev": self._prev, "hash": _digest(self._prev, body)}
            self._prev = event["hash"]
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        for cb in list(self._listeners):
            try:
                cb(event)
            except Exception:
                pass
        return event


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def verify(path: Path) -> tuple[bool, str]:
    """Return (ok, message). Checks sequence continuity and the hash chain."""
    prev, expected_seq = GENESIS, 1
    for event in read_events(path):
        body = {k: v for k, v in event.items() if k not in ("prev", "hash")}
        if event.get("seq") != expected_seq:
            return False, f"sequence gap at seq={event.get('seq')} (expected {expected_seq})"
        if event.get("prev") != prev:
            return False, f"broken link at seq={event['seq']}"
        if _digest(prev, body) != event.get("hash"):
            return False, f"tampered event at seq={event['seq']}"
        prev, expected_seq = event["hash"], expected_seq + 1
    return True, f"ok: {expected_seq - 1} events, head={prev[:12]}"
