#!/usr/bin/env python3
"""Preflight/stage MetaBrowser privacy context on Chromium 154.0.8037.97.

Default is READ ONLY: print the complete change plan. --apply writes only after
every source anchor and existing patch has been validated. Stages the project's
header-only privacy_context GN target and its //chrome/browser:core dependency,
plus the native unit-test source/dependency in //chrome/test:unit_tests.

Runtime: balanced by default, controlled by the registered enabled profile pref.
Explicit --metabrowser-privacy=off gives baseline; balanced still respects prefs.
Empty/unknown explicit modes warn and use balanced protection. No seed switch exists.
Document and dedicated-worker bootstrap carry ONLY a derived uint64.
Shared/service workers and worklets have null tokens. Opaque/nonce documents
under a verified protected top site use context-local ephemeral tokens.
Renderer-created inherited-origin documents reuse only a matching local owner's
context, checked before scripts with full top-site/nonce/origin constraints.
This first cut does NOT claim full worker coverage.

Settings contract: privacy_context.h registers nonsyncing root_secret, enabled,
and compatibility_sites profile prefs. Main must expose enabled + canonical
schemeful-site exceptions in Settings; root_secret must NEVER be allowlisted for
WebUI. Exceptions apply to newly created contexts; reload existing pages/workers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import os
import re
import tempfile


VERSION = ["MAJOR=154", "MINOR=0", "BUILD=8037", "PATCH=97"]
MARKER = "METABROWSER_PRIVACY_CONTEXT_V1:"


def gn_block(text, signature):
    if text.count(signature) != 1:
        raise ValueError(f"expected one GN target: {signature}")
    start = text.index(signature)
    brace = text.index("{", start)
    depth, quoted, escaped, comment = 0, False, False, False
    for index in range(brace, len(text)):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == "#":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise ValueError(f"unterminated GN target: {signature}")


class Plan:
    def __init__(self, source):
        self.source = source
        self.original = {}
        self.result = {}

    def read(self, path):
        if path not in self.original:
            self.original[path] = (self.source / path).read_text()
            self.result[path] = self.original[path]
        return self.result[path]

    def replace(self, path, anchor, replacement, tag, previous_replacement=None):
        text = self.read(path)
        marker = "// " + MARKER + tag + "\n"
        patched = marker + replacement
        if marker in text:
            if (previous_replacement is not None and text.count(marker) == 1
                    and text.count(marker + previous_replacement) == 1):
                self.result[path] = text.replace(marker + previous_replacement, patched, 1)
                return
            if text.count(marker) != 1 or text.count(patched) != 1:
                raise ValueError(f"existing privacy patch drift: {path} ({tag})")
            return
        if text.count(anchor) != 1:
            raise ValueError(f"expected one anchor, got {text.count(anchor)}: {path} ({tag})")
        self.result[path] = text.replace(anchor, patched, 1)

    def include(self, path, include, anchor, tag):
        # An existing upstream/other-worker include is already sufficient.
        if include in self.read(path):
            return
        self.replace(path, anchor, anchor + "\n" + include, tag)

    def helper(self, project, name):
        path = "metabrowser/" + name
        target = self.source / path
        expected = (project / "chromium/metabrowser" / name).read_text()
        if target.exists():
            self.original[path] = target.read_text()
            if self.original[path] != expected:
                raise ValueError(f"existing {name} differs; review before replacing")
        else:
            self.original[path] = None
        self.result[path] = expected

    def gn_list(self, path, signature, field, value):
        text = self.read(path)
        start, end = gn_block(text, signature)
        block = text[start:end]
        anchors = list(re.finditer(r"(?m)^  " + field + r" = \[", block))
        if len(anchors) != 1:
            raise ValueError(f"expected one top-level GN {field}: {path} {signature}")
        # Scope membership to this list, not an unrelated target/list.
        opening = anchors[0].end()
        closing = block.index("]", opening)
        if '"' + value + '"' in block[opening:closing]:
            return
        position = start + opening
        addition = '\n    "' + value + '",'
        self.result[path] = text[:position] + addition + text[position:]

    def gn_target(self, project):
        path = "metabrowser/BUILD.gn"
        text = self.read(path)
        signature = 'source_set("privacy_context") {'
        if signature in text:
            begin, end = gn_block(text, signature)
            if '"privacy_context.h"' not in text[begin:end]:
                raise ValueError("privacy_context target does not expose privacy_context.h")
            return
        configured = (project / "chromium/metabrowser/BUILD.gn").read_text()
        begin, end = gn_block(configured, signature)
        self.result[path] = text + "\n" + configured[begin:end] + "\n"


def make_plan(source, project):
    if (source / "chrome/VERSION").read_text().splitlines() != VERSION:
        raise ValueError("expected exact Chromium 154.0.8037.97 source")
    p = Plan(source)
    p.helper(project, "privacy_context.h")
    p.helper(project, "privacy_context_unittest.cc")
    p.gn_target(project)
    p.gn_list("chrome/browser/BUILD.gn", 'source_set("core") {', "deps",
              "//metabrowser:privacy_context")
    p.gn_list("chrome/test/BUILD.gn", 'test("unit_tests") {', "sources",
              "//metabrowser/privacy_context_unittest.cc")
    p.gn_list("chrome/test/BUILD.gn", 'test("unit_tests") {', "deps",
              "//metabrowser:privacy_context")
    browser_header = "content/public/browser/content_browser_client.h"
    browser_hook = """  // Browser-owned context only; no renderer-provided origin or profile seed.
  // Non-Chrome embedders keep their baseline through this default-null hook.
  virtual std::optional<uint64_t> GetMetaBrowserPrivacyToken(
      BrowserContext* browser_context, const blink::StorageKey& storage_key,
      const StoragePartitionConfig& partition,
      const url::Origin& top_frame_origin);

