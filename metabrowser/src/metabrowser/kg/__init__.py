"""Site knowledge -> TinyKG.

Writes a site pack's feature map (modules/pages), interaction map (actions),
data entities, risks and capabilities into a TinyKG store using the
``metabrowser-site`` schema, so metacodes agents can recall them with
KgRecall/KgContext and governance can query e.g. all irreversible actions.

Transport: the TinyKG CLI against a store path (the same pair metacodes uses in
dev mode: METACODES_KG_BIN / METACODES_KG_STORE). Node ids are memoised in a
sidecar file so repeated syncs are idempotent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..sites import SitePack

SCHEMA_PATH = Path(__file__).with_name("metabrowser-site.schema.json")


@dataclass
class Plan:
    """Backend-neutral list of nodes/edges; also the JSON export format."""

    nodes: list[tuple[str, str]] = field(default_factory=list)       # (kind, name)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (src name, rel, dst name)

    def node(self, kind: str, name: str) -> str:
        if (kind, name) not in self.nodes:
            self.nodes.append((kind, name))
        return name

    def edge(self, src: str, rel: str, dst: str) -> None:
        if (src, rel, dst) not in self.edges:
            self.edges.append((src, rel, dst))

    def to_json(self) -> dict:
        return {"schema": "metabrowser-site", "nodes": [{"kind": k, "name": n} for k, n in self.nodes],
                "edges": [{"src": s, "rel": r, "dst": d} for s, r, d in self.edges]}


def plan_for(site: SitePack) -> Plan:
    """Map site.json + capabilities onto the schema. Names are '<site>/<kind>/<id>'."""
    p, m, sid = Plan(), site.meta, site.id
    n = lambda kind, ident: f"{sid}/{kind}/{ident}"  # noqa: E731
    root = p.node("site", sid)
    for risk in m.get("risks", []):
        r = p.node("site_risk", n("risk", risk["id"]))
        p.edge(root, "has_risk", r)
    for ent in m.get("entities", []):
        e = p.node("data_entity", n("entity", ent["id"]))
        for rid in ent.get("risks", []):
            p.edge(e, "has_risk", n("risk", rid))
    for mod in m.get("modules", []):
        p.edge(root, "has_module", p.node("site_module", n("module", mod["id"])))
    for page in m.get("pages", []):
        pg = p.node("site_page", n("page", page["id"]))
        p.edge(n("module", page["module"]) if page.get("module") else root, "has_page", pg)
        for ent in page.get("entities", []):
            p.edge(pg, "reads_entity", n("entity", ent))
        for act in page.get("actions", []):
            a = p.node("ui_action", n("action", act["id"]))
            p.edge(pg, "exposes_action", a)
            if act.get("navigates_to"):
                p.edge(a, "navigates_to", n("page", act["navigates_to"]))
            for ent in act.get("writes", []):
                p.edge(a, "writes_entity", n("entity", ent))
            for rid in act.get("risks", []):
                p.edge(a, "has_risk", n("risk", rid))
        for target in page.get("links", []):
            p.edge(pg, "navigates_to", n("page", target))
    for cap in site.capabilities.values():
        c = p.node("capability", n("capability", cap.name))
        p.edge(root, "provides", c)
        rec = p.node("recipe", n("recipe", cap.name))
        p.edge(rec, "implements", c)
        for ent in cap.reads:
            p.edge(c, "reads_entity", n("entity", ent))
        for ent in cap.writes:
            p.edge(c, "writes_entity", n("entity", ent))
    return p


class TinyKG:
    def __init__(self, store: Path, binary: Optional[str] = None):
        self.store = Path(store).expanduser()
        self.bin = binary or os.environ.get("METACODES_KG_BIN") or shutil.which("tinykg")
        if not self.bin:
            raise RuntimeError("tinykg binary not found: pass --kg-bin or set METACODES_KG_BIN")
        self._ids_file = self.store.parent / (self.store.name + ".metabrowser-ids.json")
        state = json.loads(self._ids_file.read_text()) if self._ids_file.exists() else {}
        self.ids: dict[str, int] = state.get("nodes", {})
        self.edges: set[tuple[str, str, str]] = {tuple(e) for e in state.get("edges", [])}  # type: ignore[misc]

    def _run(self, *args: str) -> str:
        out = subprocess.run([self.bin, *args], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"tinykg {' '.join(args[:2])}: {(out.stderr or out.stdout).strip()}")
        return out.stdout

    def ensure_store(self) -> None:
        if not self.store.exists():
            self._run("init", str(self.store))
        self._run("schema-apply", str(self.store), "--schema", str(SCHEMA_PATH))

    def apply(self, plan: Plan) -> dict[str, int]:
        self.ensure_store()
        added_nodes = added_edges = 0
        for kind, name in plan.nodes:
            if name in self.ids:
                continue
            out = self._run("add-node", str(self.store), kind, name, "--schema", str(SCHEMA_PATH))
            match = re.search(r"node (\d+)", out)
            if not match:
                raise RuntimeError(f"unexpected tinykg output: {out!r}")
            self.ids[name] = int(match.group(1))
            added_nodes += 1
        for src, rel, dst in plan.edges:
            if (src, rel, dst) in self.edges or src not in self.ids or dst not in self.ids:
                continue
            self._run("add-edge", str(self.store), str(self.ids[src]), rel, str(self.ids[dst]),
                      "--schema", str(SCHEMA_PATH))
            self.edges.add((src, rel, dst))
            added_edges += 1
        self._ids_file.write_text(json.dumps({"nodes": self.ids, "edges": sorted(self.edges)},
                                             ensure_ascii=False, indent=1))
        return {"nodes_added": added_nodes, "edges_added": added_edges}
