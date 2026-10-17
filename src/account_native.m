// Desktop OAuth transport: no web cookies, embedded secret, JWT decoding,
// plaintext credential file, or model-visible account bearer.
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <CommonCrypto/CommonDigest.h>
#include "account_native.h"
#include <curl/curl.h>
#include <arpa/inet.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

static atomic_bool busy, cancelled;
static NSLock *mutex;
static NSMutableDictionary *relays;
static pthread_once_t once=PTHREAD_ONCE_INIT;
static void initialize(void){@autoreleasepool{mutex=[NSLock new];relays=[NSMutableDictionary new];curl_global_init(CURL_GLOBAL_DEFAULT);}}
static void fail(NSString *s){@throw [NSException exceptionWithName:@"Account" reason:s userInfo:nil];}
static NSString *str(id v){return [v isKindOfClass:NSString.class]?v:nil;}
static NSDictionary *dict(id v){return [v isKindOfClass:NSDictionary.class]?v:nil;}
static NSData *json(id o){return [NSJSONSerialization dataWithJSONObject:o options:0 error:nil];}
static NSDictionary *parse(NSData *d){return d.length?dict([NSJSONSerialization JSONObjectWithData:d options:0 error:nil]):nil;}
static NSString *env(const char *name,NSString *fallback){const char *v=getenv(name);return v&&*v?@(v):fallback;}
static NSString *base64url(NSData *d){return [[[[d base64EncodedStringWithOptions:0] stringByReplacingOccurrencesOfString:@"+" withString:@"-"] stringByReplacingOccurrencesOfString:@"/" withString:@"_"] stringByReplacingOccurrencesOfString:@"=" withString:@""];}
static NSString *randomString(void){uint8_t b[32];if(SecRandomCopyBytes(kSecRandomDefault,sizeof(b),b))fail(@"SecureRandomFailed");return base64url([NSData dataWithBytes:b length:sizeof(b)]);}
static NSString *digest(NSString *s){NSData *d=[s dataUsingEncoding:NSUTF8StringEncoding];uint8_t b[32];CC_SHA256(d.bytes,(CC_LONG)d.length,b);return base64url([NSData dataWithBytes:b length:sizeof(b)]);}
static BOOL loopback(NSURL *u){return [@[@"127.0.0.1",@"localhost",@"::1",@"[::1]"] containsObject:u.host.lowercaseString];}
static BOOL safeURL(NSString *s){NSURL *u=[NSURL URLWithString:s?:@""];return u.host.length&&!u.user&&!u.password&&!u.fragment&&([u.scheme isEqual:@"https"]||([u.scheme isEqual:@"http"]&&loopback(u)));}
static NSString *origin(NSString *s){NSURL *u=[NSURL URLWithString:s?:@""];return u.host?[NSString stringWithFormat:@"%@://%@:%@",u.scheme.lowercaseString,u.host.lowercaseString,u.port?:([u.scheme isEqual:@"https"]?@443:@80)]:@"";}
static void emit(MBAccountEvent e,void *ctx,uint32_t kind,id o){if(!e||atomic_load(&cancelled))return;NSData *d=[o isKindOfClass:NSString.class]?[o dataUsingEncoding:NSUTF8StringEncoding]:json(o);e(ctx,kind,d.bytes,d.length);}

@interface MBHTTP:NSObject
@property long status;
@property BOOL ok;
@property NSString *effectiveURL;
@property NSMutableData *data;
@end
@implementation MBHTTP @end
static size_t collect(char *p,size_t n,size_t c,void *raw){NSMutableData *d=(__bridge NSMutableData*)raw;size_t size=n*c;if(d.length+size>2*1024*1024)return 0;[d appendBytes:p length:size];return size;}
static int progress(void *raw,curl_off_t a,curl_off_t b,curl_off_t c,curl_off_t d){return raw&&atomic_load(&cancelled);}
static MBHTTP *httpRequest(NSString *url,NSDictionary *payload,NSString *token,BOOL cancellable,BOOL discovery){
  if(!safeURL(url))fail(@"UnsafeEndpoint");MBHTTP *r=[MBHTTP new];r.data=[NSMutableData new];CURL *c=curl_easy_init();if(!c)fail(@"TransportUnavailable");
  struct curl_slist *h=NULL;h=curl_slist_append(h,"Accept: application/json");NSData *body=payload?json(payload):nil;
  if(body)h=curl_slist_append(h,"Content-Type: application/json");if(token)h=curl_slist_append(h,[[NSString stringWithFormat:@"Authorization: Bearer %@",token] UTF8String]);
  curl_easy_setopt(c,CURLOPT_URL,url.UTF8String);curl_easy_setopt(c,CURLOPT_HTTPHEADER,h);curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,8L);curl_easy_setopt(c,CURLOPT_TIMEOUT,20L);curl_easy_setopt(c,CURLOPT_FOLLOWLOCATION,discovery?1L:0L);
  if(discovery){curl_easy_setopt(c,CURLOPT_MAXREDIRS,5L);curl_easy_setopt(c,CURLOPT_REDIR_PROTOCOLS,[[NSURL URLWithString:url].scheme isEqual:@"https"]?CURLPROTO_HTTPS:(CURLPROTO_HTTP|CURLPROTO_HTTPS));}
  curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,collect);curl_easy_setopt(c,CURLOPT_WRITEDATA,(__bridge void*)r.data);curl_easy_setopt(c,CURLOPT_NOPROGRESS,0L);curl_easy_setopt(c,CURLOPT_XFERINFOFUNCTION,progress);curl_easy_setopt(c,CURLOPT_XFERINFODATA,cancellable?(void*)1:NULL);
  if(body){curl_easy_setopt(c,CURLOPT_POST,1L);curl_easy_setopt(c,CURLOPT_POSTFIELDS,body.bytes);curl_easy_setopt(c,CURLOPT_POSTFIELDSIZE_LARGE,(curl_off_t)body.length);}
  r.ok=curl_easy_perform(c)==CURLE_OK;long status=0;curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&status);r.status=status;char *effective=NULL;curl_easy_getinfo(c,CURLINFO_EFFECTIVE_URL,&effective);r.effectiveURL=effective?@(effective):url;curl_slist_free_all(h);curl_easy_cleanup(c);return r;
}
static MBHTTP *http(NSString *url,NSDictionary *payload,NSString *token,BOOL cancellable){return httpRequest(url,payload,token,cancellable,NO);}
static NSString *oauthError(MBHTTP *r){id e=parse(r.data)[@"error"];return str(e)?:str(dict(e)[@"code"])?:@"OAuthRequestFailed";}
static NSDictionary *success(MBHTTP *r){if(!r.ok)fail(@"NetworkError_NoAutomaticGrantRetry");if(r.status!=200)fail([NSString stringWithFormat:@"%@ (HTTP %ld)",oauthError(r),r.status]);NSDictionary *d=parse(r.data);if(!d)fail(@"InvalidJSONResponse");return d;}

