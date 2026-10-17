// Native Host-owned MCP transport. AgentCore owns negotiation and tool schemas.
#include <metask/agentcore.h>
#include <curl/curl.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
extern char **environ;
extern int mb_mcp_matches(const uint8_t*,size_t,const uint8_t*,size_t);
static pthread_once_t curl_once=PTHREAD_ONCE_INIT;
static void initialize_curl(void){curl_global_init(CURL_GLOBAL_DEFAULT);}
#define LIMIT (8u * 1024 * 1024)
typedef struct {
  _Atomic unsigned refs;
  char **argv;
  char *url, *authorization;
} Definition;
typedef struct {
  Definition *definition;
  int input, output;
  pid_t pid;
  pthread_mutex_t mutex;
  char *pending;
  size_t pending_len;
  char session[1024], version[32];
} Connection;
static int cancelled(const metask_agentcore_mcp_cancellation_v1 *c) {
  return c && c->is_cancelled && c->is_cancelled(c->ctx);
}
static void retain(void *p) { atomic_fetch_add(&((Definition*)p)->refs,1); }
static void release(void *p) {
  Definition *d=p;
  if(atomic_fetch_sub(&d->refs,1)!=1) return;
  if(d->argv) { for(size_t i=0;d->argv[i];i++) free(d->argv[i]); free(d->argv); }
  free(d->url); free(d->authorization); free(d);
}
void *mb_mcp_definition(const char **argv, const char *url, const char *authorization) {
  Definition *d=calloc(1,sizeof(*d)); if(!d)return NULL;
  atomic_init(&d->refs,1);
  if(argv) {
    size_t n=0; while(argv[n])n++;
    d->argv=calloc(n+1,sizeof(char*)); if(!d->argv){release(d);return NULL;}
    for(size_t i=0;i<n;i++) if(!(d->argv[i]=strdup(argv[i]))){release(d);return NULL;}
  }
  if(url && !(d->url=strdup(url))){release(d);return NULL;}
  if(authorization && !(d->authorization=strdup(authorization))){release(d);return NULL;}
  return d;
}
void mb_mcp_definition_release(void *d) { release(d); }
static uint32_t open_connection(void *raw,uint32_t purpose,uint32_t era,uint32_t timeout,void **out) {
  (void)purpose;(void)timeout;
  Definition *d=raw; Connection *c=calloc(1,sizeof(*c)); if(!c)return 6;
  c->definition=d;c->input=c->output=-1;
  pthread_mutex_init(&c->mutex,NULL);
  snprintf(c->version,sizeof(c->version),"%s",era==1?"2026-07-28":era==2?"2025-11-25":"2025-06-18");
  if(d->argv) {
    int in[2],outpipe[2];
    if(pipe(in)){free(c);return 6;}
    if(pipe(outpipe)){close(in[0]);close(in[1]);free(c);return 6;}
    // Do not leak either connection into later MCP children.
    for(int i=0;i<2;i++){fcntl(in[i],F_SETFD,FD_CLOEXEC);fcntl(outpipe[i],F_SETFD,FD_CLOEXEC);}
    posix_spawn_file_actions_t a;posix_spawn_file_actions_init(&a);
    posix_spawn_file_actions_adddup2(&a,in[0],STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&a,outpipe[1],STDOUT_FILENO);
    posix_spawn_file_actions_addopen(&a,STDERR_FILENO,"/dev/null",O_WRONLY,0);
    // A browser owns unrelated sockets/files. MCP children inherit only the
    // descriptors explicitly installed by the stdio file actions above.
    posix_spawnattr_t attributes;
    int status=posix_spawnattr_init(&attributes);
    if(!status){
      status=posix_spawnattr_setflags(&attributes,POSIX_SPAWN_CLOEXEC_DEFAULT);
      if(!status)status=posix_spawnp(&c->pid,d->argv[0],&a,&attributes,d->argv,environ);
      posix_spawnattr_destroy(&attributes);
    }
    posix_spawn_file_actions_destroy(&a);close(in[0]);close(outpipe[1]);
    if(status){close(in[1]);close(outpipe[0]);pthread_mutex_destroy(&c->mutex);free(c);return 5;}
    c->input=in[1];c->output=outpipe[0];
    fcntl(c->input,F_SETFL,O_NONBLOCK);fcntl(c->output,F_SETFL,O_NONBLOCK);
#ifdef F_SETNOSIGPIPE
    fcntl(c->input,F_SETNOSIGPIPE,1);
#endif
  }
  *out=c;return 0;
}
static double monotonic_ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000.0+t.tv_nsec/1e6;}
static int send_line(Connection *c,metask_agentcore_bytes_view_v1 bytes,uint32_t timeout,const metask_agentcore_mcp_cancellation_v1 *cancel) {
  double deadline=monotonic_ms()+timeout;
  for(size_t i=0;i<=bytes.len;) {
    if(cancelled(cancel))return 6;
    if(monotonic_ms()>deadline)return 1;
    struct pollfd f={c->input,POLLOUT,0}; if(poll(&f,1,25)<0 && errno!=EINTR)return 5;
    if(!(f.revents&POLLOUT))continue;
    const void *p=i==bytes.len?(const void*)"\n":bytes.ptr+i;
    size_t left=i==bytes.len?1:bytes.len-i;
    ssize_t n=write(c->input,p,left);if(n>0)i+=(size_t)n;else if(errno!=EAGAIN && errno!=EINTR)return 5;
  }return 0;
}
typedef struct {char *data;size_t len;const metask_agentcore_mcp_cancellation_v1 *cancel;Connection *connection;const uint8_t *request;size_t request_len;int complete;} Capture;
static int select_sse_response(Capture *b){
  if(!b->request||!b->data||(!strstr(b->data,"data:")&&strncmp(b->data,"event:",6)))return 0;
  char *start=b->data;
  while(*start){
    char *end=strstr(start,"\n\n");size_t separator=2;
    char *crlf=strstr(start,"\r\n\r\n");if(crlf&&(!end||crlf<end)){end=crlf;separator=4;}
    if(!end)break;
    size_t size=(size_t)(end-start);char *frame=malloc(size+1);if(!frame)return 0;size_t used=0;
    for(char *line=start;line<end;){
      char *next=memchr(line,'\n',(size_t)(end-line));if(!next)next=end;
      if(next-line>=5&&!strncmp(line,"data:",5)){
        char *text=line+5;if(text<next&&*text==' ')text++;
        char *tail=next;if(tail>text&&tail[-1]=='\r')tail--;
        size_t n=(size_t)(tail-text);memcpy(frame+used,text,n);used+=n;frame[used++]='\n';
      }
      line=next<end?next+1:end;
    }
    frame[used]=0;
    if(used&&mb_mcp_matches((uint8_t*)frame,used,b->request,b->request_len)==1){
      free(b->data);b->data=frame;b->len=used;b->complete=1;return 1;
    }
    free(frame);start=end+separator;
  }
  return 0;
}
static size_t capture(void *p,size_t size,size_t count,void *raw) {
  Capture *b=raw;size_t n=size*count;
  if(n>LIMIT-b->len)return 0;
  char *next=realloc(b->data,b->len+n+1);if(!next)return 0;b->data=next;
  memcpy(next+b->len,p,n);b->len+=n;next[b->len]=0;
  // End a POST SSE response as soon as its correlated result arrives; never
  // wait for a long-lived server stream or confuse a log notification with it.
  if(select_sse_response(b))return 0;
  return n;
}
static int progress(void *raw,curl_off_t a,curl_off_t b,curl_off_t c,curl_off_t d) {
  (void)a;(void)b;(void)c;(void)d;return cancelled(((Capture*)raw)->cancel);
}
static size_t headers(char *p,size_t size,size_t count,void *raw) {
  Connection *c=raw;size_t n=size*count;
  const char *key="Mcp-Session-Id:";size_t k=strlen(key);
  if(n>k && !strncasecmp(p,key,k)) {
    size_t start=k;while(start<n && (p[start]==' '||p[start]=='\t'))start++;
    size_t end=n;while(end>start && (p[end-1]=='\r'||p[end-1]=='\n'))end--;
    if(end-start>=sizeof(c->session))return 0;
    memcpy(c->session,p+start,end-start);c->session[end-start]=0;
  }return n;
}
static uint32_t http_exchange(Connection *c,metask_agentcore_bytes_view_v1 request,uint32_t timeout,const metask_agentcore_mcp_cancellation_v1 *cancel,metask_agentcore_mcp_response_v1 *response) {
  pthread_once(&curl_once,initialize_curl);
  CURL *h=curl_easy_init();if(!h)return 8;
  struct curl_slist *list=NULL;
  list=curl_slist_append(list,"Content-Type: application/json");
  list=curl_slist_append(list,"Accept: application/json, text/event-stream");
  char header[1200];snprintf(header,sizeof(header),"MCP-Protocol-Version: %s",c->version);list=curl_slist_append(list,header);
  if(c->session[0]){snprintf(header,sizeof(header),"Mcp-Session-Id: %s",c->session);list=curl_slist_append(list,header);}
  if(c->definition->authorization)list=curl_slist_append(list,c->definition->authorization);
  Capture body={.cancel=cancel,.connection=c,.request=request.ptr,.request_len=request.len};
  curl_easy_setopt(h,CURLOPT_URL,c->definition->url);
  curl_easy_setopt(h,CURLOPT_HTTPHEADER,list);
  curl_easy_setopt(h,CURLOPT_POSTFIELDS,request.ptr);
  curl_easy_setopt(h,CURLOPT_POSTFIELDSIZE_LARGE,(curl_off_t)request.len);
  curl_easy_setopt(h,CURLOPT_TIMEOUT_MS,(long)timeout);
  curl_easy_setopt(h,CURLOPT_CONNECTTIMEOUT_MS,5000L);
  curl_easy_setopt(h,CURLOPT_FOLLOWLOCATION,0L);
  curl_easy_setopt(h,CURLOPT_NOSIGNAL,1L);
  curl_easy_setopt(h,CURLOPT_WRITEFUNCTION,capture);curl_easy_setopt(h,CURLOPT_WRITEDATA,&body);
  curl_easy_setopt(h,CURLOPT_HEADERFUNCTION,headers);curl_easy_setopt(h,CURLOPT_HEADERDATA,c);
  curl_easy_setopt(h,CURLOPT_NOPROGRESS,0L);curl_easy_setopt(h,CURLOPT_XFERINFOFUNCTION,progress);curl_easy_setopt(h,CURLOPT_XFERINFODATA,&body);
  CURLcode code=curl_easy_perform(h);long status=0;curl_easy_getinfo(h,CURLINFO_RESPONSE_CODE,&status);
  curl_slist_free_all(list);curl_easy_cleanup(h);
  if(code!=CURLE_OK && !(code==CURLE_WRITE_ERROR&&body.complete)){free(body.data);return cancelled(cancel)?6:code==CURLE_OPERATION_TIMEDOUT?1:2;}
  if(status==401||status==403){free(body.data);return 3;}
  // JSON responses or SSE event framing. Correlation is validated by AgentCore.
  if(body.data && !strncmp(body.data,"event:",6)) {
    char *line=strstr(body.data,"data:");
    if(line){line+=5;while(*line==' ')line++;char *end=strchr(line,'\n');if(end)*end=0;size_t n=strlen(line);memmove(body.data,line,n+1);body.len=n;}
  }else if(body.data && !strncmp(body.data,"data:",5)){
    char *line=body.data+5;while(*line==' ')line++;char *end=strchr(line,'\n');if(end)*end=0;size_t n=strlen(line);memmove(body.data,line,n+1);body.len=n;
  }
  response->http_status=(uint32_t)status;response->body.ptr=(uint8_t*)body.data;response->body.len=body.len;return 0;
}
static uint32_t exchange(void *definition,void *connection,metask_agentcore_bytes_view_v1 request,uint32_t timeout,const metask_agentcore_mcp_cancellation_v1 *cancel,metask_agentcore_mcp_response_v1 *response) {
  (void)definition;Connection *c=connection;pthread_mutex_lock(&c->mutex);
  uint32_t result=0;
  if(c->definition->url){result=http_exchange(c,request,timeout,cancel,response);goto done;}
  result=send_line(c,request,timeout,cancel);if(result)goto done;
  double deadline=monotonic_ms()+timeout;
  while(1){
    if(cancelled(cancel)){result=6;break;}
    if(monotonic_ms()>deadline){result=1;break;}
    char *newline=c->pending?memchr(c->pending,'\n',c->pending_len):NULL;
    if(newline){size_t n=(size_t)(newline-c->pending);
      int match=mb_mcp_matches((uint8_t*)c->pending,n,request.ptr,request.len);
      if(match<0){result=8;break;}
      if(!match){memmove(c->pending,newline+1,c->pending_len-n-1);c->pending_len-=n+1;continue;}
      response->body.ptr=malloc(n);if(!response->body.ptr){result=8;break;}
      memcpy(response->body.ptr,c->pending,n);response->body.len=n;
      memmove(c->pending,newline+1,c->pending_len-n-1);c->pending_len-=n+1;break;}
    struct pollfd f={c->output,POLLIN,0};int ready=poll(&f,1,25);if(ready<0 && errno!=EINTR){result=5;break;}if(!ready)continue;
    char chunk[4096];ssize_t n=read(c->output,chunk,sizeof(chunk));if(n==0){result=5;break;}if(n<0){if(errno==EAGAIN||errno==EINTR)continue;result=5;break;}
    if((size_t)n>LIMIT-c->pending_len){result=8;break;}
    char *next=realloc(c->pending,c->pending_len+n);if(!next){result=8;break;}c->pending=next;memcpy(next+c->pending_len,chunk,n);c->pending_len+=(size_t)n;
  }
done:pthread_mutex_unlock(&c->mutex);return result;
}
static uint32_t notify(void *definition,void *connection,metask_agentcore_bytes_view_v1 request,uint32_t timeout,const metask_agentcore_mcp_cancellation_v1 *cancel) {
  (void)definition;Connection *c=connection;pthread_mutex_lock(&c->mutex);
  uint32_t result;
  if(c->definition->url){metask_agentcore_mcp_response_v1 r={0};result=http_exchange(c,request,timeout,cancel,&r);free(r.body.ptr);}else result=send_line(c,request,timeout,cancel);
  pthread_mutex_unlock(&c->mutex);return result?1:0;
}
static uint32_t stream(void *d,void *c,metask_agentcore_bytes_view_v1 request,uint32_t timeout,const metask_agentcore_mcp_cancellation_v1 *cancel,const metask_agentcore_host_result_sink_v1 *sink){
  metask_agentcore_mcp_response_v1 r={.struct_size=sizeof(r)};
  uint32_t status=exchange(d,c,request,timeout,cancel,&r);
  if(status==1||status==2||status==5||r.http_status>=500)status=7;
  else if(r.http_status>=400)status=4;
  if(!status && sink && sink->write){metask_agentcore_bytes_view_v1 bytes={r.body.ptr,r.body.len};if(sink->write(sink->ctx,bytes))status=8;}
  free(r.body.ptr);return status;
}
static void close_connection(void *d,void *connection){
  (void)d;Connection *c=connection;
  if(c->input>=0)close(c->input);if(c->output>=0)close(c->output);
  if(c->pid>0){kill(c->pid,SIGTERM);for(int i=0;i<20;i++){if(waitpid(c->pid,NULL,WNOHANG)!=0){c->pid=0;break;}usleep(10000);}if(c->pid){kill(c->pid,SIGKILL);waitpid(c->pid,NULL,0);}}
  pthread_mutex_destroy(&c->mutex);free(c->pending);free(c);
}
static void release_response(void *d,void *c,metask_agentcore_owned_bytes_v1 *b){(void)d;(void)c;free(b->ptr);b->ptr=NULL;b->len=0;}
void mb_mcp_connector(void *definition,metask_agentcore_mcp_connector_v1 *out){
  *out=(metask_agentcore_mcp_connector_v1){.struct_size=sizeof(*out),.ctx=definition,.open=open_connection,.request=exchange,.request_tool_stream=stream,.notify=notify,.close=close_connection,.release_response=release_response,.retain_connector=retain,.release_connector=release};
}
