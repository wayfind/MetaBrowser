#ifndef METABROWSER_AGENT_GATEWAY_H_
#define METABROWSER_AGENT_GATEWAY_H_
#include <memory>
#include <cstdint>
#include <string>
#include "base/functional/callback.h"
#include "base/memory/ref_counted.h"
#include "base/task/sequenced_task_runner.h"
namespace metabrowser {
// Local A2A and optional MCP endpoints. No SDK handles or credential APIs.
class AgentGateway {
 public:
  using Update=base::RepeatingCallback<void(std::string,std::string)>;
  using Submit=base::RepeatingCallback<void(std::string,Update)>;
  using Cancel=base::RepeatingClosure;
  // Execute runs on UI sequence, must authorize through native UI before any
  // mutation and use the visible view's BrowserTools. Completion is mandatory,
  // including after CancelTool; status 0 means transport/tool execution success,
  // not verified business success. Never route cancellation to an SDK run.
  using Execute=base::RepeatingCallback<void(std::string,std::string,
      base::OnceCallback<void(uint32_t,std::string)>)>;
  using CancelTool=base::RepeatingClosure;
  AgentGateway(unsigned port,std::string token,Submit submit,Cancel cancel,
               Execute execute=Execute(),CancelTool cancel_tool=CancelTool());
  ~AgentGateway();
 private:
  class Server;
  scoped_refptr<Server> server_;
};
}
#endif
