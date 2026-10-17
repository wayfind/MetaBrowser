#ifndef METABROWSER_BROWSER_TOOLS_H_
#define METABROWSER_BROWSER_TOOLS_H_
#include <map>
#include <string>
#include <vector>
#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/values.h"
#include "base/time/time.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/weak_document_ptr.h"
#include "ui/accessibility/ax_node_data.h"
class BrowserWindowInterface;
namespace ui {struct AXTreeUpdate;}
namespace content {class ScopedAccessibilityMode;}
namespace metabrowser {
// UI-sequence only; never exposes renderer pointers to the model.
class BrowserTools {
 public:
  using Reply=base::OnceCallback<void(uint32_t,std::string)>;
  explicit BrowserTools(BrowserWindowInterface* browser);
  ~BrowserTools();
  void Run(std::string name,std::string arguments,Reply reply);
  void Cancel();
  base::WeakPtr<BrowserTools> GetWeakPtr(){return weak_.GetWeakPtr();}
  content::WebContents* ActivePage();
  std::string Context();
  static base::ListValue ToolCatalog();
  static bool IsReadOnly(std::string_view name);
  static bool ValidateArguments(std::string_view name,const base::DictValue& args);
  bool Acquire(const std::string& owner){if(!owner_.empty()&&owner_!=owner)return false;owner_=owner;return true;}
  void Release(const std::string& owner){if(owner_==owner)owner_.clear();}
  bool OwnedBy(const std::string& owner) const{return owner_==owner;}
  uint64_t generation() const { return generation_; }
  content::WebContents* FindPage(std::string_view tab_id);
  bool NavigationReady(content::WebContents* page);
  content::WeakDocumentPtr TargetDocument(const std::string& observation,int target);
 private:
  class NavigationWatch;
  struct Navigation {int64_t id=0;std::string url;};
  void TrackNavigation(content::WebContents* page,const std::string& url);
  struct Target {
    content::WeakDocumentPtr document;
    ui::AXNodeData node;
    std::string frame_id;
  };
  struct Snapshot {
    base::WeakPtr<content::WebContents> page;
    content::WeakDocumentPtr document;
    std::map<int,Target> targets;
    base::ListValue nodes;
    std::string signature;
    base::TimeTicks captured;
    bool consumed=false;
    bool truncated=false;
  };
  void Observe(base::WeakPtr<content::WebContents> page,base::DictValue args,Reply reply);
  void Collected(base::WeakPtr<content::WebContents> page,content::WeakDocumentPtr document,base::DictValue args,Reply reply,ui::AXTreeUpdate& tree);
  void ReadTarget(content::WebContents* page,std::string name,const base::DictValue& args,Reply reply);
  void Invalidate(content::WebContents* page);
  raw_ptr<BrowserWindowInterface> browser_;
  std::map<std::string,std::unique_ptr<content::ScopedAccessibilityMode>> accessibility_;
  std::map<std::string,Snapshot> snapshots_;
  std::map<std::string,std::pair<content::WeakDocumentPtr,int>> refs_;
  int next_ref_=1;
  uint64_t generation_=0;
  std::string owner_;
  uint64_t action_id_=0,pending_action_=0;
  std::map<std::string,Navigation> navigations_;
  std::map<std::string,std::unique_ptr<NavigationWatch>> navigation_watches_;
  base::WeakPtrFactory<BrowserTools> weak_{this};
};
}
#endif
