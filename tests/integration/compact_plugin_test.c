#include "metacodes_plugin.h"
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t (*control)(void*,const char*,const char*,uint8_t**,uint64_t*);
static void (*release)(uint8_t*,uint64_t);
static void event(void* ctx,uint32_t kind,const uint8_t* bytes,uint64_t n){
  (void)ctx;if(kind==2)fprintf(stderr,"fixture SDK diagnostic: %.*s\n",(int)n,bytes);
}
static void invoke(void* session,const char* op,const char* argument,const char* stage){
  uint8_t* out=0;uint64_t n=0;assert(control(session,op,argument,&out,&n)==0);
  printf("{\"stage\":\"%s\",\"result\":%.*s}\n",stage,(int)(n?n:4),n?(char*)out:"null");
  release(out,n);
}
int main(int argc,char** argv){
  assert(argc==4);void* lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
  if(!lib){fprintf(stderr,"%s\n",dlerror());return 1;}
  void* (*create)(const mb_mc_config*)=dlsym(lib,"mb_mc_create");
  uint32_t (*run)(void*,uint64_t,const char*)=dlsym(lib,"mb_mc_run");
  void (*destroy)(void*)=dlsym(lib,"mb_mc_destroy");
  control=dlsym(lib,"mb_mc_control");release=dlsym(lib,"mb_mc_free");
  assert(create&&run&&destroy&&control&&release);
  mb_mc_config c={sizeof(c),MB_METACODES_ABI,argv[2],"gpt-4.1-mini","fixture",argv[3],event,0,2,0,2,64,0,argv[3],0};
  void* s=create(&c);assert(s);
  invoke(s,"compact","","empty_compact");
  char old[8193];memset(old,'A',8192);old[8192]=0;
  assert(run(s,1,old)==0);
  for(uint64_t id=2;id<=6;id++)assert(run(s,id,"recent context") == 0);
  invoke(s,"describe","","before");invoke(s,"compact","","compact");invoke(s,"describe","","after");
  assert(run(s,7,"continue after compact") == 0);
  char checkpoint[4096];snprintf(checkpoint,sizeof(checkpoint),"%s/checkpoint",argv[3]);
  invoke(s,"checkpoint",checkpoint,"checkpoint");destroy(s);
  c.checkpoint=checkpoint;s=create(&c);assert(s);
  assert(run(s,8,"continue after restoring compressed context") == 0);
  invoke(s,"describe","","restored");destroy(s);
  return 0;
}
