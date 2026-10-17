#include "runtime_host.h"
#include <assert.h>
#include <stdio.h>
static unsigned cancelled, released, started;
static void event(void* p, uint64_t run, const uint8_t* b, uint64_t n) { (void)p; (void)run; (void)b; (void)n; }
static void begin(void* p, uint64_t run, const uint8_t* b, uint64_t n,
                  mb_event_fn cb, void* ctx) { (void)b; (void)n; (void)ctx; assert(p == &cancelled && run == 42 && cb == event); ++started; }
static void cancel(void* p, uint64_t run) { assert(p == &cancelled && run == 42); ++cancelled; }
static void release(void* p) { assert(p == &cancelled); ++released; }
int main(void) {
  mb_runtime_host host = { sizeof(host), MB_RUNTIME_ABI, &cancelled, begin, cancel, release };
  assert(!mb_register_runtime(0));
  host.abi = 99; assert(!mb_register_runtime(&host)); host.abi = MB_RUNTIME_ABI;
  assert(mb_register_runtime(&host)); assert(!mb_register_runtime(&host));
  assert(!mb_begin_runtime(0, 0, 0, event, 0));
  assert(mb_begin_runtime(42, 0, 0, event, 0)); assert(started == 1);
  mb_cancel_runtime(42); assert(cancelled == 1);
  mb_shutdown_runtime(); mb_shutdown_runtime(); assert(released == 1);
  assert(mb_register_runtime(&host)); mb_shutdown_runtime(); assert(released == 2);
  puts("Runtime ABI registration/cancellation/lifetime: PASS");
}