@interface MBAccount:NSObject
@property NSString *root,*site,*client,*vault,*loginID;
@property NSDictionary *metadata;
@end
@implementation MBAccount @end
static MBAccount *configuration(NSString *root){
  MBAccount *a=[MBAccount new];a.root=root;NSDictionary *c=parse([NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"config.json"]]);
  a.site=env("METASK_SITE_URL",str(c[@"site"])?:@"https://app.metask-ai.com");while([a.site hasSuffix:@"/"])a.site=[a.site substringToIndex:a.site.length-1];
  a.client=env("METABROWSER_OAUTH_CLIENT_ID",str(c[@"client_id"])?:@"metabrowser");if(!safeURL(a.site)||!a.client.length)fail(@"InvalidAccountConfiguration");
  a.vault=digest([NSString stringWithFormat:@"%@|%@|%@",root,a.site,a.client]);return a;
}
static void discover(MBAccount *a){
  MBHTTP *reply=httpRequest([a.site stringByAppendingString:@"/.well-known/oauth-authorization-server"],nil,nil,YES,YES);
  NSDictionary *m=success(reply);
  if(!safeURL(reply.effectiveURL)||!safeURL(str(m[@"issuer"]))||![origin(str(m[@"issuer"])) isEqual:origin(reply.effectiveURL)])fail(@"IssuerMismatch");
  NSString *canonicalOrigin=origin(reply.effectiveURL);
  for(NSString *k in @[@"authorization_endpoint",@"token_endpoint",@"revocation_endpoint",@"userinfo_endpoint"])
    if(!safeURL(str(m[k]))||![origin(m[k]) isEqual:canonicalOrigin])fail(@"InvalidDiscoveryEndpoint");
  if(![m[@"code_challenge_methods_supported"] containsObject:@"S256"]||![m[@"token_endpoint_auth_methods_supported"] containsObject:@"none"])fail(@"UnsupportedPublicClient");a.metadata=m;
}
static NSDictionary *vaultQuery(MBAccount *a){return @{(__bridge id)kSecClass:(__bridge id)kSecClassGenericPassword,(__bridge id)kSecAttrService:@"com.metask.metabrowser.oauth",(__bridge id)kSecAttrAccount:a.vault};}
static NSMutableDictionary *load(MBAccount *a){
  NSMutableDictionary *q=[vaultQuery(a) mutableCopy];q[(__bridge id)kSecReturnData]=@YES;q[(__bridge id)kSecMatchLimit]=(__bridge id)kSecMatchLimitOne;CFTypeRef v=NULL;OSStatus s=SecItemCopyMatching((__bridge CFDictionaryRef)q,&v);
  if(s==errSecItemNotFound)return nil;if(s!=errSecSuccess)fail(@"KeychainReadFailed");NSData *d=CFBridgingRelease(v);NSMutableDictionary *r=[parse(d) mutableCopy];if(!r)fail(@"InvalidKeychainRecord");return r;
}
static void clear(MBAccount *a){OSStatus s=SecItemDelete((__bridge CFDictionaryRef)vaultQuery(a));if(s!=errSecSuccess&&s!=errSecItemNotFound)fail(@"KeychainDeleteFailed");}
static void save(MBAccount *a,NSDictionary *r){
  NSDictionary *changes=@{(__bridge id)kSecValueData:json(r)};OSStatus s=SecItemUpdate((__bridge CFDictionaryRef)vaultQuery(a),(__bridge CFDictionaryRef)changes);
  if(s==errSecItemNotFound){NSMutableDictionary *q=[vaultQuery(a) mutableCopy];[q addEntriesFromDictionary:changes];q[(__bridge id)kSecAttrAccessible]=(__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly;s=SecItemAdd((__bridge CFDictionaryRef)q,NULL);}if(s!=errSecSuccess)fail(@"KeychainWriteFailed");
}
// Cross-process lock + in-process mutex order refresh, publication and logout.
static int lockAccount(MBAccount *a){
  [mutex lock];if(![NSFileManager.defaultManager createDirectoryAtPath:a.root withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil]){[mutex unlock];fail(@"AccountDirectoryUnavailable");}
  int fd=open([[a.root stringByAppendingPathComponent:@"oauth.lock"] fileSystemRepresentation],O_CREAT|O_RDWR|O_NOFOLLOW,0600);if(fd<0){[mutex unlock];fail(@"AccountLockUnavailable");}fchmod(fd,0600);
  for(unsigned n=0;flock(fd,LOCK_EX|LOCK_NB);n++){if(n>=1200){close(fd);[mutex unlock];fail(@"AccountBusy");}usleep(25000);}return fd;
}
static void unlockAccount(int fd){flock(fd,LOCK_UN);close(fd);[mutex unlock];}
static BOOL scoped(NSString *s,NSString *v){return [[s componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceCharacterSet] containsObject:v];}
static NSMutableDictionary *tokenRecord(MBAccount *a,NSDictionary *t,NSDictionary *old){
  NSString *access=str(t[@"access_token"]),*refresh=str(t[@"refresh_token"]),*scope=str(t[@"scope"])?:str(old[@"scope"]);double life=[t[@"expires_in"] doubleValue];
  if(!access.length||!refresh.length||![str(t[@"token_type"]).lowercaseString isEqual:@"bearer"]||life<=0||!scoped(scope,@"read"))fail(@"InvalidTokenResponse");
  if(t[@"client_id"]&&![t[@"client_id"] isEqual:a.client])fail(@"TokenClientMismatch");
  NSMutableDictionary *r=old?[old mutableCopy]:[NSMutableDictionary new];r[@"access_token"]=access;r[@"refresh_token"]=refresh;r[@"scope"]=scope;r[@"expires_at"]=@([NSDate date].timeIntervalSince1970+life);r[@"refresh_margin"]=@(MIN(60,life*0.2));
  if(!old)r[@"login_id"]=randomString();
  for(NSString *k in @[@"gateway_url",@"models_url"]){NSString *v=str(t[k])?:str(old[k]);if(!safeURL(v))fail(@"InvalidGatewayURL");r[k]=v;}
  if(![origin(r[@"gateway_url"]) isEqual:origin(r[@"models_url"])])fail(@"InvalidModelsOrigin");
  if(!loopback([NSURL URLWithString:a.site])&&(![[NSURL URLWithString:r[@"gateway_url"]].scheme isEqual:@"https"]||loopback([NSURL URLWithString:r[@"gateway_url"]])))fail(@"InvalidGatewayURL");
  r[@"metadata"]=a.metadata;r[@"issuer"]=a.site;r[@"client_id"]=a.client;return r;
}
static NSMutableDictionary *credentials(MBAccount *a,BOOL force,NSString *stale,NSString *sub){
  int fd=lockAccount(a);@try{NSMutableDictionary *r=load(a);if(!r)fail(@"LoginRequired");if(sub&&(![r[@"sub"] isEqual:sub]||![r[@"login_id"] isEqual:a.loginID]))fail(@"AccountChanged_LoginRequired");
    if(!scoped(str(r[@"scope"]),@"model:invoke"))fail(@"Missing_model:invoke_Reauthorize");
    BOOL different=stale&&![r[@"access_token"] isEqual:stale];
    if((force&&!different)||[r[@"expires_at"] doubleValue]-[r[@"refresh_margin"] doubleValue]<=[NSDate date].timeIntervalSince1970){
      a.metadata=dict(r[@"metadata"]);if(!a.metadata)fail(@"MissingDiscoveryMetadata");MBHTTP *reply=http(a.metadata[@"token_endpoint"],@{@"grant_type":@"refresh_token",@"refresh_token":r[@"refresh_token"],@"client_id":a.client},nil,NO);
      if(!reply.ok||reply.status>=500||[oauthError(reply) isEqual:@"invalid_grant"]){clear(a);fail(@"RefreshUncertainOrExpired_LoginRequired");}
      if(reply.status!=200)success(reply); // Definite configuration errors preserve the grant.
      @try{NSDictionary *t=success(reply);r=tokenRecord(a,t,r);save(a,r);}@catch(NSException *e){clear(a);@throw e;}
    }return r;
  }@finally{unlockAccount(fd);}
}
static NSDictionary *identityAndModels(MBAccount *a,NSMutableDictionary *r){
  MBHTTP *reply=http(a.metadata[@"userinfo_endpoint"],nil,r[@"access_token"],YES);
    if(reply.status==401){NSString *code=oauthError(reply);if([@[@"invalid_token",@"token_expired"] containsObject:code]){r=credentials(a,YES,r[@"access_token"],nil);reply=http(a.metadata[@"userinfo_endpoint"],nil,r[@"access_token"],YES);}else if([@[@"authorization_revoked",@"user_not_found"] containsObject:code]){int fd=lockAccount(a);@try{NSMutableDictionary *current=load(a);if([current[@"access_token"] isEqual:r[@"access_token"]])clear(a);}@finally{unlockAccount(fd);}fail(@"AuthorizationRevoked_LoginRequired");}}
  NSDictionary *user=success(reply);NSString *sub=str(user[@"sub"]);if(!sub.length||![user[@"client_id"] isEqual:a.client]||(r[@"sub"]&&![r[@"sub"] isEqual:sub]))fail(@"IdentityMismatch");r[@"sub"]=sub;r[@"name"]=str(user[@"name"])?:@"";r[@"email"]=str(user[@"email"])?:@"";
  MBHTTP *modelsReply=http(r[@"models_url"],nil,r[@"access_token"],YES);
  if(modelsReply.status==401&&[@[@"invalid_token",@"token_expired"] containsObject:oauthError(modelsReply)]){r=credentials(a,YES,r[@"access_token"],nil);modelsReply=http(r[@"models_url"],nil,r[@"access_token"],YES);}
  NSDictionary *catalog=success(modelsReply);NSMutableArray *models=[NSMutableArray new];
  for(id item in catalog[@"data"]){NSDictionary *m=dict(item);NSString *mid=str(m[@"id"]);if(!mid.length)continue;NSDictionary *endpoints=dict(dict(m[@"capabilities"])[@"endpoints"]);
    for(NSString *kind in @[@"chat_completions",@"messages",@"responses"]){NSDictionary *e=dict(endpoints[kind]);
      // Current production also serves the earlier explicit-boolean schema:
      // modalities are declared at capability level, without endpoint status.
      // Never override an explicit unknown/unsupported status or modality list.
      NSDictionary *caps=dict(m[@"capabilities"]);NSString *status=str(e[@"status"]);
      BOOL textIn=e[@"input"]?[e[@"input"] isKindOfClass:NSArray.class]&&[e[@"input"] containsObject:@"text"]:[dict(dict(caps[@"input"])[@"text"])[@"supported"] isEqual:@YES];
      BOOL textOut=e[@"output"]?[e[@"output"] isKindOfClass:NSArray.class]&&[e[@"output"] containsObject:@"text"]:[dict(dict(caps[@"output"])[@"text"])[@"supported"] isEqual:@YES];
      if(![e[@"supported"] isEqual:@YES]||(e[@"status"]&&![status isEqual:@"supported"])||!textIn||!textOut)continue;
      [models addObject:@{@"id":mid,@"provider":[kind isEqual:@"messages"]?@"anthropic":[kind isEqual:@"responses"]?@"responses":@"openai",@"path":[kind isEqual:@"messages"]?@"/v1/messages":[kind isEqual:@"responses"]?@"/v1/responses":@"/v1/chat/completions"}];break;
    }
  }if(!models.count)fail(@"NoExplicitlySupportedTextModel");r[@"models"]=models;
  int fd=lockAccount(a);@try{NSMutableDictionary *current=load(a);if(![current[@"access_token"] isEqual:r[@"access_token"]])fail(@"AccountChanged_RetryRestore");[current addEntriesFromDictionary:@{@"sub":sub,@"name":r[@"name"],@"email":r[@"email"],@"models":models}];save(a,current);}@finally{unlockAccount(fd);}return r;
}

static int listenLoopback(uint16_t *port){
  int fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)fail(@"LoopbackUnavailable");fcntl(fd,F_SETFD,FD_CLOEXEC);
  struct sockaddr_in addr={.sin_family=AF_INET,.sin_addr.s_addr=htonl(INADDR_LOOPBACK),.sin_port=0};
  if(bind(fd,(struct sockaddr*)&addr,sizeof(addr))||listen(fd,8)){close(fd);fail(@"LoopbackUnavailable");}socklen_t n=sizeof(addr);getsockname(fd,(struct sockaddr*)&addr,&n);*port=ntohs(addr.sin_port);return fd;
}
static BOOL sendAll(int fd,const void *bytes,size_t length){const char *p=bytes;while(length){ssize_t n=send(fd,p,length,0);if(n<=0)return NO;p+=n;length-=n;}return YES;}
static void response(int fd,int status,NSString *body){
  NSData *d=[body dataUsingEncoding:NSUTF8StringEncoding];NSString *h=[NSString stringWithFormat:@"HTTP/1.1 %d Result\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: %lu\r\n\r\n",status,(unsigned long)d.length];sendAll(fd,h.UTF8String,strlen(h.UTF8String));sendAll(fd,d.bytes,d.length);
  // Deliver an error even when rejecting before the request body was read.
  // Closing with unread input otherwise sends RST and discards that response.
  shutdown(fd,SHUT_WR);for(unsigned n=0;n<128;n++){struct pollfd p={fd,POLLIN,0};if(poll(&p,1,10)<=0)break;char b[8192];if(recv(fd,b,sizeof(b),MSG_DONTWAIT)<=0)break;}
}
static NSString *readHead(int fd,NSMutableData *data){
  struct timeval timeout={3,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));int yes=1;setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof(yes));
  while(data.length<16384){char b[1024];ssize_t n=recv(fd,b,sizeof(b),0);if(n<=0)return nil;[data appendBytes:b length:n];NSRange range=[data rangeOfData:[@"\r\n\r\n" dataUsingEncoding:NSUTF8StringEncoding] options:0 range:NSMakeRange(0,data.length)];if(range.location!=NSNotFound)return [[NSString alloc] initWithData:[data subdataWithRange:NSMakeRange(0,range.location+4)] encoding:NSUTF8StringEncoding];}return nil;
}
static NSDictionary *pkce(MBAccount *a,MBAccountEvent event,void *ctx){
  uint16_t port;int listener=listenLoopback(&port);@try{
    NSString *redirect=[NSString stringWithFormat:@"http://localhost:%hu/auth/metask/callback",port],*state=randomString(),*verifier=randomString();NSURLComponents *url=[NSURLComponents componentsWithString:a.metadata[@"authorization_endpoint"]];
    NSMutableArray *items=[url.queryItems mutableCopy]?:[NSMutableArray new];NSDictionary *params=@{@"response_type":@"code",@"client_id":a.client,@"redirect_uri":redirect,@"state":state,@"code_challenge":digest(verifier),@"code_challenge_method":@"S256",@"scope":@"read model:invoke"};
    for(NSString *k in params)[items addObject:[NSURLQueryItem queryItemWithName:k value:params[k]]];url.queryItems=items;emit(event,ctx,6,@{@"uri":url.string,@"code":@"",@"flow":@"pkce"});
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:300];while(deadline.timeIntervalSinceNow>0&&!atomic_load(&cancelled)){
      struct pollfd p={listener,POLLIN,0};if(poll(&p,1,100)<=0)continue;int client=accept(listener,NULL,NULL);if(client<0)continue;
      @try{NSMutableData *bytes=[NSMutableData new];NSString *head=readHead(client,bytes);NSArray *line=[[head componentsSeparatedByString:@"\r\n"].firstObject componentsSeparatedByString:@" "];
        if(line.count!=3||![line[0] isEqual:@"GET"]||![line[1] hasPrefix:@"/"]){response(client,400,@"Invalid callback");continue;}
        NSURLComponents *callback=[NSURLComponents componentsWithString:[@"http://127.0.0.1" stringByAppendingString:line[1]]];NSMutableDictionary *query=[NSMutableDictionary new];BOOL duplicate=NO;
        for(NSURLQueryItem *item in callback.queryItems){if(query[item.name])duplicate=YES;query[item.name]=item.value?:@"";}
        if(duplicate||![callback.path isEqual:@"/auth/metask/callback"]||![query[@"state"] isEqual:state]){response(client,400,@"Invalid callback state");continue;}
        if(query[@"error"]){response(client,200,@"Authorization declined. Return to MetaBrowser.");fail(@"AuthorizationDenied");}
        NSString *code=str(query[@"code"]);if(!code.length){response(client,400,@"Missing code");continue;}response(client,200,@"Authorization received. Return to MetaBrowser.");
        return success(http(a.metadata[@"token_endpoint"],@{@"grant_type":@"authorization_code",@"code":code,@"redirect_uri":redirect,@"client_id":a.client,@"code_verifier":verifier},nil,YES));
      }@finally{close(client);}
    }fail(atomic_load(&cancelled)?@"Cancelled":@"AuthorizationTimedOut");
  }@finally{close(listener);}return nil;
}
static NSDictionary *device(MBAccount *a,MBAccountEvent event,void *ctx){
  NSString *endpoint=str(a.metadata[@"device_authorization_endpoint"]);if(!safeURL(endpoint)||![origin(endpoint) isEqual:origin(a.site)])fail(@"DeviceFlowUnavailable");
  NSDictionary *g=success(http(endpoint,@{@"client_id":a.client,@"scope":@"read model:invoke"},nil,YES));NSString *uri=str(g[@"verification_uri_complete"])?:str(g[@"verification_uri"]);
  if(!safeURL(uri)||![origin(uri) isEqual:origin(a.site)]||!str(g[@"device_code"]).length||!str(g[@"user_code"]).length)fail(@"InvalidDeviceGrant");emit(event,ctx,6,@{@"uri":uri,@"code":g[@"user_code"],@"flow":@"device"});
  double interval=MAX(1,[g[@"interval"] doubleValue]);NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:MIN(1800,[g[@"expires_in"] doubleValue])];
  while(deadline.timeIntervalSinceNow>0&&!atomic_load(&cancelled)){
    NSDate *next=[NSDate dateWithTimeIntervalSinceNow:interval];while(next.timeIntervalSinceNow>0&&deadline.timeIntervalSinceNow>0&&!atomic_load(&cancelled))usleep(100000);if(atomic_load(&cancelled)||deadline.timeIntervalSinceNow<=0)break;
    MBHTTP *r=http(a.metadata[@"token_endpoint"],@{@"grant_type":@"urn:ietf:params:oauth:grant-type:device_code",@"device_code":g[@"device_code"],@"client_id":a.client},nil,YES);
    if(r.ok&&r.status==200)return success(r);NSString *code=oauthError(r);if(r.ok&&r.status==400&&[code isEqual:@"authorization_pending"])continue;if(r.ok&&r.status==400&&[code isEqual:@"slow_down"]){interval+=5;continue;}success(r);
  }fail(atomic_load(&cancelled)?@"Cancelled":@"DeviceGrantExpired");return nil;
}

