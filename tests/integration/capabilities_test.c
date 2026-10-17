#include "metacodes_plugin.h"
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <fcntl.h>
static unsigned permissions,starts,chunks;
static void event(void *raw,uint32_t kind,const uint8_t *p,uint64_t n){
  (void)raw;if(kind==2)fprintf(stderr,"SDK: %.*s\n",(int)n,p);
  if(kind==0)chunks++;
  if(kind==4 && n && memmem(p,n,"tool_start",10))starts++;
}
static uint32_t request(void *raw,uint32_t kind,const char *name,const uint8_t *p,uint64_t n,uint8_t **out,uint64_t *length){
  (void)name;assert(kind==0);permissions++;
  // Fixture parses the SDK's exact request identity, never approves by model text.
  char *s=strndup((const char*)p,n);char id[256]={0};unsigned long generation=0;
  const char *a=strstr(s,"\"request_id\":\"");assert(a);a+=14;const char *b=strchr(a,'"');assert(b && b-a<256);memcpy(id,a,b-a);
  a=strstr(s,"\"policy_generation\":");assert(a);generation=strtoul(a+20,NULL,10);
  char response[512];int bytes=snprintf(response,sizeof(response),"{\"permission\":\"%s\",\"request_id\":\"%s\",\"policy_generation\":%lu}",raw?"deny_once":"allow_once",id,generation);
  free(s);*out=malloc(bytes);memcpy(*out,response,bytes);*length=bytes;return 0;
}
int main(int argc,char **argv){
  assert(argc==3||argc==4);void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);if(!library){puts(dlerror());return 1;}
  void *(*create)(const mb_mc_config*)=dlsym(library,"mb_mc_create");
  uint32_t (*run)(void*,uint64_t,const char*)=dlsym(library,"mb_mc_run");
  void (*destroy)(void*)=dlsym(library,"mb_mc_destroy");
  uint32_t (*control)(void*,const char*,const char*,uint8_t**,uint64_t*)=dlsym(library,"mb_mc_control");
  void (*release)(uint8_t*,uint64_t)=dlsym(library,"mb_mc_free");
  mb_mc_config config={sizeof(config),2,"http://127.0.0.1:18794/v1/chat/completions","gpt-4.1-mini","fixture",argv[2],event,NULL,2,0,2,32,request,argv[2],NULL};
  void *session=create(&config);assert(session);uint8_t *output=NULL;uint64_t length=0;
  if(argc==4){
    FILE *f=fopen(argv[3],"rb");assert(f);char configuration[1024*1024];size_t n=fread(configuration,1,sizeof(configuration)-1,f);fclose(f);configuration[n]=0;
    unsigned status=control(session,"mcp_configure",configuration,&output,&length);
    printf("MCP probe status %u; catalog bytes %llu\n",status,(unsigned long long)length);
    if(output)printf("%.*s\n",(int)length,output);release(output,length);destroy(session);return status;
  }
  assert(control(session,"describe","",&output,&length)==0);assert(memmem(output,length,"gpt-4.1-mini",12));release(output,length);
  assert(run(session,1,"coding-fixture")==0);assert(starts>=3);assert(permissions>0);
  char path[4096];snprintf(path,sizeof(path),"%s/agent-result.txt",argv[2]);assert(access(path,F_OK)==0);
  snprintf(path,sizeof(path),"%s/checkpoint.bin",argv[2]);unsigned checkpoint_status=control(session,"checkpoint",path,&output,&length);assert(checkpoint_status==0);release(output,length);
  destroy(session);config.checkpoint=path;session=create(&config);assert(session);config.checkpoint=NULL;
  char setup[8192];snprintf(setup,sizeof(setup),"{\"revision\":1,\"servers\":[{\"name\":\"fixture\",\"url\":\"http://127.0.0.1:18794/mcp\",\"tools\":[\"echo\"]}]}");
  unsigned status=control(session,"mcp_configure",setup,&output,&length);if(status)fprintf(stderr,"MCP configure status %u: %.*s\n",status,(int)length,output);assert(status==0);release(output,length);
  if(getenv("METABROWSER_TEST_MCP_EXPIRY"))sleep(31);
  unsigned before=starts;assert(run(session,2,"mcp-fixture")==0);assert(starts>before);
  char cwd[4096];assert(getcwd(cwd,sizeof(cwd)));
  int unrelated=-1;if(getenv("METABROWSER_TEST_FD_ISOLATION")){unrelated=socket(AF_INET,SOCK_STREAM,0);assert(unrelated>=0);assert(fcntl(unrelated,F_SETFD,0)==0);}
  snprintf(setup,sizeof(setup),"{\"revision\":2,\"servers\":[{\"name\":\"stdiofixture\",\"command\":\"/usr/bin/python3\",\"args\":[\"%s/tests/integration/capability_fixture.py\",\"--stdio\"%s],\"tools\":[\"echo\"]}]}",cwd,unrelated>=0?",\"--assert-no-network-sockets\"":"");
  status=control(session,"mcp_configure",setup,&output,&length);if(status)fprintf(stderr,"stdio MCP status %u: %.*s\n",status,(int)length,output);assert(status==0);release(output,length);
  if(unrelated>=0)close(unrelated);
  before=starts;assert(run(session,3,"mcp-fixture stdio")==0);assert(starts>before);
  snprintf(setup,sizeof(setup),"{\"revision\":3,\"servers\":[{\"name\":\"ssefixture\",\"url\":\"http://127.0.0.1:18794/mcp-sse\",\"tools\":[\"echo\"]}]}");
  status=control(session,"mcp_configure",setup,&output,&length);if(status)fprintf(stderr,"SSE MCP status %u: %.*s\n",status,(int)length,output);assert(status==0);release(output,length);
  before=starts;assert(run(session,4,"mcp-fixture SSE")==0);assert(starts>before);destroy(session);
  char denied[4096];snprintf(denied,sizeof(denied),"%s/denied",argv[2]);mkdir(denied,0700);
  config.context=(void*)1;config.workspace=denied;
  session=create(&config);assert(session);assert(run(session,1,"coding-fixture deny")==0);destroy(session);
  snprintf(path,sizeof(path),"%s/agent-result.txt",denied);assert(access(path,F_OK)!=0);
  config.context=NULL;config.workspace=argv[2];
  const struct {unsigned provider,protocol;const char *model;} providers[]={{1,0,"claude-sonnet-4-5"},{3,0,"gemini-2.5-flash"},{2,1,"gpt-4.1-mini"}};
  for(unsigned i=0;i<3;i++){
    config.provider=providers[i].provider;config.protocol=providers[i].protocol;config.model=providers[i].model;
    config.endpoint="http://127.0.0.1:18794";config.request=NULL;
    session=create(&config);assert(session);unsigned before_chunks=chunks;assert(run(session,1,"provider-fixture")==0);assert(chunks>before_chunks);destroy(session);
  }
  printf("PASS: SDK coding/file/sandboxed shell, permissions, checkpoint restore, HTTP/stdio MCP and all provider protocols; %u tool starts\n",starts);
}
