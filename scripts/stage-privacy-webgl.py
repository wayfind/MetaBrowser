#!/usr/bin/env python3
"""Stage the pinned Chromium WebGL privacy gate; never fetch or build sources.

The browser transport supplies per-profile/site CanvasNoiseToken values. This
patch only consumes token presence: no token means the upstream extension policy.
Protected contexts keep WEBGL_debug_renderer_info, as official Chrome does, and
read an Apple Silicon family cohort as the unmasked renderer. An unmapped GPU
keeps the extension hidden instead of exposing its model.
GetExecutionContext() is inherited from CanvasRenderingContext and resolves the
canvas host's context, including WorkerGlobalScope for worker OffscreenCanvas.
Both extension enumeration and acquisition use ExtensionSupportedAndAllowed.

Usage: stage-privacy-webgl.py SOURCE_ROOT [--dry-run | --check]
Only modules/webgl/webgl_rendering_context_base.cc is changed under SOURCE_ROOT.
"""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import sys


BLINK = Path("third_party/blink/renderer")
TARGET = BLINK / "modules/webgl/webgl_rendering_context_base.cc"
VERSION = "MAJOR=154\nMINOR=0\nBUILD=8037\nPATCH=97\n"
ORIGINAL = """bool WebGLRenderingContextBase::ExtensionSupportedAndAllowed(
    const ExtensionTracker* tracker) {
  if (tracker->Draft() &&
      !RuntimeEnabledFeatures::WebGLDraftExtensionsEnabled())
    return false;
  if (tracker->Developer() &&
      !RuntimeEnabledFeatures::WebGLDeveloperExtensionsEnabled())
    return false;
  if (!tracker->Supported(this))
    return false;
  if (disabled_extensions_.Contains(String(tracker->ExtensionName())))
    return false;
  return true;
}
"""
OLD_GATE = """  // MetaBrowser WebGL privacy gate begin.
  // Use the canvas host context for both document and worker OffscreenCanvas.
  if (tracker->MatchesName(WebGLDebugRendererInfo::ExtensionName())) {
    ExecutionContext* execution_context = GetExecutionContext();
    if (execution_context && execution_context->CanvasNoiseToken().has_value()) {
      return false;
    }
  }
  // MetaBrowser WebGL privacy gate end.
"""
GATE = """  // MetaBrowser WebGL privacy gate begin.
  // Use the canvas host context for both document and worker OffscreenCanvas.
  // Protected contexts keep the extension when the renderer maps to a cohort.
  if (tracker->MatchesName(WebGLDebugRendererInfo::ExtensionName())) {
    ExecutionContext* execution_context = GetExecutionContext();
    if (execution_context && execution_context->CanvasNoiseToken().has_value() &&
        (!ContextGL() || !MetaBrowserRendererCohort(
                             String(ContextGL()->GetString(GL_RENDERER))))) {
      return false;
    }
  }
  // MetaBrowser WebGL privacy gate end.
"""
OLD_PATCHED = ORIGINAL.replace("  if (tracker->Draft()", OLD_GATE + "  if (tracker->Draft()", 1)
PATCHED = ORIGINAL.replace("  if (tracker->Draft()", GATE + "  if (tracker->Draft()", 1)
GATE_ANCHOR = "bool WebGLRenderingContextBase::ExtensionSupportedAndAllowed("
HELPER = """namespace {
// MetaBrowser WebGL renderer cohort: an Apple Silicon renderer string collapses
// to the base chip of its GPU family (M1, M2, M3 and later -> M3). Capabilities
// stay consistent with WebGL/WebGPU limits while tier and generation are hidden.
std::optional<String> MetaBrowserRendererCohort(const String& renderer) {
  const std::string value = renderer.Utf8();
  const size_t start = value.find("Apple M");
  if (start == std::string::npos) return std::nullopt;
  size_t digits = start + 7;
  unsigned generation = 0;
  while (digits < value.size() && value[digits] >= '0' && value[digits] <= '9' &&
         generation < 100) {
    generation = generation * 10 + static_cast<unsigned>(value[digits++] - '0');
  }
  if (!generation) return std::nullopt;
  const size_t end = value.find(',', digits);
  const char* chip = generation == 1 ? "Apple M1"
                     : generation == 2 ? "Apple M2" : "Apple M3";
  return String::FromUtf8(value.substr(0, start) + chip +
      (end == std::string::npos ? std::string() : value.substr(end)));
}
}  // namespace

"""
UNMASKED_ORIGINAL = """    case WebGLDebugRendererInfo::kUnmaskedRendererWebgl:
      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {
        return WebGLAny(script_state,
                        String(ContextGL()->GetString(GL_RENDERER)));
      }"""
UNMASKED_PATCHED = """    case WebGLDebugRendererInfo::kUnmaskedRendererWebgl:
      if (ExtensionEnabled(kWebGLDebugRendererInfoName)) {
        // MetaBrowser WebGL renderer cohort for protected contexts.
        String renderer(ContextGL()->GetString(GL_RENDERER));
        ExecutionContext* execution_context = GetExecutionContext();
        if (execution_context &&
            execution_context->CanvasNoiseToken().has_value()) {
          if (auto cohort = MetaBrowserRendererCohort(renderer)) {
            renderer = *cohort;
          }
        }
        return WebGLAny(script_state, renderer);
      }"""
