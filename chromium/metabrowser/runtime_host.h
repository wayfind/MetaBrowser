#ifndef METABROWSER_RUNTIME_HOST_H_
#define METABROWSER_RUNTIME_HOST_H_
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define MB_RUNTIME_ABI 1u
// Called on the browser UI sequence. Copy borrowed bytes before returning.
// Post completion asynchronously on that sequence; never block on model work.
typedef void (*mb_event_fn)(void* context, uint64_t run_id,
                            const uint8_t* bytes, uint64_t length);
typedef struct mb_runtime_host {
  uint32_t struct_size;
  uint32_t abi;
  void* context;
  void (*begin)(void*, uint64_t, const uint8_t*, uint64_t, mb_event_fn, void*);
  void (*cancel)(void*, uint64_t);
  void (*release)(void*);
} mb_runtime_host;
// Browser owns the registered host until shutdown. No model/provider logic here.
// Returns 0 for ABI mismatch/incomplete tables or a second registration.
int mb_register_runtime(const mb_runtime_host* host);
// Returns admission only, never task success. The callback reports completion.
int mb_begin_runtime(uint64_t run_id, const uint8_t* bytes, uint64_t length,
                     mb_event_fn callback, void* callback_context);
void mb_cancel_runtime(uint64_t run_id);
void mb_shutdown_runtime(void);
#ifdef __cplusplus
}
#endif
#endif
