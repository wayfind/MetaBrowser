#include "chromium/privacy/metabrowser_storage_quota.h"
#include <cassert>
#include <cstdint>
#include <limits>

int main() {
  constexpr int64_t headroom=int64_t{10}*1024*1024*1024;
  constexpr int64_t maximum=std::numeric_limits<int64_t>::max();
  using content::MetaBrowserReportedStorageQuota;
  static_assert(MetaBrowserReportedStorageQuota(0)==headroom);
  static_assert(MetaBrowserReportedStorageQuota(4096)==headroom+4096);
  static_assert(MetaBrowserReportedStorageQuota(maximum)==maximum);
  static_assert(MetaBrowserReportedStorageQuota(maximum-headroom)==maximum);
  assert(MetaBrowserReportedStorageQuota(-1)==headroom);
  for(int64_t usage=0;usage<=32*1024*1024;usage+=4096)
    assert(MetaBrowserReportedStorageQuota(usage)-usage==headroom);
  for(int64_t offset=0;offset<1024;offset++)
    assert(MetaBrowserReportedStorageQuota(maximum-offset)==maximum);
}