"""
    anchor = "  virtual void OverrideWebPreferences(WebContents* web_contents,"
    old_browser_hook = browser_hook.replace(
        "const url::Origin& top_frame_origin);",
        "const url::Origin& top_frame_origin) { return std::nullopt; }")
    p.replace(browser_header, anchor, browser_hook + anchor, "embedder-hook",
              previous_replacement=old_browser_hook + anchor)
    path = "content/public/browser/content_browser_client.cc"
    anchor = "bool ContentBrowserClient::OverrideWebPreferencesAfterNavigation("
    p.replace(path, anchor, """std::optional<uint64_t> ContentBrowserClient::GetMetaBrowserPrivacyToken(
    BrowserContext*, const blink::StorageKey&, const StoragePartitionConfig&,
    const url::Origin&) {
  return std::nullopt;
}

""" + anchor, "embedder-default-implementation")
    chrome_header = "chrome/browser/chrome_content_browser_client.h"
    anchor = "  void OverrideWebPreferences(content::WebContents* web_contents,"
    p.replace(chrome_header, anchor, """  std::optional<uint64_t> GetMetaBrowserPrivacyToken(
      content::BrowserContext* browser_context,
      const blink::StorageKey& storage_key,
      const content::StoragePartitionConfig& partition,
      const url::Origin& top_frame_origin) override;

""" + anchor, "chrome-hook")
    chrome_cc = "chrome/browser/chrome_content_browser_client.cc"
    p.include(chrome_cc, '#include "metabrowser/privacy_context.h"',
              '#include "chrome/browser/chrome_content_browser_client.h"', "privacy-helper")
    anchor = "void ChromeContentBrowserClient::OverrideWebPreferences("
    p.replace(chrome_cc, anchor, """std::optional<uint64_t> ChromeContentBrowserClient::GetMetaBrowserPrivacyToken(
    content::BrowserContext* browser_context,
    const blink::StorageKey& storage_key,
    const content::StoragePartitionConfig& partition,
    const url::Origin& top_frame_origin) {
  return metabrowser::GetPrivacyContextToken(
      Profile::FromBrowserContext(browser_context), storage_key, partition,
      top_frame_origin);
}