MARKER = "MetaBrowser WebGL privacy gate"


class SourceDrift(ValueError):
    """A source/API mismatch requires review instead of a guessed patch."""


def require_once(text: str, anchor: str, label: str) -> None:
    if text.count(anchor) != 1:
        raise SourceDrift(f"{label}: expected exactly one pinned anchor")


def read_source(root: Path, relative: Path) -> str:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SourceDrift(f"source path escapes root or is a symlink: {relative}")
    return path.read_bytes().decode("utf-8")


def validate_apis(root: Path, source: str) -> None:
    """Verify the actual pinned accessors and both callers before any write."""
    requirements = {
        BLINK / "core/execution_context/execution_context.h": [
            "const std::optional<NoiseToken>& CanvasNoiseToken() const {\n"
            "    return canvas_noise_token_;\n  }",
        ],
        BLINK / "core/html/canvas/canvas_rendering_context.h": [
            "ExecutionContext* GetExecutionContext() const {",
            "return host->GetTopExecutionContext();",
        ],
        BLINK / "core/html/canvas/html_canvas_element.h": [
            "ExecutionContext* GetTopExecutionContext() const override {\n"
            "    return GetDocument().GetExecutionContext();\n  }",
        ],
        BLINK / "core/offscreencanvas/offscreen_canvas.h": [
            "ExecutionContext* GetTopExecutionContext() const override {\n"
            "    return execution_context_.Get();\n  }",
        ],
        BLINK / "core/workers/worker_or_worklet_global_scope.h": [
            "class CORE_EXPORT WorkerOrWorkletGlobalScope\n"
            "    : public EventTarget,\n      public ExecutionContext,",
        ],
        BLINK / "modules/webgl/webgl_rendering_context_base.h": [
            "      public CanvasRenderingContext,",
            "bool MatchesName(const String&) const;",
            "bool ExtensionSupportedAndAllowed(const ExtensionTracker*);",
        ],
    }
    for path, anchors in requirements.items():
        text = read_source(root, path)
        for anchor in anchors:
            require_once(text, anchor, str(path))
    for anchor in (
        '#include "third_party/blink/renderer/core/execution_context/execution_context.h"',
        '#include "third_party/blink/renderer/modules/webgl/webgl_debug_renderer_info.h"',
        "if (!tracker->MatchesName(name) || !ExtensionSupportedAndAllowed(tracker)) {",
        "WebGLExtension* extension = EnableExtensionIfSupported(name, context);",
        "if (ExtensionSupportedAndAllowed(tracker)) {\n"
        "      result.push_back(tracker->ExtensionName());",
    ):
        require_once(source, anchor, str(TARGET))


def transform(source: str) -> str:
    require_once(source, GATE_ANCHOR, "shared extension gate")
    if OLD_PATCHED in source:
        # Migrate the earlier unconditional gate; the cohort gate replaces it.
        require_once(source, OLD_PATCHED, "earlier staged gate")
        source = source.replace(OLD_PATCHED, ORIGINAL, 1)
    if PATCHED in source:
        require_once(source, PATCHED, "staged gate")
        if source.count(MARKER) != 2:
            raise SourceDrift("duplicate or partial privacy gate")
    elif MARKER in source:
        raise SourceDrift("partial or modified privacy gate")
    else:
        require_once(source, ORIGINAL, "upstream extension policy")
        source = source.replace(ORIGINAL, PATCHED, 1)
    if HELPER in source:
        require_once(source, HELPER, "renderer cohort helper")
    elif "MetaBrowserRendererCohort(const String& renderer)" in source:
        raise SourceDrift("partial or modified renderer cohort helper")
    else:
        source = source.replace(GATE_ANCHOR, HELPER + GATE_ANCHOR, 1)
    if UNMASKED_PATCHED in source:
        require_once(source, UNMASKED_PATCHED, "unmasked renderer cohort")
    else:
        require_once(source, UNMASKED_ORIGINAL, "upstream unmasked renderer")
        source = source.replace(UNMASKED_ORIGINAL, UNMASKED_PATCHED, 1)
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Chromium 154.0.8037.97 source root")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate and print diff without writing")
    mode.add_argument("--check", action="store_true", help="read-only; fail if staging is needed")
    args = parser.parse_args()
    try:
        root = args.source.resolve(strict=True)
        if read_source(root, Path("chrome/VERSION")) != VERSION:
            raise SourceDrift("unexpected Chromium version; expected 154.0.8037.97")
        before = read_source(root, TARGET)
        validate_apis(root, before)
        after = transform(before)
        changed = before != after
        if args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=str(TARGET), tofile=str(TARGET),
            ))
        elif changed and not args.check:
            # All guards pass before the sole source write. Re-staging is a no-op.
            (root / TARGET).write_bytes(after.encode("utf-8"))
        print(json.dumps({
            "path": str(TARGET),
            "status": "needs-staging" if changed and args.check else
                      "would-stage" if changed and args.dry_run else
                      "staged" if changed else "already-staged",
            "before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
            "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
        }, sort_keys=True))
        return 1 if args.check and changed else 0
    except (OSError, UnicodeError, SourceDrift) as exc:
        parser.exit(2, f"WebGL privacy staging refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
