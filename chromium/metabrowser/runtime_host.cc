#include "runtime_host.h"
#include <optional>
namespace { std::optional<mb_runtime_host> runtime; }
extern "C" int mb_register_runtime(const mb_runtime_host* host) {
  if (!host || host->struct_size != sizeof(mb_runtime_host) ||
      host->abi != MB_RUNTIME_ABI || !host->begin || !host->cancel ||
      !host->release || runtime) return 0;
  runtime = *host;
  return 1;
}
extern "C" int mb_begin_runtime(uint64_t run_id, const uint8_t* bytes,
                                 uint64_t length, mb_event_fn callback,
                                 void* callback_context) {
  if (!runtime || !run_id || !callback || (!bytes && length)) return 0;
  auto host = *runtime;
  host.begin(host.context, run_id, bytes, length, callback, callback_context);
  return 1;
}
extern "C" void mb_cancel_runtime(uint64_t run_id) {
  if (runtime) runtime->cancel(runtime->context, run_id);
}
extern "C" void mb_shutdown_runtime() {
  if (!runtime) return;
  auto previous = *runtime;
  runtime.reset();
  previous.release(previous.context);
}