""" + anchor, "chrome-derive")
    anchor = """void ChromeContentBrowserClient::RegisterProfilePrefs(
    user_prefs::PrefRegistrySyncable* registry) {"""
    p.replace(chrome_cc, anchor, anchor + "\n  metabrowser::RegisterPrivacyContextPrefs(registry);",
              "register-profile-prefs")

    # Reject a damaged persistent identity before keyed services, restored tabs
    # or background workers can initialize. Keep the stored bytes for recovery;
    # a missing root remains a legitimate new profile. Handle both creation APIs.
    impl = "chrome/browser/profiles/profile_impl.cc"
    p.include(impl, '#include "metabrowser/privacy_context.h"',
              '#include "chrome/browser/profiles/profile_impl.h"',
              "profile-identity-validation")
    p.include(impl, '#include "chrome/browser/ui/simple_message_box.h"',
              '#include "chrome/browser/profiles/profile_impl.h"',
              "profile-identity-error-ui")
    for header, tag in [
            ('components/keep_alive_registry/scoped_keep_alive.h', 'error-ui-keep-alive'),
            ('components/keep_alive_registry/keep_alive_types.h', 'error-ui-keep-alive-types')]:
        p.include(impl, '#include "' + header + '"',
                  '#include "chrome/browser/profiles/profile_impl.h"', tag)
    anchor = '  TRACE_EVENT0("browser", "ProfileImpl::OnPrefsLoaded");'
    old_guard = anchor + '''
  if (metabrowser::HasInvalidPrivacyRoot(prefs_.get())) {
    LOG(ERROR) << "MetaBrowser privacy identity invalid; profile load refused";
    chrome::ShowWarningMessageBoxSync(
        gfx::NativeWindow(), u"身份配置无法加载",
        u"身份配置无法读取或校验，已阻止加载此配置。原身份未更换。"
        u"请从备份恢复配置或检查文件权限，或使用其他完好的身份后重试。");
    success = false;
  }'''
    p.replace(impl, anchor, anchor + '''
  if (metabrowser::HasInvalidPrivacyRoot(prefs_.get())) {
    LOG(ERROR) << "MetaBrowser privacy identity invalid; profile load refused";
    // Reject synchronously before services/tabs; only defer presentation. A
    // startup NSAlert must not block the failure delegate and app activation.
    success = false;
    if (!g_browser_process->IsShuttingDown()) {
      auto keep_alive = std::make_unique<ScopedKeepAlive>(
          KeepAliveOrigin::PROFILE_MANAGER, KeepAliveRestartOption::DISABLED);
      base::SequencedTaskRunner::GetCurrentDefault()->PostNonNestableTask(
          FROM_HERE, base::BindOnce([](std::unique_ptr<ScopedKeepAlive> keep_alive) {
            if (!g_browser_process || g_browser_process->IsShuttingDown()) return;
            chrome::ShowWarningMessageBoxAsync(
                gfx::NativeWindow(), u"身份配置无法加载",
                u"身份配置无法读取或校验，已阻止加载此配置。原身份未更换。"
                u"请从备份恢复配置或检查文件权限，或使用其他完好的身份后重试。",
                base::BindOnce([](std::unique_ptr<ScopedKeepAlive>,
                                  chrome::MessageBoxResult) {},
                               std::move(keep_alive)));
          }, std::move(keep_alive)));
    }
  }''', "profile-identity-fail-closed", previous_replacement=old_guard)
    anchor = '''      path, delegate, create_mode, creation_time, io_task_runner));
  return profile;'''
    old_sync_guard = '''      path, delegate, create_mode, creation_time, io_task_runner));
  if (create_mode == CreateMode::kSynchronous &&
      metabrowser::HasInvalidPrivacyRoot(profile->GetPrefs())) {
    return nullptr;
  }
  return profile;'''
    # Synchronous creation registers an unowned ProfileInfo before returning.
    # Never destroy the local unique_ptr while leaving that registration alive.
    p.replace(impl, anchor, anchor, "profile-identity-sync-fail-closed",
              previous_replacement=old_sync_guard)
    manager = "chrome/browser/profiles/profile_manager.cc"
    p.include(manager, '#include "metabrowser/privacy_context.h"',
              '#include "chrome/browser/profiles/profile_manager.h"',
              "profile-manager-identity-validation")
    anchor = "  TakeOwnershipOfProfile(std::move(profile), info);"
    p.replace(manager, anchor, anchor + '''
  if (metabrowser::HasInvalidPrivacyRoot(info->GetRawProfile()->GetPrefs())) {
    // Ownership must precede erasure: ProfileInfo's destructor requires it.
    // No final initialization, tabs or keyed services for rejected identities.
    profiles_info_.erase(profile_dir);
    return nullptr;
  }''', "profile-manager-identity-fail-closed")

    # Chromium renames malformed JSON to Preferences.bad. A later launch
    # must not confuse this retained damaged identity with a brand-new profile.
    # This runs on the existing preferences file task sequence, never UI I/O.
    path = "components/prefs/json_pref_store.cc"
    anchor = '''      case JSONFileValueDeserializer::JSON_NO_SUCH_FILE:
        return PersistentPrefStore::PREF_READ_ERROR_NO_FILE;'''
    p.replace(path, anchor, '''      case JSONFileValueDeserializer::JSON_NO_SUCH_FILE:
        if (path.BaseName().value() == FILE_PATH_LITERAL("Preferences") &&
            base::PathExists(path.ReplaceExtension(kBadExtension))) {
          return PersistentPrefStore::PREF_READ_ERROR_JSON_REPEAT;
        }
        return PersistentPrefStore::PREF_READ_ERROR_NO_FILE;''', "profile-damaged-json-restart-fail-closed")

    # Additive nullable primitives need no new Mojo import, typemap or GN target.
    path = "third_party/blink/public/mojom/navigation/navigation_params.mojom"
    anchor = "struct CommitNavigationParams {"
    p.replace(path, anchor, anchor + """
  // Derived browser context token, never the profile's root secret.
  uint64? metabrowser_privacy_token;
""", "commit-mojo")
    path = "content/browser/renderer_host/render_frame_host_impl.cc"
    anchor = "  TRACE_EVENT0(\"navigation\", \"RenderFrameHostImpl::SendCommitNavigation\");"
    p.replace(path, anchor, anchor + """
  commit_params->metabrowser_privacy_token =
      GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
          GetBrowserContext(), commit_params->storage_key,
          GetStoragePartition()->GetConfig(),
          IsOutermostMainFrame() ? commit_params->origin_to_commit
              : GetOutermostMainFrame()->GetLastCommittedOrigin());
