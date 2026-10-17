#ifndef METABROWSER_STORAGE_QUOTA_H_
#define METABROWSER_STORAGE_QUOTA_H_

#include <cstdint>
#include <limits>

namespace content {
// Report only an origin's own usage plus a stable public allowance. Actual
// quota enforcement and explicit application-authored bucket caps are separate.
inline constexpr int64_t MetaBrowserReportedStorageQuota(int64_t usage) {
  constexpr int64_t headroom = int64_t{10} * 1024 * 1024 * 1024;
  constexpr int64_t maximum = std::numeric_limits<int64_t>::max();
  if (usage < 0) usage = 0;
  return usage > maximum - headroom ? maximum : usage + headroom;
}
}  // namespace content

#endif
