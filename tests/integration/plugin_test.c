#include "metacodes_plugin.h"
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static void* (*create_fn)(const mb_mc_config*);
static uint32_t (*run_fn)(void*, uint64_t, const char*);
static uint32_t (*abort_fn)(void*, uint64_t);
static void (*destroy_fn)(void*);
static _Atomic int chunks, cancelled;
static void* session;
static void event(void* ctx,uint32_t kind,const uint8_t* bytes,uint64_t length) {
  (void)ctx;
  if(kind==0) atomic_fetch_add(&chunks,1);
  if(kind==2) {fprintf(stderr,"SDK error: %.*s\n",(int)length,bytes);}
  if(kind==3 && length==9 && memcmp(bytes,"Cancelled",9)==0) atomic_store(&cancelled,1);
}
static void* slow_run(void* p) { (void)p; run_fn(session,3,"cancel-check");return 0; }
int main(int argc,char** argv) {
  assert(argc==2);
  void* lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
  if(!lib){fprintf(stderr,"%s\n",dlerror());return 1;}
  create_fn=dlsym(lib,"mb_mc_create");run_fn=dlsym(lib,"mb_mc_run");
  abort_fn=dlsym(lib,"mb_mc_abort");destroy_fn=dlsym(lib,"mb_mc_destroy");
  assert(create_fn && run_fn && abort_fn && destroy_fn);
  mb_mc_config config={sizeof(config),MB_METACODES_ABI,"http://127.0.0.1:18792/v1/chat/completions","gpt-4.1-mini","fixture-key","/tmp",event,0,2,0,2,64,0,"/tmp",0};
  session=create_fn(&config);assert(session);
  assert(run_fn(session,1,"验收真实会话") == 0);assert(atomic_load(&chunks)>0);
  assert(run_fn(session,2,"第二轮会话") == 0);
  atomic_store(&chunks,0);
  pthread_attr_t attr; assert(pthread_attr_init(&attr)==0); assert(pthread_attr_setstacksize(&attr,16*1024*1024)==0);
  pthread_t thread;assert(pthread_create(&thread,&attr,slow_run,0)==0); pthread_attr_destroy(&attr);
  for(int i=0;i<500 && !atomic_load(&chunks);i++)usleep(10000);
  assert(atomic_load(&chunks)>0);
  assert(abort_fn(session,3)==0);pthread_join(thread,0);
  assert(atomic_load(&cancelled));
  destroy_fn(session);
  session=create_fn(&config);assert(session);destroy_fn(session);
  puts("PASS: real AgentCore multi-turn streaming, cancellation and session recreation");
}