""", "browser-commit-token")
    for path in ("content/browser/renderer_host/navigation_entry_impl.cc",
                 "content/browser/renderer_host/navigation_controller_impl.cc"):
        anchor = "blink::mojom::CommitNavigationParams::New(\n          url::Origin(),"
        p.replace(path, anchor,
                  "blink::mojom::CommitNavigationParams::New(\n          std::nullopt, url::Origin(),",
                  "commit-constructor-null-token")
    path = "content/browser/renderer_host/navigation_request.cc"
    for suffix, tag in (
        ("""          // The correct storage key will be computed before committing the
          // navigation.
          blink::StorageKey(), override_user_agent,""", "before-commit"),
        ("""          // The correct storage key is computed right after creating the
          // NavigationRequest below.
          blink::StorageKey(), is_overriding_user_agent, redirects,""", "before-request"),
    ):
        anchor = "blink::mojom::CommitNavigationParams::New(\n          url::Origin(),\n" + suffix
        replacement = anchor.replace("url::Origin(),", "std::nullopt, url::Origin(),", 1)
        p.replace(path, anchor, replacement, "request-commit-constructor-" + tag)
    path = "third_party/blink/public/web/web_navigation_params.h"
    anchor = "  StorageKey storage_key;"
    p.replace(path, anchor, anchor + "\n  std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;\n  bool metabrowser_privacy_context_from_browser = false;",
              "web-navigation-token")
    path = "content/renderer/render_frame_impl.cc"
    anchor = "  navigation_params->navigation_timings = BuildNavigationTimings("
    p.replace(path, anchor, """  navigation_params->metabrowser_privacy_token =
      commit_params.metabrowser_privacy_token;
  navigation_params->metabrowser_privacy_context_from_browser = true;
