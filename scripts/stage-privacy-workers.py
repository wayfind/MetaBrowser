#!/usr/bin/env python3
"""Preflight/stage shared/service worker tokens on Chromium 154.0.8037.97.

READ ONLY by default. --apply writes exactly eight files after checking every
anchor and the existing privacy-context transport prerequisites. JSON receipts
include all_files and their planned/resulting sha256 hashes, even on a no-op.
No remote access, GN edits, seed generation, worker identity or storage changes.

Run AFTER stage-privacy-context.py, outside any active build. Token derivation
uses the browser UI thread, BrowserContext, worker/registration StorageKey,
actual StoragePartition config, and browser-owned forced-partitioning top site.
Renderer bridges copy optional values verbatim, including authoritative null.
Service worker tokens live outside nullable network script-load parameters, so
installed/cached starts and restarts use the same bootstrap as fresh starts.

Shared-worker isolation relies on upstream default third-party partitioning.
User-forced disabling of that partitioning is UNSUPPORTED: a reused worker realm
cannot provide a different privacy identity per connecting top-level site. This
patch deliberately does not change worker matching or storage semantics.
Worklets are outside scope; the existing WorkerGlobalScope consumer is reused.

Privacy setting changes require a full browser RESTART. Reloading a page does
not replace live shared/service worker tokens. No hot policy propagation or
indiscriminate worker termination is implemented or required by this patch.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


VERSION = ["MAJOR=154", "MINOR=0", "BUILD=8037", "PATCH=97"]
MARKER = "METABROWSER_PRIVACY_WORKERS_V1:"
FILES = (
    "content/browser/worker_host/shared_worker_host.cc",
    "content/renderer/worker/embedded_shared_worker_stub.cc",
    "third_party/blink/renderer/core/exported/web_shared_worker_impl.cc",
    "third_party/blink/public/mojom/service_worker/embedded_worker.mojom",
    "content/browser/service_worker/embedded_worker_instance.cc",
    "third_party/blink/public/web/web_embedded_worker_start_data.h",
    "content/renderer/service_worker/embedded_worker_instance_client_impl.cc",
    "third_party/blink/renderer/modules/exported/web_embedded_worker_impl.cc",
)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Plan:
    def __init__(self, source):
        self.source = source
        self.original = {}
        self.result = {}
        self.prerequisites = {}

    def read(self, path):
        target = self.source / path
        if not target.resolve(strict=True).is_relative_to(self.source):
            raise ValueError(f"source path escapes checkout: {path}")
        return target.read_text(encoding="utf-8")

    def require(self, path, snippets):
        text = self.read(path)
        for snippet in snippets:
            if text.count(snippet) != 1:
                raise ValueError(f"missing/ambiguous prerequisite: {path}: {snippet}")
        self.prerequisites[path] = text

    def replace(self, path, anchor, replacement, tag):
        if path not in FILES:
            raise ValueError(f"write outside eight-file allowlist: {path}")
        if path not in self.original:
            self.original[path] = self.read(path)
            self.result[path] = self.original[path]
        text = self.result[path]
        marker = "// " + MARKER + tag + "\n"
        patched = marker + replacement
        if marker in text:
            # Earlier local staging duplicated an existing method-entry UI
            # checker. Keep upstream's guard and migrate only that exact patch.
            token = {"shared-browser-token": "  const auto metabrowser_top_key =",
                     "service-browser-token": "  const auto& metabrowser_worker_key ="}.get(tag)
            if token:
                legacy = patched.replace(token,
                    "  DCHECK_CURRENTLY_ON(BrowserThread::UI);\n" + token, 1)
                if legacy != patched and text.count(marker) == 1 and text.count(legacy) == 1:
                    self.result[path] = text.replace(legacy, patched, 1)
                    return
            if text.count(marker) != 1 or text.count(patched) != 1:
                raise ValueError(f"existing worker patch drift: {path} ({tag})")
            return
        if text.count(anchor) != 1:
            raise ValueError(f"expected one anchor, got {text.count(anchor)}: {path} ({tag})")
        self.result[path] = text.replace(anchor, patched, 1)

    def include(self, path, header, anchor, tag):
        # Validate our marker even if its include is present: edited existing
        # patches must fail closed instead of bypassing the drift guard.
        text = self.result.get(path)
        if text is None:
            text = self.read(path)
        include = "#include " + header
        if "// " + MARKER + tag + "\n" not in text and include in text.splitlines():
            return
        self.replace(path, anchor, anchor + "\n" + include, tag)

    def validate_snapshot(self):
        for path, text in {**self.prerequisites, **self.original}.items():
            if self.read(path) != text:
                raise ValueError(f"source changed during preflight: {path}")


def make_plan(source):
    p = Plan(source.resolve(strict=True))
    if p.read("chrome/VERSION").splitlines() != VERSION:
        raise ValueError("expected exact Chromium 154.0.8037.97 source")
    p.prerequisites["chrome/VERSION"] = p.read("chrome/VERSION")
    # These files are read/hashed only. Never run the context staging script
    # implicitly: its larger scope belongs to the caller's immutable receipt.
    p.require("content/public/browser/content_browser_client.h", [
        "virtual std::optional<uint64_t> GetMetaBrowserPrivacyToken(",
        "const StoragePartitionConfig& partition,\n"
        "      const url::Origin& top_frame_origin);"])
    p.require("content/public/browser/content_browser_client.cc", [
        "std::optional<uint64_t> ContentBrowserClient::GetMetaBrowserPrivacyToken(",
        "BrowserContext*, const blink::StorageKey&, const StoragePartitionConfig&,"])
    p.require("third_party/blink/public/mojom/worker/worker_main_script_load_params.mojom", [
        "uint64? metabrowser_privacy_token;"])
    p.require("third_party/blink/public/common/loader/worker_main_script_load_parameters.h", [
        "std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;"])
    p.require("third_party/blink/renderer/core/workers/global_scope_creation_params.h", [
        "std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;"])
    p.require("third_party/blink/renderer/core/workers/worker_global_scope.cc", [
        "SetCanvasNoiseToken(creation_params->metabrowser_privacy_token",
        "*creation_params->metabrowser_privacy_token))"])

    path = FILES[0]
    # Complete types for the hook, StorageKey top site and url::Origin::Create.
    p.include(path, '"content/public/browser/content_browser_client.h"',
              '#include "content/public/common/content_client.h"', "shared-browser-api")
    p.include(path, '"third_party/blink/public/common/storage_key/storage_key.h"',
              '#include "third_party/blink/public/common/features.h"', "shared-storage-key")
    p.include(path, '"url/origin.h"',
              '#include "content/browser/worker_host/shared_worker_host.h"', "shared-origin")
    anchor = "  // Send the CreateSharedWorker message.\n"
    p.replace(path, anchor, """  // Derive on browser UI, using this worker's own origin and the creator's
  // trusted top site. Never copy a connecting renderer's token. Worker matching
  // still relies on upstream third-party storage partitioning being enabled.
  const auto metabrowser_top_key =
      instance_.creator_storage_key()
          .CopyWithForceEnabledThirdPartyStoragePartitioning();
  result.main_script_load_params->metabrowser_privacy_token =
      GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
          GetProcessHost()->GetBrowserContext(), instance_.worker_storage_key(),
          GetStoragePartitionImpl()->GetConfig(),
          url::Origin::Create(metabrowser_top_key.top_level_site().GetURL()));