// One HTTP request can be replayed once on token expiry, before any response
// bytes reach the SDK. The AgentLoop, tool history and browser actions stay put.
@interface MBRelay:NSObject
@property MBAccount *account;
@property NSString *capability,*sub;
@property int listener;
@property uint16_t port;
@end
@implementation MBRelay @end
typedef struct{int fd;long status;BOOL sent,chat;char contentType[128];__unsafe_unretained NSMutableData *error,*pending;}Stream;
static size_t relayHeader(char *p,size_t n,size_t c,void *raw){
  Stream *s=raw;size_t size=n*c;if(size>9&&!strncmp(p,"HTTP/",5)){char *space=memchr(p,' ',size);if(space)s->status=strtol(space+1,NULL,10);}
  if(size>13&&!strncasecmp(p,"Content-Type:",13)){size_t start=13,end=size;while(start<end&&(p[start]==' '||p[start]=='\t'))start++;while(end>start&&(p[end-1]=='\r'||p[end-1]=='\n'))end--;size_t length=MIN(end-start,sizeof(s->contentType)-1);memcpy(s->contentType,p+start,length);s->contentType[length]=0;}
  return size;
}
static BOOL relaySend(Stream *s,NSData *data){
  if(!s->sent){NSString *h=[NSString stringWithFormat:@"HTTP/1.1 200 OK\r\nContent-Type: %s\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",s->contentType[0]?s->contentType:"application/json"];if(!sendAll(s->fd,h.UTF8String,strlen(h.UTF8String)))return NO;s->sent=YES;}
  return sendAll(s->fd,data.bytes,data.length);
}
static size_t relayBody(char *p,size_t n,size_t c,void *raw){
  Stream *s=raw;size_t size=n*c;if(s->status!=200){if(s->error.length+size>2*1024*1024)return 0;[s->error appendBytes:p length:size];return size;}
  if(!s->chat||strncasecmp(s->contentType,"text/event-stream",17))return relaySend(s,[NSData dataWithBytes:p length:size])?size:0;
  // The pinned SDK mistakes any top-level usage key for a usage-only frame.
  // Null contains no accounting data. Omit it, preserving text/tool deltas,
  // actual usage objects, SSE boundaries and every other field unchanged.
  // Combined delta+usage frames are split so the SDK consumes both records.
  if(s->pending.length+size>2*1024*1024)return 0;[s->pending appendBytes:p length:size];NSRange newline;
  while((newline=[s->pending rangeOfData:[NSData dataWithBytes:"\n" length:1] options:0 range:NSMakeRange(0,s->pending.length)]).location!=NSNotFound){
    NSData *line=[s->pending subdataWithRange:NSMakeRange(0,newline.location+1)];[s->pending replaceBytesInRange:NSMakeRange(0,newline.location+1) withBytes:NULL length:0];
    NSString *text=[[NSString alloc] initWithData:line encoding:NSUTF8StringEncoding];
    if([text hasPrefix:@"data:"]){NSMutableDictionary *event=[parse([[text substringFromIndex:5] dataUsingEncoding:NSUTF8StringEncoding]) mutableCopy];
      id usage=event[@"usage"];BOOL combined=dict(usage)&&[event[@"choices"] isKindOfClass:NSArray.class]&&[event[@"choices"] count]>0;
      if(usage==NSNull.null||combined){[event removeObjectForKey:@"usage"];NSMutableData *normalized=[NSMutableData dataWithBytes:"data: " length:6];[normalized appendData:json(event)];[normalized appendBytes:"\n" length:1];
        if(combined){[normalized appendBytes:"\ndata: " length:7];[normalized appendData:json(@{@"choices":@[],@"usage":usage})];[normalized appendBytes:"\n" length:1];}line=normalized;}
    }
    if(!relaySend(s,line))return 0;
  }return size;
}
static int disconnected(void *raw,curl_off_t a,curl_off_t b,curl_off_t c,curl_off_t d){Stream *s=raw;char byte;return recv(s->fd,&byte,1,MSG_PEEK|MSG_DONTWAIT)==0;}
static void relayRequest(MBRelay *relay,int fd){
  NSMutableData *bytes=[NSMutableData new];NSString *head=readHead(fd,bytes);if(!head){response(fd,400,@"Invalid request");return;}NSArray *lines=[head componentsSeparatedByString:@"\r\n"],*request=[lines[0] componentsSeparatedByString:@" "];NSMutableDictionary *headers=[NSMutableDictionary new];BOOL duplicate=NO;
  for(NSString *line in lines){NSRange colon=[line rangeOfString:@":"];if(colon.location==NSNotFound)continue;NSString *key=[[line substringToIndex:colon.location] lowercaseString];if(headers[key])duplicate=YES;headers[key]=[[line substringFromIndex:colon.location+1] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];}
  if(duplicate||request.count!=3||![@[@"GET",@"POST"] containsObject:request[0]]||headers[@"origin"]||headers[@"transfer-encoding"]){response(fd,400,@"Invalid provider request");return;}
  if(![headers[@"authorization"] isEqual:[@"Bearer " stringByAppendingString:relay.capability]]&&![headers[@"x-api-key"] isEqual:relay.capability]){response(fd,401,@"Local capability required");return;}
  NSString *path=request[1];
  if([request[0] isEqual:@"GET"]){
    if(![path isEqual:@"/v1/models"]){response(fd,404,@"Unsupported endpoint");return;}
    NSMutableDictionary *record=credentials(relay.account,NO,nil,relay.sub);
    MBHTTP *reply=http(record[@"models_url"],nil,record[@"access_token"],YES);
    if(reply.status==401&&[@[@"invalid_token",@"token_expired"] containsObject:oauthError(reply)]){record=credentials(relay.account,YES,record[@"access_token"],relay.sub);reply=http(record[@"models_url"],nil,record[@"access_token"],YES);}
    if(reply.status!=200||reply.data.length>1024*1024){response(fd,502,@"Model catalogue unavailable");return;}
    NSDictionary *catalogue=parse(reply.data);NSString *route=headers[@"x-metacodes-model-endpoint"]?:@"messages";
    if(![@[@"chat_completions",@"messages",@"responses"] containsObject:route]){response(fd,400,@"Model endpoint required");return;}
    NSMutableArray *entries=[NSMutableArray new];
    for(NSDictionary *entry in catalogue[@"data"]){
      if(!dict(entry)||!str(entry[@"id"]))continue;
      NSDictionary *caps=dict(entry[@"capabilities"]),*endpoint=dict(dict(caps[@"endpoints"])[route]);
      BOOL supported=[endpoint[@"supported"] isEqual:@YES]&&(!endpoint[@"status"]||[endpoint[@"status"] isEqual:@"supported"]);
      if(!supported)continue;
      BOOL image=endpoint[@"input"]?([endpoint[@"input"] isKindOfClass:NSArray.class]&&[endpoint[@"input"] containsObject:@"image"]):[dict(dict(caps[@"input"])[@"image"])[@"supported"] isEqual:@YES];
      if(dict(caps[@"image_input"])[@"supported"])image=[dict(caps[@"image_input"])[@"supported"] isEqual:@YES]&&image;
      NSMutableDictionary *model=[entry mutableCopy],*capabilities=caps?[caps mutableCopy]:[NSMutableDictionary new];capabilities[@"image_input"]=@{@"supported":@(image)};model[@"capabilities"]=capabilities;[entries addObject:model];
    }
    catalogue=@{@"data":entries};
    // Forward only catalogue metadata: credentials and account state stay in this relay.
    NSData *payload=json(catalogue);
    NSString *head=[NSString stringWithFormat:@"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %lu\r\nConnection: close\r\n\r\n",(unsigned long)payload.length];
    sendAll(fd,head.UTF8String,[head lengthOfBytesUsingEncoding:NSUTF8StringEncoding]);sendAll(fd,payload.bytes,payload.length);return;
  }
  if(![@[@"/v1/chat/completions",@"/v1/messages",@"/v1/responses"] containsObject:path]){response(fd,404,@"Unsupported endpoint");return;}
  NSString *size=headers[@"content-length"];if(!size.length||[size rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet.invertedSet].location!=NSNotFound||size.longLongValue<=0||size.longLongValue>32*1024*1024){response(fd,413,@"Invalid body length");return;}
  NSUInteger length=(NSUInteger)size.longLongValue,offset=[head lengthOfBytesUsingEncoding:NSUTF8StringEncoding];NSMutableData *body=[[bytes subdataWithRange:NSMakeRange(offset,bytes.length-offset)] mutableCopy];
  while(body.length<length){char b[8192];ssize_t n=recv(fd,b,MIN(sizeof(b),length-body.length),0);if(n<=0)return;[body appendBytes:b length:n];}if(body.length!=length){response(fd,400,@"Invalid request body");return;}
  NSString *model=str(parse(body)[@"model"]);if(!model){response(fd,400,@"Missing model");return;}NSMutableDictionary *r=credentials(relay.account,NO,nil,relay.sub);BOOL supported=NO;
  for(NSDictionary *entry in r[@"models"])if([entry[@"id"] isEqual:model]&&[entry[@"path"] isEqual:path])supported=YES;if(!supported){response(fd,400,@"Model endpoint not explicitly supported; restore catalogue");return;}
  for(unsigned attempt=0;attempt<2;attempt++){
    NSMutableData *errors=[NSMutableData new],*pending=[NSMutableData new];Stream stream={.fd=fd,.chat=[path isEqual:@"/v1/chat/completions"],.error=errors,.pending=pending};CURL *c=curl_easy_init();if(!c)fail(@"TransportUnavailable");struct curl_slist *h=NULL;
    h=curl_slist_append(h,"Content-Type: application/json");h=curl_slist_append(h,"Accept: text/event-stream");h=curl_slist_append(h,[[NSString stringWithFormat:@"Authorization: Bearer %@",r[@"access_token"]] UTF8String]);h=curl_slist_append(h,[[NSString stringWithFormat:@"x-api-key: %@",r[@"access_token"]] UTF8String]);if([path isEqual:@"/v1/messages"])h=curl_slist_append(h,"anthropic-version: 2023-06-01");
    NSString *gateway=r[@"gateway_url"];while([gateway hasSuffix:@"/"])gateway=[gateway substringToIndex:gateway.length-1];NSString *target=[gateway stringByAppendingString:path];
    curl_easy_setopt(c,CURLOPT_URL,target.UTF8String);curl_easy_setopt(c,CURLOPT_POST,1L);curl_easy_setopt(c,CURLOPT_POSTFIELDS,body.bytes);curl_easy_setopt(c,CURLOPT_POSTFIELDSIZE_LARGE,(curl_off_t)body.length);curl_easy_setopt(c,CURLOPT_HTTPHEADER,h);curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,8L);curl_easy_setopt(c,CURLOPT_TIMEOUT,600L);curl_easy_setopt(c,CURLOPT_FOLLOWLOCATION,0L);
    curl_easy_setopt(c,CURLOPT_HEADERFUNCTION,relayHeader);curl_easy_setopt(c,CURLOPT_HEADERDATA,&stream);curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,relayBody);curl_easy_setopt(c,CURLOPT_WRITEDATA,&stream);curl_easy_setopt(c,CURLOPT_NOPROGRESS,0L);curl_easy_setopt(c,CURLOPT_XFERINFOFUNCTION,disconnected);curl_easy_setopt(c,CURLOPT_XFERINFODATA,&stream);
    CURLcode code=curl_easy_perform(c);curl_slist_free_all(h);curl_easy_cleanup(c);if(stream.sent){if(pending.length)relaySend(&stream,pending);return;}if(code!=CURLE_OK){response(fd,502,@"Upstream interrupted; request was not replayed");return;}
    MBHTTP *error=[MBHTTP new];error.data=errors;NSString *reason=oauthError(error);
    if(stream.status==401&&attempt==0&&[@[@"invalid_token",@"token_expired"] containsObject:reason]){r=credentials(relay.account,YES,r[@"access_token"],relay.sub);continue;}
    if(stream.status==401&&[@[@"authorization_revoked",@"user_not_found"] containsObject:reason]){int lock=lockAccount(relay.account);@try{if([load(relay.account)[@"sub"] isEqual:relay.sub])clear(relay.account);}@finally{unlockAccount(lock);}}
    response(fd,(int)(stream.status?:502),reason);return;
  }
}
static void *relayThread(void *raw){MBRelay *relay=CFBridgingRelease(raw);for(;;){int fd=accept(relay.listener,NULL,NULL);if(fd<0){if(errno==EINTR)continue;break;}@autoreleasepool{@try{relayRequest(relay,fd);}@catch(NSException *e){response(fd,401,e.reason?:@"LoginRequired");}@finally{close(fd);}}}return NULL;}
static MBRelay *startRelay(MBAccount *a,NSDictionary *record){
  NSString *sub=record[@"sub"];a.loginID=record[@"login_id"];
  @synchronized(relays){NSString *key=[a.vault stringByAppendingFormat:@"|%@",a.loginID];MBRelay *r=relays[key];if(r)return r;r=[MBRelay new];r.account=a;r.sub=sub;r.capability=randomString();uint16_t port;r.listener=listenLoopback(&port);r.port=port;
    pthread_attr_t attr;pthread_attr_init(&attr);pthread_attr_setstacksize(&attr,16*1024*1024);pthread_attr_setdetachstate(&attr,PTHREAD_CREATE_DETACHED);pthread_t thread;void *retained=(void*)CFBridgingRetain(r);int result=pthread_create(&thread,&attr,relayThread,retained);pthread_attr_destroy(&attr);if(result){(void)CFBridgingRelease(retained);close(r.listener);fail(@"ProviderRelayUnavailable");}relays[key]=r;return r;
  }
}
static void ready(MBAccount *a,NSDictionary *r,MBAccountEvent event,void *ctx){MBRelay *relay=startRelay(a,r);NSDictionary *model=[r[@"models"] firstObject];emit(event,ctx,8,@{@"name":r[@"name"]?:@"",@"email":r[@"email"]?:@"",@"sub":r[@"sub"],@"scope":r[@"scope"],@"gateway_url":r[@"gateway_url"],@"models":r[@"models"],@"provider":model[@"provider"],@"model":model[@"id"],@"endpoint":[NSString stringWithFormat:@"http://127.0.0.1:%hu%@",relay.port,model[@"path"]],@"local_capability":relay.capability});}
void mb_account_cancel(void){atomic_store(&cancelled,true);}
uint32_t mb_account_operation(const char *root,uint32_t op,MBAccountEvent event,void *ctx){
  bool expected=false;if(!atomic_compare_exchange_strong(&busy,&expected,true))return 3;pthread_once(&once,initialize);atomic_store(&cancelled,false);
  @autoreleasepool{@try{MBAccount *a=configuration(@(root));
    if(op==2){int fd=lockAccount(a);BOOL revoked=NO;@try{NSMutableDictionary *r=load(a);@try{if(r){a.metadata=dict(r[@"metadata"]);if(a.metadata){MBHTTP *reply=http(a.metadata[@"revocation_endpoint"],@{@"token":r[@"refresh_token"],@"token_type_hint":@"refresh_token",@"client_id":a.client},nil,NO);revoked=reply.ok&&reply.status==200;}}else revoked=YES;}@finally{clear(a);}}@finally{unlockAccount(fd);}emit(event,ctx,10,@{@"signed_out":@YES,@"revoked":@(revoked)});
    }else if(op==1){int fd=lockAccount(a);NSMutableDictionary *r;@try{r=load(a);}@finally{unlockAccount(fd);}if(!r)emit(event,ctx,11,@{});else{a.metadata=dict(r[@"metadata"]);r=credentials(a,NO,nil,nil);ready(a,identityAndModels(a,r),event,ctx);}
    }else if(op==0||op==3){discover(a);NSDictionary *t=op==3?device(a,event,ctx):pkce(a,event,ctx);NSMutableDictionary *r=tokenRecord(a,t,nil);if(atomic_load(&cancelled))fail(@"Cancelled");int fd=lockAccount(a);@try{save(a,r);}@finally{unlockAccount(fd);}ready(a,identityAndModels(a,r),event,ctx);
    }else fail(@"UnknownAccountOperation");atomic_store(&busy,false);return 0;
  }@catch(NSException *e){emit(event,ctx,9,e.reason?:@"AccountError");atomic_store(&busy,false);return 1;}}
}