""" + anchor, "renderer-commit-token")
    path = "third_party/blink/renderer/core/loader/document_loader.h"
    anchor = "  blink::BlinkStorageKey storage_key_;"
    p.replace(path, anchor, anchor + "\n  std::optional<uint64_t> metabrowser_privacy_token_;\n  bool metabrowser_privacy_context_from_browser_;",
              "loader-token-member")
    path = "third_party/blink/renderer/core/loader/document_loader.cc"
    anchor = "  BlinkStorageKey storage_key;"
    p.replace(path, anchor, anchor + "\n  std::optional<uint64_t> metabrowser_privacy_token;\n  bool metabrowser_privacy_context_from_browser;",
              "loader-size-mirror")
    p.include(path, '#include "base/rand_util.h"',
              '#include "third_party/blink/renderer/core/loader/document_loader.h"', "ephemeral-random")
    anchor = "      storage_key_(std::move(params_->storage_key)),"
    p.replace(path, anchor, anchor + "\n      metabrowser_privacy_token_(params_->metabrowser_privacy_token),\n      metabrowser_privacy_context_from_browser_(params_->metabrowser_privacy_context_from_browser),",
              "loader-token-init")
    anchor = "  params->storage_key = window->GetStorageKey();"
    p.replace(path, anchor, anchor + """
  // javascript:/XSLT document clones preserve their OWN context, including an
  // authoritative null. Never derive identity from a URL or parent here.
  if (window->CanvasNoiseToken()) {
    params->metabrowser_privacy_token = window->CanvasNoiseToken()->Value();
  }
  params->metabrowser_privacy_context_from_browser = true;
