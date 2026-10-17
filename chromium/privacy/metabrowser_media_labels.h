// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_MODULES_MEDIASTREAM_METABROWSER_MEDIA_LABELS_H_
#define THIRD_PARTY_BLINK_RENDERER_MODULES_MEDIASTREAM_METABROWSER_MEDIA_LABELS_H_

#include "third_party/blink/renderer/core/execution_context/execution_context.h"
#include "third_party/blink/renderer/platform/wtf/text/string_builder.h"

namespace blink {
// The suffix is drawn only from the already web-visible, origin-salted device
// ID, never a hardware name or native ID. It adds no extra identifier and keeps
// devices distinguishable without changing permission checks or routing IDs.
inline String MetaBrowserMediaAlias(const char* kind, const String& public_id) {
  StringBuilder result;
  result.Append(String(kind));
  if (!public_id.empty()) {
    result.Append(' ');
    result.Append(public_id.substr(0, 8));
  }
  return result.ToString();
}

inline String MetaBrowserMediaLabel(ExecutionContext* context,
                                    const String& original,
                                    const String& public_id,
                                    const char* kind) {
  // Empty upstream labels are a permission boundary; do not reveal existence
  // or turn permission-denied results into apparently authorized devices.
  if (original.empty() || !context || !context->CanvasNoiseToken())
    return original;
  return MetaBrowserMediaAlias(kind, public_id);
}
}  // namespace blink
#endif
