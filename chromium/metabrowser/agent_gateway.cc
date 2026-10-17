#include "metabrowser/agent_gateway.h"
#include "metabrowser/browser_tools.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/base64.h"
#include "base/strings/string_util.h"
#include "base/strings/string_split.h"
#include "base/strings/string_number_conversions.h"
#include <map>
#include <optional>
#include <string_view>
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/threading/thread.h"
#include "base/uuid.h"
#include "net/base/ip_address.h"
#include "net/base/ip_endpoint.h"
#include "net/base/net_errors.h"
#include "net/log/net_log_source.h"
#include "net/server/http_server.h"
#include "net/server/http_server_request_info.h"
#include "net/server/http_server_response_info.h"
#include "net/socket/tcp_server_socket.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
namespace metabrowser {
namespace {
constexpr auto annotation=net::DefineNetworkTrafficAnnotation("metabrowser_local_a2a",R"(
semantics { sender: "MetaBrowser local agent gateway" description: "Returns task status and explicitly requested agent output to authenticated local clients." trigger: "User enables the local agent gateway." data: "Task messages, status and output." destination: LOCAL }
policy { cookies_allowed: NO setting: "Enabled only with explicit local port and token configuration." policy_exception_justification: "Local development gateway." }
)");
constexpr size_t kMaxMcpResponseBytes=5*1024*1024;
std::string Id(){return base::Uuid::GenerateRandomV4().AsLowercaseString();}
bool Accepts(std::string_view header,std::string_view type){
  for(auto entry:base::SplitStringPiece(header,",",base::TRIM_WHITESPACE,base::SPLIT_WANT_NONEMPTY)){
    auto parts=base::SplitStringPiece(entry,";",base::TRIM_WHITESPACE,base::SPLIT_WANT_NONEMPTY);
    if(parts.empty()||!base::EqualsCaseInsensitiveASCII(parts[0],type))continue;
    double quality=1;
    for(size_t i=1;i<parts.size();++i){
      const auto equal=parts[i].find('=');
      if(equal!=std::string_view::npos&&base::EqualsCaseInsensitiveASCII(
          base::TrimWhitespaceASCII(parts[i].substr(0,equal),base::TRIM_ALL),"q")){
        if(!base::StringToDouble(base::TrimWhitespaceASCII(parts[i].substr(equal+1),base::TRIM_ALL),&quality))quality=0;
      }
    }
    if(quality>0&&quality<=1)return true;
  }
  return false;
}
}
class AgentGateway::Server:public base::RefCountedThreadSafe<Server>,public net::HttpServer::Delegate {
 public:
  Server(unsigned port,std::string token,Submit submit,Cancel cancel,Execute execute,CancelTool cancel_tool):port_(port),token_(std::move(token)),submit_(std::move(submit)),cancel_(std::move(cancel)),execute_(std::move(execute)),cancel_tool_(std::move(cancel_tool)),ui_(base::SequencedTaskRunner::GetCurrentDefault()){}
  void Start(){
    static base::Thread* thread=[] {auto* t=new base::Thread("MetaBrowser A2A");base::Thread::Options options;options.message_pump_type=base::MessagePumpType::IO;CHECK(t->StartWithOptions(std::move(options)));return t;}();
    io_=thread->task_runner();io_->PostTask(FROM_HERE,base::BindOnce(&Server::Listen,base::RetainedRef(this)));
  }
  void Stop(){if(io_)io_->PostTask(FROM_HERE,base::BindOnce(&Server::Close,base::RetainedRef(this)));}
 private:
  friend class base::RefCountedThreadSafe<Server>;
  ~Server() override=default;
  struct Task {std::string id,context,state="TASK_STATE_WORKING",text,prompt;bool cancel_requested=false;};
  void Listen(){
    auto socket=std::make_unique<net::TCPServerSocket>(nullptr,net::NetLogSource());
    if(port_==0||port_>65535||token_.size()<32)return;
    if(socket->Listen(net::IPEndPoint(net::IPAddress::IPv4Localhost(),port_),16,std::nullopt)!=net::OK)return;
    callback_target_=std::make_shared<CallbackTarget>(CallbackTarget{this});
    http_=std::make_unique<net::HttpServer>(std::move(socket),this);
  }
  void Close(){
    // Invalidate completion targets on IO before releasing transport state.
    // A native callback may outlive the window but must not retain this server.
    callback_target_.reset();tool_timer_.reset();
    if(pending_&&!pending_->abandoned&&!cancel_tool_.is_null())ui_->PostTask(FROM_HERE,base::BindOnce(cancel_tool_));
    pending_.reset();sessions_.clear();http_.reset();submit_.Reset();cancel_.Reset();execute_.Reset();cancel_tool_.Reset();
  }
  void OnConnect(int id) override {
    http_->SetReceiveBufferSize(id,1024*1024);
    // HttpServer's default send buffer is too small for native PNG responses.
    http_->SetSendBufferSize(id,kMaxMcpResponseBytes+8192);
  }
  void OnClose(int connection) override {
    if(pending_&&pending_->connection==connection)AbortCall("unknown","Client disconnected; cancellation requested",false);
  }
  void OnWebSocketRequest(int id,const net::HttpServerRequestInfo&) override {http_->Close(id);}
  void OnWebSocketMessage(int id,std::string) override {http_->Close(id);}
  base::DictValue TaskValue(const Task& task){
    base::DictValue value;value.Set("id",task.id);value.Set("contextId",task.context);value.Set("status",base::DictValue().Set("state",task.state));
    value.Set("metadata",base::DictValue().Set("cancelRequested",task.cancel_requested).Set("completionScope","agent-turn").Set("businessOutcomeVerified",false));
    if(!task.text.empty())value.Set("artifacts",base::ListValue().Append(base::DictValue().Set("artifactId",task.id+"-response").Set("name","Agent response").Set("parts",base::ListValue().Append(base::DictValue().Set("text",task.text)))));
    return value;
  }
  void Send(int id,net::HttpStatusCode status,base::DictValue value){
    net::HttpServerResponseInfo response(status);response.SetBody(base::WriteJson(value).value_or("{}"),"application/json");response.AddHeader("Cache-Control","no-store");http_->SendResponse(id,response,annotation);
  }
  void Error(int connection,const base::Value& id,int code,std::string message){Send(connection,net::HTTP_OK,base::DictValue().Set("jsonrpc","2.0").Set("id",id.Clone()).Set("error",base::DictValue().Set("code",code).Set("message",message)));}
  void UpdateTask(std::string id,std::string state,std::string text){
    auto it=tasks_.find(id);if(it==tasks_.end())return;
    if(it->second.state=="TASK_STATE_CANCELED")return;
    it->second.state=state;
    if(active_task_==id&&(state=="TASK_STATE_COMPLETED"||state=="TASK_STATE_FAILED"||state=="TASK_STATE_REJECTED"||state=="TASK_STATE_CANCELED"))active_task_.clear();
    if(text.size()<=1024*1024-it->second.text.size())it->second.text+=text;
  }
  // The native catalogue and recursive validator are the single policy surface.
  base::ListValue McpCatalog(){return BrowserTools::ToolCatalog();}
  base::DictValue ToolError(std::string status,std::string reason){
    auto payload=base::DictValue().Set("status",status).Set("reason",reason)
        .Set("outcome","unconfirmed").Set("business_outcome_verified",false);
    return base::DictValue().Set("isError",true).Set("content",base::ListValue().Append(
        base::DictValue().Set("type","text").Set("text",base::WriteJson(payload).value_or("{}"))));
  }
  void McpSend(int connection,net::HttpStatusCode status,base::DictValue value,
               const std::string& session=std::string()){
    if(!http_)return;
    net::HttpServerResponseInfo response(status);
    if(status!=net::HTTP_NO_CONTENT){
      auto encoded=status==net::HTTP_ACCEPTED?std::make_optional(std::string()):base::WriteJson(value);
      // Bound the serialized envelope too: text escaping can expand native JSON.
      if(!encoded||encoded->size()>kMaxMcpResponseBytes){
        value.Remove("result");value.Remove("error");
        value.Set("result",ToolError("unknown","Serialized response exceeded 5 MiB; reconcile before retrying"));
        encoded=base::WriteJson(value);
      }
      response.SetBody(encoded.value_or("{}"),"application/json");
    }
    response.AddHeader("Cache-Control","no-store");
    if(status==net::HTTP_METHOD_NOT_ALLOWED)response.AddHeader("Allow","POST, DELETE");
    if(!session.empty())response.AddHeader("Mcp-Session-Id",session);
    http_->SendResponse(connection,response,annotation);
  }
  void McpResult(int connection,const base::Value& id,base::DictValue result,
                 const std::string& session){
    McpSend(connection,net::HTTP_OK,base::DictValue().Set("jsonrpc","2.0")
        .Set("id",id.Clone()).Set("result",std::move(result)),session);
  }
  void AbortCall(std::string status,std::string reason,bool respond){
    if(!pending_||pending_->abandoned)return;
    pending_->abandoned=true;
    if(tool_timer_)tool_timer_->Stop();
    if(respond&&http_)McpResult(pending_->connection,pending_->id,
        ToolError(std::move(status),std::move(reason)),pending_->session);
    // Retain ownership until the native completion callback acknowledges cleanup.
    // This prevents cancellation from racing another session's direct request.
    ui_->PostTask(FROM_HERE,base::BindOnce(cancel_tool_));
  }
  void ToolDone(std::string generation,uint32_t status,std::string text){
    if(!pending_||pending_->generation!=generation)return;
    // Completion releases ownership BEFORE sending: a synchronous connection
    // close from SendResponse must never cancel a completed native request.
    auto completed=std::move(pending_);
    if(tool_timer_)tool_timer_->Stop();
    if(completed->abandoned||!http_)return;
    base::DictValue result;
    if(text.size()>kMaxMcpResponseBytes){
      result=ToolError("unknown","Native result exceeded 5 MiB; reconcile before retrying");
    }else if(!base::IsStringUTF8(text)){
      result=ToolError("unknown","Native result was not valid UTF-8; reconcile before retrying");
    }else{
      auto native=base::JSONReader::ReadDict(text,base::JSON_PARSE_RFC);
      const auto* type=native?native->FindString("type"):nullptr;
      if(!status&&type&&*type=="image"){
        const auto* mime=native->FindString("media_type");
        const auto* data=native->FindString("data");
        std::string decoded;
        if(!mime||(*mime!="image/png"&&*mime!="image/jpeg"&&*mime!="image/webp"&&*mime!="image/gif")||
            !data||data->empty()||!base::Base64Decode(*data,&decoded)||decoded.size()>3*1024*1024){
          result=ToolError("unknown","Invalid or oversized native image");
        }else{
          base::ListValue content;
          content.Append(base::DictValue().Set("type","image").Set("mimeType",*mime).Set("data",*data));
          // Do not duplicate base64 in the accompanying document/viewport metadata.
          native->Remove("data");
          content.Append(base::DictValue().Set("type","text").Set("text",base::WriteJson(*native).value_or("{}")));
          result.Set("isError",false);result.Set("content",std::move(content));
        }
      }else if(status&&!native){
        result=ToolError("unknown",std::move(text));
      }else{
        result.Set("isError",status!=0);result.Set("content",base::ListValue().Append(
            base::DictValue().Set("type","text").Set("text",std::move(text))));
      }
    }
    McpResult(completed->connection,completed->id,std::move(result),completed->session);
  }
  void ToolTimeout(std::string generation){
    if(pending_&&pending_->generation==generation)AbortCall("timeout","Tool deadline exceeded; cancellation requested",true);
  }
  void McpRequest(int connection,const net::HttpServerRequestInfo& request){
    if(execute_.is_null()||cancel_tool_.is_null()){
      Send(connection,net::HTTP_NOT_FOUND,base::DictValue().Set("error","MCP is not enabled"));return;
    }
    // Reject DNS rebinding/alternate authorities, even with a valid bearer.
    const auto host=request.headers.find("host");
    if(host==request.headers.end()||host->second!="127.0.0.1:"+std::to_string(port_)){
      Send(connection,net::HTTP_FORBIDDEN,base::DictValue().Set("error","Invalid local authority"));return;
    }
    if(request.method!="POST"&&request.method!="DELETE"){
      McpSend(connection,net::HTTP_METHOD_NOT_ALLOWED,base::DictValue().Set("error","SSE and server initiated requests are not supported"));return;
    }
    const auto sid=request.headers.find("mcp-session-id");
    auto session=sid==request.headers.end()?sessions_.end():sessions_.find(sid->second);
    if(sid!=request.headers.end()&&session==sessions_.end()){
      Send(connection,net::HTTP_NOT_FOUND,base::DictValue().Set("error","Unknown MCP session"));return;
    }
    if(request.method=="DELETE"){
      if(session==sessions_.end()){Send(connection,net::HTTP_BAD_REQUEST,base::DictValue().Set("error","Session required"));return;}
      if(pending_&&pending_->session==session->first)AbortCall("cancelled","Session terminated; cancellation requested",true);
      sessions_.erase(session);McpSend(connection,net::HTTP_NO_CONTENT,base::DictValue());return;
    }
    const auto content=request.headers.find("content-type");
    if(content==request.headers.end()||
        !base::EqualsCaseInsensitiveASCII(base::TrimWhitespaceASCII(content->second.substr(0,content->second.find(';')),base::TRIM_ALL),"application/json")||
        request.data.size()>128*1024){
      Send(connection,net::HTTP_BAD_REQUEST,base::DictValue().Set("error","Bounded application/json body required"));return;
    }
    const auto accept=request.headers.find("accept");
    if(accept==request.headers.end()||!Accepts(accept->second,"application/json")||!Accepts(accept->second,"text/event-stream")){
      McpSend(connection,net::HTTP_NOT_ACCEPTABLE,base::DictValue().Set("error","Accept application/json and text/event-stream required"));return;
    }
    auto parsed=base::JSONReader::Read(request.data,base::JSON_PARSE_RFC);const base::Value empty;
    if(!parsed){Error(connection,empty,-32700,"Parse error");return;}
    const auto* rpc=parsed->is_dict()?&parsed->GetDict():nullptr;
    const auto* id=rpc?rpc->Find("id"):nullptr;
    const auto* method=rpc?rpc->FindString("method"):nullptr;
    const auto* version=rpc?rpc->FindString("jsonrpc"):nullptr;
    if(!rpc||!method||!version||*version!="2.0"||(id&&!id->is_int()&&!id->is_string())){
      Error(connection,empty,-32600,"Invalid MCP request");return;
    }
    const auto* params=rpc->FindDict("params");
    if(rpc->contains("params")&&!params){
      if(id)Error(connection,*id,-32602,"Object params required");
      else McpSend(connection,net::HTTP_ACCEPTED,base::DictValue());
      return;
    }
    if(*method=="initialize"){
      if(!id){McpSend(connection,net::HTTP_ACCEPTED,base::DictValue());return;}
      if(session!=sessions_.end()||!params||!params->FindString("protocolVersion")||!params->FindDict("capabilities")||!params->FindDict("clientInfo")){
        Error(connection,id?*id:empty,-32602,"Fresh initialize with client information required");return;
      }
      // Negotiate a deliberately pinned Streamable HTTP protocol version.
      for(auto it=sessions_.begin();it!=sessions_.end();){
        if((!pending_||pending_->session!=it->first)&&base::TimeTicks::Now()-it->second.touched>base::Minutes(30))it=sessions_.erase(it);else ++it;
      }
      if(sessions_.size()>=32){Error(connection,*id,-32000,"Session limit exceeded");return;}
      const std::string key=Id();sessions_.emplace(key,McpSession{false,base::TimeTicks::Now()});
      McpResult(connection,*id,base::DictValue().Set("protocolVersion","2025-03-26")
          .Set("capabilities",base::DictValue().Set("tools",base::DictValue().Set("listChanged",false)))
          .Set("serverInfo",base::DictValue().Set("name","MetaBrowser native tools").Set("version","0.1.0")),key);return;
    }
    if(session==sessions_.end()){Send(connection,net::HTTP_BAD_REQUEST,base::DictValue().Set("error","Mcp-Session-Id required"));return;}
    session->second.touched=base::TimeTicks::Now();
    const auto protocol=request.headers.find("mcp-protocol-version");
    if(protocol!=request.headers.end()&&protocol->second!="2025-03-26"){
      Send(connection,net::HTTP_BAD_REQUEST,base::DictValue().Set("error","Unsupported MCP protocol version"));return;
    }
    if(!id){
      if(*method=="notifications/initialized")session->second.initialized=true;
      if(*method=="notifications/cancelled"&&params&&pending_&&pending_->session==session->first){
        const auto* target=params->Find("requestId");
        if(target&&*target==pending_->id)AbortCall("cancelled","Client requested cancellation",true);
      }
      McpSend(connection,net::HTTP_ACCEPTED,base::DictValue());return;
    }
    if(!session->second.initialized){Error(connection,*id,-32000,"Initialization notification required");return;}
    if(*method=="ping"){McpResult(connection,*id,base::DictValue(),session->first);return;}
    if(*method=="tools/list"){
      if(params&&!params->empty()){Error(connection,*id,-32602,"Pagination is not supported");return;}
      McpResult(connection,*id,base::DictValue().Set("tools",McpCatalog()),session->first);return;
    }
    if(*method!="tools/call"){Error(connection,*id,-32601,"Method not found");return;}
    if(pending_){Error(connection,*id,-32000,"Native direct tool lane is busy");return;}
    const auto* name=params?params->FindString("name"):nullptr;
    const auto* arguments=params?params->FindDict("arguments"):nullptr;
    const base::DictValue no_args;
    if(!arguments&&params&&params->contains("arguments")){Error(connection,*id,-32602,"Object arguments required");return;}
    if(!arguments)arguments=&no_args;
    if(!name||!BrowserTools::ValidateArguments(*name,*arguments)){
      Error(connection,*id,-32602,"Unknown tool or invalid typed arguments");return;
    }
    pending_=std::make_unique<PendingCall>(PendingCall{connection,session->first,id->Clone(),Id(),false});
    const auto generation=pending_->generation;
    auto done=base::BindOnce([](scoped_refptr<base::SequencedTaskRunner> io,
        std::weak_ptr<CallbackTarget> target,std::string generation,uint32_t status,std::string text){
      // Lock/access the target ONLY on IO; Close resets its sole persistent owner
      // on that same sequence, so it cannot race dereferencing the server.
      io->PostTask(FROM_HERE,base::BindOnce([](std::weak_ptr<CallbackTarget> target,
          std::string generation,uint32_t status,std::string text){
        if(auto live=target.lock())live->server->ToolDone(std::move(generation),status,std::move(text));
      },std::move(target),std::move(generation),status,std::move(text)));
    },io_,std::weak_ptr<CallbackTarget>(callback_target_),generation);
    ui_->PostTask(FROM_HERE,base::BindOnce(execute_,*name,base::WriteJson(*arguments).value_or("{}"),std::move(done)));
    if(!tool_timer_)tool_timer_=std::make_unique<base::OneShotTimer>();
    tool_timer_->Start(FROM_HERE,base::Seconds(60),base::BindOnce(&Server::ToolTimeout,base::Unretained(this),generation));
  }
  void OnHttpRequest(int connection,const net::HttpServerRequestInfo& request) override {
    if(!http_)return;
    // HTTP/1 pipelining cannot interleave a held tool response with another RPC.
    if(pending_&&!pending_->abandoned&&pending_->connection==connection){http_->Close(connection);return;}
    // CORS is deliberately absent. Browser origins cannot use this local capability.
    if(request.headers.contains("origin")){Send(connection,net::HTTP_FORBIDDEN,base::DictValue().Set("error","Browser-origin requests are not accepted"));return;}
    if(request.path=="/.well-known/agent-card.json"&&request.method=="GET"){
      const auto url="http://127.0.0.1:"+std::to_string(port_)+"/a2a";
      auto card=base::JSONReader::ReadDict(R"({"name":"MetaBrowser","description":"Native browser and MetaCodes workspace agent. Actions retain local user authorization.","version":"0.1.0","supportedInterfaces":[],"capabilities":{"streaming":false,"pushNotifications":false},"defaultInputModes":["text/plain"],"defaultOutputModes":["text/plain"],"securitySchemes":{"localBearer":{"httpAuthSecurityScheme":{"scheme":"bearer"}}},"securityRequirements":[{"schemes":{"localBearer":{"list":[]}}}],"skills":[{"id":"browser-workspace","name":"Browser and workspace tasks","description":"Delegate a task to the visible browser agent","tags":["browser","coding"]}]})",base::JSON_PARSE_RFC);
      card->Set("supportedInterfaces",base::ListValue().Append(base::DictValue().Set("url",url).Set("protocolBinding","JSONRPC").Set("protocolVersion","1.0")));
      Send(connection,net::HTTP_OK,std::move(*card));return;
    }
    const auto auth=request.headers.find("authorization");
    if(auth==request.headers.end()||auth->second!="Bearer "+token_){Send(connection,net::HTTP_UNAUTHORIZED,base::DictValue().Set("error","Authentication required"));return;}
    if(request.path=="/mcp"){McpRequest(connection,request);return;}
    if(request.path!="/a2a"||request.method!="POST"){Send(connection,net::HTTP_NOT_FOUND,base::DictValue().Set("error","Not found"));return;}
    auto rpc=base::JSONReader::ReadDict(request.data,base::JSON_PARSE_RFC);const base::Value empty;
    const auto* id=rpc?rpc->Find("id"):nullptr;const auto* jsonrpc=rpc?rpc->FindString("jsonrpc"):nullptr;
    if(!rpc||!id||!jsonrpc||*jsonrpc!="2.0"||(!id->is_string()&&!id->is_int()&&!id->is_double()&&!id->is_none())){Error(connection,empty,-32600,"Invalid request");return;}
    const auto version=request.headers.find("a2a-version");if(version==request.headers.end()||version->second!="1.0"){Error(connection,*id,-32009,"Only explicit A2A-Version: 1.0 is supported");return;}
    const auto* method=rpc->FindString("method");const auto* params=rpc->FindDict("params");
    if(!method||!params){Error(connection,*id,-32602,"Missing method or params");return;}
    base::DictValue result;
    if(*method=="SendMessage"){
      const auto* message=params->FindDict("message");const auto* parts=message?message->FindList("parts"):nullptr;const auto* message_id=message?message->FindString("messageId"):nullptr;
      if(!message||!parts||!message_id||message_id->empty()||message_id->size()>128||message->FindString("role")==nullptr||*message->FindString("role")!="ROLE_USER"){Error(connection,*id,-32602,"Text user message and messageId required");return;}
      if(message->contains("taskId")||message->contains("contextId")){Error(connection,*id,-32602,"This endpoint currently accepts new tasks only");return;}
      std::string prompt;for(const auto& part:*parts){if(!part.is_dict()||!part.GetDict().FindString("text")){Error(connection,*id,-32602,"Only text parts are supported");return;}prompt+=*part.GetDict().FindString("text");prompt+="\n";}
      if(prompt.find_first_not_of(" \t\r\n")==std::string::npos||prompt.size()>65536){Error(connection,*id,-32602,"Invalid task input");return;}
      auto duplicate=messages_.find(*message_id);
      if(duplicate!=messages_.end()){
        const auto& task=tasks_.at(duplicate->second);if(task.prompt!=prompt){Error(connection,*id,-32602,"messageId was already used for different content");return;}
        result.Set("task",TaskValue(task));
      }
      else{
        if(!active_task_.empty()){Error(connection,*id,-32000,"Another task is active");return;}
        if(prompt.empty()||prompt.size()>65536||tasks_.size()>=64){Error(connection,*id,-32602,"Task or input limit exceeded");return;}
        Task task;task.id=Id();task.context=Id();task.prompt=prompt;const auto task_id=task.id;tasks_.emplace(task_id,task);messages_[*message_id]=task_id;active_task_=task_id;
        auto update=base::BindRepeating([](scoped_refptr<base::SequencedTaskRunner> io,
            std::weak_ptr<CallbackTarget> target,std::string task_id,std::string state,std::string text){
          io->PostTask(FROM_HERE,base::BindOnce([](std::weak_ptr<CallbackTarget> target,
              std::string task_id,std::string state,std::string text){
            if(auto live=target.lock())live->server->UpdateTask(std::move(task_id),std::move(state),std::move(text));
          },std::move(target),std::move(task_id),std::move(state),std::move(text)));
        },io_,std::weak_ptr<CallbackTarget>(callback_target_),task_id);
        ui_->PostTask(FROM_HERE,base::BindOnce(submit_,std::move(prompt),std::move(update)));result.Set("task",TaskValue(task));
      }
    }else if(*method=="GetTask"||*method=="CancelTask"){
      const auto* key=params->FindString("id");auto it=key?tasks_.find(*key):tasks_.end();if(it==tasks_.end()){Error(connection,*id,-32001,"Task not found");return;}
      if(*method=="CancelTask"){
        if(it->second.state!="TASK_STATE_WORKING"&&it->second.state!="TASK_STATE_INPUT_REQUIRED"){Error(connection,*id,-32002,"Task is not cancelable");return;}
        // Only the active task is allowed to cancel the visible session.
        if(active_task_!=it->second.id){Error(connection,*id,-32002,"Task is not active");return;}
        ui_->PostTask(FROM_HERE,base::BindOnce(cancel_));it->second.cancel_requested=true;
      }
      result=TaskValue(it->second);
    }else if(*method=="ListTasks"){
      if(!params->empty()){Error(connection,*id,-32602,"Filtered listing is not supported by this local endpoint");return;}
      base::ListValue tasks;for(const auto& [key,task]:tasks_)tasks.Append(TaskValue(task));result.Set("tasks",std::move(tasks));result.Set("nextPageToken","");result.Set("pageSize",static_cast<int>(tasks_.size()));result.Set("totalSize",static_cast<int>(tasks_.size()));
    }else{Error(connection,*id,-32601,"Operation not supported; streaming and push are not advertised");return;}
    Send(connection,net::HTTP_OK,base::DictValue().Set("jsonrpc","2.0").Set("id",id->Clone()).Set("result",std::move(result)));
  }
  unsigned port_;std::string token_;Submit submit_;Cancel cancel_;
  Execute execute_;CancelTool cancel_tool_;
  struct McpSession {bool initialized=false; base::TimeTicks touched;};
  struct PendingCall {
    int connection;std::string session; base::Value id;std::string generation;
    bool abandoned=false;
  };
  std::map<std::string,McpSession> sessions_;
  std::unique_ptr<PendingCall> pending_;
  struct CallbackTarget {raw_ptr<Server> server;};
  std::shared_ptr<CallbackTarget> callback_target_;
  std::unique_ptr<base::OneShotTimer> tool_timer_;

  scoped_refptr<base::SequencedTaskRunner> ui_,io_;
  std::unique_ptr<net::HttpServer> http_;
  std::map<std::string,Task> tasks_;
  std::map<std::string,std::string> messages_;
  std::string active_task_;
};
AgentGateway::AgentGateway(unsigned port,std::string token,Submit submit,Cancel cancel,Execute execute,CancelTool cancel_tool){server_=base::MakeRefCounted<Server>(port,std::move(token),std::move(submit),std::move(cancel),std::move(execute),std::move(cancel_tool));server_->Start();}
AgentGateway::~AgentGateway(){server_->Stop();}
}
