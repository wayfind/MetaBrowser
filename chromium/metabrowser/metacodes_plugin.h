#ifndef METABROWSER_METACODES_PLUGIN_H_
#define METABROWSER_METACODES_PLUGIN_H_
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define MB_METACODES_ABI 2u
// Events are borrowed and delivered on the worker running mb_mc_run.
// 0=text, 1=status, 2=error, 3=terminal. Host copies before returning.
typedef void (*mb_mc_event)(void*, uint32_t, const uint8_t*, uint64_t);
// Synchronous worker callback; marshal UI/browser work to the UI sequence.
// kind 0=SDK UI request, 1=browser tool. Host allocates response with malloc.
typedef uint32_t (*mb_mc_request)(void*, uint32_t, const char*, const uint8_t*,
                                  uint64_t, uint8_t**, uint64_t*);
typedef struct mb_mc_config {
  uint32_t struct_size;
  uint32_t abi;
  const char* endpoint;
  const char* model;
  const char* api_key;
  const char* workspace;
  mb_mc_event event;
  void* context;
  uint32_t provider;  // AgentCore provider code: Anthropic=1, OpenAI=2, Gemini=3.
  uint32_t protocol;  // 0=provider default, 1=OpenAI Responses.
  uint32_t shell_policy; // 1=disabled, 2=SDK sandboxed. No silent fallback.
  uint32_t max_turns;
  mb_mc_request request;
  const char* state_home;
  const char* checkpoint; // Optional checkpoint to restore, never raw profile.
} mb_mc_config;
uint32_t mb_mc_abi(void);
void* mb_mc_create(const mb_mc_config*);
uint32_t mb_mc_run(void*, uint64_t, const char*);
// Typed JSON input: text, skill, or multimodal parts; optional context_blocks.
uint32_t mb_mc_run_input(void*, uint64_t, const char*);
// 12=versioned raw event+RunContext; 13=typed terminal status/result.
// SDK callback status domains MUST NOT be interchanged.
#define MB_UI_ANSWERED 0u
#define MB_UI_UNAVAILABLE 1u
#define MB_UI_FATAL 2u
#define MB_UI_CANCELLED 3u
#define MB_HOST_OK 0u
#define MB_HOST_FAILED 1u
#define MB_HOST_REJECTED 2u
#define MB_HOST_FATAL 3u
uint32_t mb_mc_abort(void*, uint64_t);
void mb_mc_destroy(void*);
// Idle-session operations. Returned JSON is malloc-owned; use mb_mc_free.
uint32_t mb_mc_control(void*, const char*, const char*, uint8_t**, uint64_t*);
void mb_mc_free(uint8_t*, uint64_t);
// Separate account worker. Events 6=instructions, 8=private credential result,
// 9=authentication error. Never forward these events to a model or A2A client.
uint32_t mb_mc_login_available(void);
uint32_t mb_mc_login(const char* state_root, mb_mc_event, void*);
// 0=PKCE, 1=restore, 2=logout/revoke, 3=device fallback.
uint32_t mb_mc_account(const char* state_root, uint32_t operation, mb_mc_event, void*);
void mb_mc_login_cancel(void);
#ifdef __cplusplus
}
#endif
#endif