""", "clone-own-context")
    anchor = "  frame_->DomWindow()->SetCanvasNoiseToken(std::nullopt);"
    p.replace(path, anchor, """  std::optional<NoiseToken> metabrowser_token;
  // The loader can correct a provisional browser StorageKey. Never apply an
  // origin's token to a different/opaque document, including sandboxed frames.
  if (metabrowser_privacy_token_ &&
      ((metabrowser_privacy_context_from_browser_ &&
        (frame_->DomWindow()->GetSecurityOrigin()->IsOpaque() ||
         storage_key_.GetNonce())) ||
       (!frame_->DomWindow()->GetSecurityOrigin()->IsOpaque() &&
        storage_key_.GetSecurityOrigin()->IsSameOriginWith(
            frame_->DomWindow()->GetSecurityOrigin())))) {
    metabrowser_token.emplace(*metabrowser_privacy_token_);
  }
  // Browser commits (including authoritative null/disabled decisions) NEVER
  // fall back to a parent. The only bootstrap is an inherited-origin document
  // whose actual owner was selected by Chromium's existing origin algorithm.
  // Both LocalFrames inhabit this RenderProcessHost, which owns one browser
  // StoragePartition and BrowserContext. Check the remaining StorageKey scopes
  // explicitly, including real top-site when 3P partitioning is disabled.
  if (!metabrowser_privacy_context_from_browser_ && owner_document &&
      owner_document->GetFrame() && owner_document->domWindow() &&
      Document::ShouldInheritSecurityOriginFromOwner(Url())) {
    const auto owner_key = owner_document->domWindow()->GetStorageKey()
                               .CopyWithForceEnabledThirdPartyStoragePartitioning();
    const auto target_key = frame_->DomWindow()->GetStorageKey()
                                .CopyWithForceEnabledThirdPartyStoragePartitioning();
    if ((frame_->DomWindow()->GetSecurityOrigin()->IsOpaque() ||
         target_key.GetNonce()) &&
        frame_->Tree().Parent() == owner_document->GetFrame() &&
        owner_document->domWindow()->CanvasNoiseToken()) {
      // A sandboxed/srcdoc child cannot expose unprotected readback. Stable
      // for this context only; NEVER reuse its protected parent's token.
      metabrowser_token.emplace(base::RandUint64());
    } else if (!frame_->DomWindow()->GetSecurityOrigin()->IsOpaque() &&
        frame_->DomWindow()->GetSecurityOrigin()->IsSameOriginWith(
            owner_document->domWindow()->GetSecurityOrigin()) &&
        !owner_key.GetNonce() && !target_key.GetNonce() &&
        owner_key.GetTopLevelSite() == target_key.GetTopLevelSite() &&
        owner_key.GetSecurityOrigin()->IsSameOriginWith(
            target_key.GetSecurityOrigin().get())) {
      metabrowser_token = owner_document->domWindow()->CanvasNoiseToken();
    }
  }
  frame_->DomWindow()->SetCanvasNoiseToken(metabrowser_token);""", "document-context-token")

    path = "third_party/blink/public/mojom/worker/worker_main_script_load_params.mojom"
    anchor = "struct WorkerMainScriptLoadParams {"
    p.replace(path, anchor, anchor + """
  // Populated only by DedicatedWorkerHost; other worker bootstraps remain null.
  uint64? metabrowser_privacy_token;
""", "worker-mojo")
    path = "content/browser/worker_host/dedicated_worker_host.cc"
    p.include(path, '#include "content/public/browser/content_browser_client.h"',
              '#include "content/public/common/content_client.h"', "worker-browser-api")
    anchor = "  client_->OnScriptLoadStarted("
    p.replace(path, anchor, """  result->main_script_load_params->metabrowser_privacy_token =
      GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
          GetProcessHost()->GetBrowserContext(), worker_storage_key_,
          GetStoragePartitionImpl()->GetConfig(),
          ancestor_render_frame_host
              ? ancestor_render_frame_host->GetOutermostMainFrame()->GetLastCommittedOrigin()
              : url::Origin());
""" + anchor, "dedicated-browser-token")
    path = "third_party/blink/public/common/loader/worker_main_script_load_parameters.h"
    p.include(path, "#include <optional>", "#include <vector>", "worker-optional")
    p.include(path, "#include <cstdint>", "#include <vector>", "worker-cstdint")
    anchor = "  int request_id;"
    p.replace(path, anchor, anchor + "\n  std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;",
              "worker-public-token")
    path = "content/renderer/worker/dedicated_worker_host_factory_client.cc"
    anchor = "  worker_main_script_load_params->request_id ="
    p.replace(path, anchor, """  worker_main_script_load_params->metabrowser_privacy_token =
      main_script_load_params->metabrowser_privacy_token;
""" + anchor, "dedicated-renderer-token")
    path = "third_party/blink/renderer/core/workers/global_scope_creation_params.h"
    anchor = "struct CORE_EXPORT GlobalScopeCreationParams final {"
    p.replace(path, anchor, anchor + """
  // Default null for shared/service workers and all worklets. Never copy a
  // creator's token; only a browser-owned dedicated-worker bootstrap fills it.
  std::optional<uint64_t> metabrowser_privacy_token = std::nullopt;