""" + anchor, "shared-browser-token")

    path = FILES[1]
    anchor = "  worker_main_script_load_params->request_id =\n"
    p.replace(path, anchor, """  worker_main_script_load_params->metabrowser_privacy_token =
      main_script_load_params->metabrowser_privacy_token;
""" + anchor, "shared-renderer-token")

    path = FILES[2]
    anchor = "  GetWorkerThread()->Start(std::move(creation_params), thread_startup_data,\n"
    p.replace(path, anchor, """  // Install before WorkerGlobalScope construction and script evaluation.
  // Absent browser bootstrap remains null; no creator/context fallback.
  if (worker_main_script_load_params) {
    creation_params->metabrowser_privacy_token =
        worker_main_script_load_params->metabrowser_privacy_token;
  }

""" + anchor, "shared-scope-token")

    path = FILES[3]
    anchor = "struct EmbeddedWorkerStartParams {"
    p.replace(path, anchor, anchor + """
  // Browser-derived for EVERY start, including installed/cached scripts.
  // Independent of optional network main_script_load_params; never a root key.
  uint64? metabrowser_privacy_token;
""", "service-mojo-token")

    path = FILES[4]
    p.include(path, '"content/public/browser/content_browser_client.h"',
              '#include "content/public/common/content_client.h"', "service-browser-api")
    p.include(path, '"third_party/blink/public/common/storage_key/storage_key.h"',
              '#include "third_party/blink/public/common/features.h"', "service-storage-key")
    p.include(path, '"url/origin.h"', '#include "url/gurl.h"', "service-origin")
    # The local process is allocated and checked on UI for every start, before
    # params is passed to SendStartWorker. No live document/client is required.
    anchor = "  CHECK(rph);\n\n  // Let the process know that it now has an instance of an origin that matches\n"
    p.replace(path, anchor, """  CHECK(rph);

  const auto& metabrowser_worker_key = owner_version_->key();
  const auto metabrowser_top_key =
      metabrowser_worker_key.CopyWithForceEnabledThirdPartyStoragePartitioning();
  params->metabrowser_privacy_token =
      GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
          rph->GetBrowserContext(), metabrowser_worker_key,
          rph->GetStoragePartition()->GetConfig(),
          url::Origin::Create(metabrowser_top_key.top_level_site().GetURL()));

  // Let the process know that it now has an instance of an origin that matches
