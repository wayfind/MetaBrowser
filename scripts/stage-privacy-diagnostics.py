#!/usr/bin/env python3
"""Guarded native diagnostic redaction for Chromium 154.0.8037.97.

Read-only by default; --apply stages exactly two .cc files. Run after privacy
context staging, outside an active build. Never reads profile preference data,
prints a secret, changes stored preferences, or contacts a remote machine.

The direct prefs-internals URL returns a fixed JSON string for the root key.
Aggregate diagnostics skip that EXACT flat pref name before SetByDottedPath
creates the nested JSON tree. Other preference values/metadata stay unchanged.
No new includes, public headers, GN dependencies or test-source edits are needed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


VERSION = ["MAJOR=154", "MINOR=0", "BUILD=8037", "PATCH=97"]
ROOT_HEADER = "metabrowser/privacy_context.h"
ROOT_KEY = "metabrowser.privacy.root_secret"
MARKER = "METABROWSER_PRIVACY_DIAGNOSTICS_V1:"
FILES = (
    "chrome/browser/ui/webui/prefs_internals_source.cc",
    "components/local_state/local_state_utils.cc",
)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require_once(text, anchor, label):
    if text.count(anchor) != 1:
        raise ValueError(f"missing/ambiguous source anchor: {label}")


class Plan:
    def __init__(self, source):
        self.source = source.resolve(strict=True)
        self.original = {}
        self.result = {}
        self.prerequisites = {}

    def read(self, path):
        target = self.source / path
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(self.source):
            raise ValueError(f"source path escapes checkout or is a symlink: {path}")
        return target.read_bytes().decode("utf-8")

    def prerequisite(self, path):
        text = self.read(path)
        self.prerequisites[path] = text
        return text

    def replace(self, path, anchor, replacement, tag):
        if path not in FILES:
            raise ValueError(f"write outside two-source allowlist: {path}")
        text = self.read(path)
        self.original[path] = text
        marker = "// " + MARKER + tag + "\n"
        patched = marker + replacement
        if MARKER in text:
            if text.count(MARKER) != 1 or text.count(patched) != 1:
                raise ValueError(f"existing diagnostic redaction drift: {path}")
            self.result[path] = text
            return
        require_once(text, anchor, path)
        self.result[path] = text.replace(anchor, patched, 1)

    def validate_snapshot(self):
        for path, expected in {**self.prerequisites, **self.original}.items():
            if self.read(path) != expected:
                raise ValueError(f"source changed during preflight: {path}")


def make_plan(source):
    plan = Plan(source)
    if plan.prerequisite("chrome/VERSION").splitlines() != VERSION:
        raise ValueError("expected exact Chromium 154.0.8037.97 source")
    header = plan.prerequisite(ROOT_HEADER)
    keys = re.findall(
        r'^inline constexpr char kPrivacyRootSecretPref\[\]\s*=\s*"([^"\n]+)"\s*;',
        header, re.MULTILINE,
    )
    if keys != [ROOT_KEY]:
        raise ValueError("privacy root-pref constant missing, ambiguous or changed")
    require_once(header, "registry->RegisterStringPref(kPrivacyRootSecretPref, std::string());",
                 "registered privacy root key")
    key = keys[0]
    direct = plan.read(FILES[0])
    for anchor in (
        "std::string_view pref_name = path.substr(1);",
        "base::WriteJsonWithOptions(*pref->GetValue(),",
        "local_state_utils::GetPrefsAsJson(prefs).value_or(std::string());",
    ):
        require_once(direct, anchor, FILES[0])
    anchor = "    if (auto* pref = prefs->FindPreference(pref_name)) {"
    plan.replace(FILES[0], anchor, f'''    // Redact before looking up/reading the stored root; keep other prefs intact.
    if (pref_name == "{key}") {{
      response_data = "\\\"[redacted]\\\"";
    }} else if (auto* pref = prefs->FindPreference(pref_name)) {{''', "direct-root-pref")

    aggregate = plan.read(FILES[1])
    for anchor in (
        "pref_service->GetPreferencesValueAndStore();",
        'pref_details.Set("value", value.Clone());',
        "local_state_values.SetByDottedPath(name, std::move(pref_details));",
    ):
        require_once(aggregate, anchor, FILES[1])
    anchor = "  for (const auto& [name, value, pref_value_store_type] : values) {"
    plan.replace(FILES[1], anchor, anchor + f'''
    // Pref names are flat here; exclude only this key before dotted JSON assembly.
    if (name == "{key}") {{
      continue;
    }}''', "aggregate-root-pref")
    if set(plan.result) != set(FILES):
        raise ValueError("internal error: expected exactly two source files")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pinned Chromium source root")
    parser.add_argument("--apply", action="store_true", help="write after complete preflight")
    args = parser.parse_args()
    try:
        plan = make_plan(args.source)
        changes = {path: text for path, text in plan.result.items()
                   if text != plan.original[path]}
        plan.validate_snapshot()
        if args.apply:
            for path, text in changes.items():
                target = plan.source / path
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=target.parent,
                    prefix=".privacy-diagnostics-stage-", delete=False,
                ) as output:
                    temporary = Path(output.name)
                    output.write(text.encode("utf-8"))
                try:
                    temporary.chmod(target.stat().st_mode & 0o777)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        print(json.dumps({
            "applied": args.apply,
            "changed_files": sorted(changes),
            "all_files": sorted(plan.result),
            "sha256": {path: sha256(text) for path, text in sorted(plan.result.items())},
            "before_sha256": {path: sha256(text) for path, text in sorted(plan.original.items())},
            "prerequisite_sha256": {path: sha256(text) for path, text in sorted(plan.prerequisites.items())},
            "redacted_pref": ROOT_KEY,
            "direct_response": "fixed JSON string [redacted]; no root value lookup",
            "aggregate_response": "exact flat name excluded before dotted JSON assembly",
            "unchanged": ["stored root", "other preferences and metadata", "GN dependencies"],
            "build_required": "recompile both native sources and package the complete app",
        }, indent=2))
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"Privacy diagnostic staging refused: {error}\n")


if __name__ == "__main__":
    main()