""", "worker-scope-token")
    path = "third_party/blink/renderer/core/workers/dedicated_worker.cc"
    anchor = """  context_proxy_->StartWorkerGlobalScope(
      CreateGlobalScopeCreationParams(
          script_url, referrer_policy,
          std::move(response_content_security_policies),
          std::move(document_policy), std::move(coep_reporting_observer),
          std::move(dip_reporting_observer)),
      std::move(worker_main_script_load_params), options_, script_url,"""
    p.replace(path, anchor, """  auto metabrowser_scope_params = CreateGlobalScopeCreationParams(
      script_url, referrer_policy, std::move(response_content_security_policies),
      std::move(document_policy), std::move(coep_reporting_observer),
      std::move(dip_reporting_observer));
  metabrowser_scope_params->metabrowser_privacy_token =
      worker_main_script_load_params
          ? worker_main_script_load_params->metabrowser_privacy_token
          : std::nullopt;
  context_proxy_->StartWorkerGlobalScope(
      std::move(metabrowser_scope_params),
      std::move(worker_main_script_load_params), options_, script_url,""", "dedicated-scope-token")
    path = "third_party/blink/renderer/core/workers/worker_global_scope.cc"
    anchor = '  TRACE_EVENT("blink.worker", "WorkerGlobalScope::WorkerGlobalScope");'
    p.replace(path, anchor, anchor + """
  // Shared/service worker creation params stay null. Dedicated opaque workers
  // receive only their own browser-issued ephemeral token, never a parent key.
  SetCanvasNoiseToken(creation_params->metabrowser_privacy_token
                          ? std::make_optional(NoiseToken(
                                *creation_params->metabrowser_privacy_token))
                          : std::nullopt);
""", "worker-context-token")
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--apply", action="store_true", help="write after all preflight checks pass")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    try:
        plan = make_plan(args.source, project)
        changes = {path: text for path, text in plan.result.items()
                   if text != plan.original[path]}
        # Detect edits made after preflight, before the first write.
        for path, original in plan.original.items():
            target = args.source / path
            if (target.read_text() if target.exists() else None) != original:
                raise ValueError(f"source changed during preflight: {path}")
        if args.apply:
            for path, text in changes.items():
                target = args.source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", dir=target.parent,
                                                 prefix=".privacy-stage-", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(text)
                try:
                    temporary.chmod(target.stat().st_mode & 0o777 if target.exists() else 0o644)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        print(json.dumps({"applied": args.apply, "changed_files": sorted(changes),
                          "all_files": sorted(plan.result),
                          "sha256": {path: hashlib.sha256(text.encode()).hexdigest()
                                     for path, text in sorted(plan.result.items())},
                          "build_wiring": "//chrome/browser:core -> //metabrowser:privacy_context; //chrome/test:unit_tests includes privacy_context_unittest.cc",
                          "unit_test_filter": "MetaBrowserPrivacyContextTest.*",
                          "inherited_frame_probe": "chromium/metabrowser/privacy_context_probe.html (serve loopback; compare balanced with explicit off)",
                          "runtime_mode": "balanced by default, respects enabled pref; explicit off is baseline; invalid explicit mode warns and stays protected; damaged root rejects profile load",
                          "supported": ["browser-committed documents", "matching local inherited-origin documents before script", "protected opaque/nonce scopes use per-context ephemeral tokens", "same-context javascript/XSLT document clones", "dedicated workers including nested"],
                          "null_token": ["shared workers", "service workers", "worklets", "non-HTTP(S) top sites", "unmatched or ownerless renderer-created documents"],
                          "settings_ui_required": ["metabrowser.privacy.enabled", "metabrowser.privacy.compatibility_sites"]}, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Privacy context staging refused: {error}\n")


if __name__ == "__main__":
    main()