""", "service-browser-token")

    path = FILES[5]
    anchor = '#include "base/unguessable_token.h"'
    p.replace(path, anchor,
              '#include <cstdint>\n#include <optional>\n\n' + anchor,
              "service-start-includes")
    anchor = "struct WebEmbeddedWorkerStartData {"
    p.replace(path, anchor, anchor + """
  // Authoritative browser decision, also present on installed-script starts.
  std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;
""", "service-start-token")

    path = FILES[6]
    anchor = "  start_data->script_url = params.script_url;"
    p.replace(path, anchor, """  // BuildStartData runs on the initiator sequence on all startup paths.
  start_data->metabrowser_privacy_token = params.metabrowser_privacy_token;
""" + anchor, "service-renderer-token")

    path = FILES[7]
    anchor = "  worker_thread_->Start(std::move(global_scope_creation_params),\n"
    p.replace(path, anchor, """  // No dependence on a fresh script fetch: installed scripts use this too.
  global_scope_creation_params->metabrowser_privacy_token =
      worker_start_data->metabrowser_privacy_token;

""" + anchor, "service-scope-token")

    if set(p.result) != set(FILES):
        raise ValueError("internal error: plan must contain exactly eight files")
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write only after all eight files pass preflight")
    args = parser.parse_args()
    try:
        p = make_plan(args.source)
        changes = {path: text for path, text in p.result.items()
                   if text != p.original[path]}
        p.validate_snapshot()
        if args.apply:
            for path, text in changes.items():
                target = p.source / path
                with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", dir=target.parent,
                        prefix=".privacy-workers-stage-", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(text)
                try:
                    temporary.chmod(target.stat().st_mode & 0o777)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        print(json.dumps({
            "applied": args.apply,
            "changed_files": sorted(changes),
            "all_files": sorted(p.result),
            "sha256": {path: sha256(text) for path, text in sorted(p.result.items())},
            "before_sha256": {path: sha256(text) for path, text in sorted(p.original.items())},
            "prerequisite_sha256": {path: sha256(text) for path, text in sorted(p.prerequisites.items())},
            "browser_thread": "UI only; renderer bridges copy optional values",
            "service_worker_cached_starts": "top-level EmbeddedWorkerStartParams token; independent of main_script_load_params",
            "shared_worker_isolation": "upstream default third-party partitioning required; user-forced disable unsupported",
            "settings_lifecycle": "privacy setting changes require browser restart; page reload does not replace live shared/service worker tokens",
            "scope": ["shared worker startup", "service worker fresh/installed/cached startup and restart"],
            "unchanged": ["WorkerGlobalScope consumer", "worker identity and storage semantics", "worklets", "GN targets", "WebAudio"],
            "build_required": "regenerate Mojo and incrementally rebuild after the current full build completes",
        }, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Privacy worker staging refused: {error}\n")


if __name__ == "__main__":
    main()
