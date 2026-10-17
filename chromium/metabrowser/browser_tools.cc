#include "metabrowser/browser_tools.h"
#include <algorithm>
#include <limits>
#include <set>
#include "base/base64.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/bind_post_task.h"
#include "base/task/sequenced_task_runner.h"
#include "base/uuid.h"
#include "build/build_config.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "components/viz/common/frame_sinks/copy_output_result.h"
#include "content/public/browser/browser_accessibility_state.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/render_widget_host_view.h"
#include "content/public/browser/scoped_accessibility_mode.h"
#include "ui/accessibility/ax_action_data.h"
#include "ui/accessibility/ax_enum_util.h"
#include "ui/accessibility/ax_mode.h"
#include "ui/accessibility/ax_node.h"
#include "ui/accessibility/ax_tree_manager.h"
#include "ui/accessibility/ax_tree_update.h"
#include "ui/accessibility/platform/browser_accessibility.h"
#include "ui/accessibility/platform/browser_accessibility_manager.h"
#include "ui/accessibility/platform/ax_platform_tree_manager_delegate.h"
#include "ui/base/page_transition_types.h"
#include "ui/gfx/codec/png_codec.h"
#include "ui/gfx/geometry/size_conversions.h"
#include "ui/gfx/geometry/point_conversions.h"
#include "ui/gfx/geometry/rect_conversions.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/image/image_skia.h"
#include "cc/paint/paint_flags.h"
#include "url/gurl.h"
#include "url/origin.h"
namespace metabrowser {
namespace {
#include "metabrowser/browser_tool_catalog.inc"
bool ValidValue(const base::Value& value,const base::DictValue& schema,unsigned depth=0){
  if(depth>6)return false;const auto* type=schema.FindString("type");if(!type)return false;
  if(*type=="object"){
    if(!value.is_dict())return false;const auto& object=value.GetDict();const auto* properties=schema.FindDict("properties");if(!properties)return false;
    if(const auto* required=schema.FindList("required"))for(const auto& key:*required)if(!key.is_string()||!object.contains(key.GetString()))return false;
    for(const auto item:object){const auto* property=properties->FindDict(item.first);if(!property||!ValidValue(item.second,*property,depth+1))return false;}
  }else if(*type=="array"){
    if(!value.is_list())return false;const auto& list=value.GetList();const auto* items=schema.FindDict("items");if(!items||list.size()>64)return false;
    if(auto n=schema.FindInt("minItems");n&&list.size()<static_cast<size_t>(*n))return false;
    if(auto n=schema.FindInt("maxItems");n&&list.size()>static_cast<size_t>(*n))return false;
    for(const auto& item:list)if(!ValidValue(item,*items,depth+1))return false;
  }else if(*type=="string"){
    if(!value.is_string()||value.GetString().size()>65536)return false;
    if(auto n=schema.FindInt("minLength");n&&value.GetString().size()<static_cast<size_t>(*n))return false;
    if(auto n=schema.FindInt("maxLength");n&&value.GetString().size()>static_cast<size_t>(*n))return false;
  }else if(*type=="integer"){
    if(!value.is_int())return false;if(auto n=schema.FindInt("minimum");n&&value.GetInt()<*n)return false;if(auto n=schema.FindInt("maximum");n&&value.GetInt()>*n)return false;
  }else if(*type=="boolean"){if(!value.is_bool())return false;}else return false;
  if(const auto* choices=schema.FindList("enum")){bool found=false;for(const auto& choice:*choices)if(choice==value)found=true;if(!found)return false;}return true;
}
std::string Encode(base::DictValue value){return base::WriteJson(value).value_or("{}");}
std::string Id(){return base::Uuid::GenerateRandomV4().AsLowercaseString();}
std::string S(const base::DictValue& args,const char* key){auto* v=args.FindString(key);return v?*v:"";}
std::string Cut(std::string s,size_t n=1024){if(s.size()<=n)return s;while(n&&((static_cast<unsigned char>(s[n])&0xc0)==0x80))--n;s.resize(n);return s;}
void Error(BrowserTools::Reply reply,std::string reason,std::string status="rejected"){
  const std::string recovery=status=="stale"?"observe_again":status=="not_ready"?"wait_then_observe":status=="ambiguous"?"inspect_and_disambiguate":status=="handoff_required"?"user_handoff":status=="unknown"?"reconcile_before_retry":"stop_or_replan";
  std::move(reply).Run(2,Encode(base::DictValue().Set("status",status).Set("reason",reason).Set("recovery",recovery).Set("retry_same_request",false).Set("execution","not_dispatched").Set("business_outcome_verified",false)));
}
std::string TabId(content::WebContents* page){
  using Entry=std::pair<base::WeakPtr<content::WebContents>,std::string>;static auto* ids=new std::map<content::WebContents*,Entry>;
  for(auto i=ids->begin();i!=ids->end();)if(!i->second.first)i=ids->erase(i);else ++i;
  auto i=ids->find(page);if(i==ids->end())i=ids->emplace(page,Entry{page->GetWeakPtr(),Id()}).first;return i->second.second;
}
std::string DocumentId(content::WebContents* page){
  using Entry=std::pair<content::WeakDocumentPtr,std::string>;static auto* ids=new std::map<std::string,Entry>;auto& e=(*ids)[TabId(page)];
  if(e.first.AsRenderFrameHostIfValid()!=page->GetPrimaryMainFrame()){e.first=page->GetPrimaryMainFrame()->GetWeakDocumentPtr();e.second=Id();}return e.second;
}
std::string URL(content::WebContents* page){GURL u=page->GetLastCommittedURL();GURL::Replacements r;r.ClearUsername();r.ClearPassword();if(u.path().find("/auth/metask/callback")!=std::string::npos){r.ClearQuery();r.ClearRef();}return u.ReplaceComponents(r).spec();}
bool Protected(const ui::AXNodeData& d){return d.HasState(ax::mojom::State::kProtected);}
bool Visible(const ui::AXNode* n){for(auto* p=n;p;p=p->parent())if(p->data().HasState(ax::mojom::State::kInvisible))return false;return true;}
bool Interactive(const ui::AXNodeData& d){static const auto* roles=new std::set<std::string>{"button","link","checkBox","radioButton","switch","comboBoxSelect","comboBoxMenuButton","menuItem","listBoxOption","slider","tab","treeItem"};return d.IsTextField()||d.HasState(ax::mojom::State::kFocusable)||roles->contains(ui::ToString(d.role));}
bool Structural(const ui::AXNodeData& d){auto r=std::string(ui::ToString(d.role));return r=="genericContainer"||r=="none"||r=="group"||r=="inlineTextBox";}
bool Same(const ui::AXNodeData& a,const ui::AXNodeData& b){return a.id==b.id&&a.role==b.role&&a.GetStringAttribute(ax::mojom::StringAttribute::kName)==b.GetStringAttribute(ax::mojom::StringAttribute::kName)&&a.GetStringAttribute(ax::mojom::StringAttribute::kValue)==b.GetStringAttribute(ax::mojom::StringAttribute::kValue)&&a.GetCheckedState()==b.GetCheckedState();}
gfx::Rect ViewportBounds(ui::BrowserAccessibility* node){
  auto* root=node->manager()->GetManagerForRootFrame();if(!root)return {};
  const float dsf=root->device_scale_factor();if(dsf<=0)return {};
  float scale=1.0f/dsf;
#if BUILDFLAG(IS_MAC) || BUILDFLAG(IS_ANDROID)
  // Root-frame AX bounds omit pinch scale on these platforms. "kScreenDIPs"
  // still uses a DSF-scaled origin in Chromium154; never mix it with view DIPs.
  scale*=root->GetPageScaleFactor();
#endif
  return gfx::ScaleToEnclosingRect(node->GetBoundsRect(ui::AXCoordinateSystem::kRootFrame,ui::AXClippingBehavior::kClipped),scale);
}
ui::AXNodeData Identity(const ui::AXNodeData& data){
  ui::AXNodeData out;out.id=data.id;out.role=data.role;out.state=data.state;
  out.AddStringAttribute(ax::mojom::StringAttribute::kName,Cut(data.GetStringAttribute(ax::mojom::StringAttribute::kName),65536));
  if(!Protected(data))out.AddStringAttribute(ax::mojom::StringAttribute::kValue,Cut(data.GetStringAttribute(ax::mojom::StringAttribute::kValue),65536));
  out.SetCheckedState(data.GetCheckedState());return out;
}
base::DictValue Node(const ui::AXNodeData& d,int ref,const std::string& frame){
  auto out=base::DictValue().Set("ref",ref).Set("frame_id",frame).Set("role",ui::ToString(d.role)).Set("name",Cut(d.GetStringAttribute(ax::mojom::StringAttribute::kName))).Set("disabled",d.GetRestriction()==ax::mojom::Restriction::kDisabled).Set("protected",Protected(d));
  if(!Protected(d))out.Set("value",Cut(d.GetStringAttribute(ax::mojom::StringAttribute::kValue)));
  if(d.GetCheckedState()!=ax::mojom::CheckedState::kNone)out.Set("checked",ui::ToString(d.GetCheckedState()));return out;
}
// Asynchronous renderer hit-testing is required: the synchronous AX cache can
// miss z-order and overflow. The supported input semantics remain AX activation,
// not general pointer routing or arbitrary canvas coordinates.
class GuardedAction:public std::enable_shared_from_this<GuardedAction>{
 public:
  GuardedAction(base::WeakPtr<BrowserTools> broker,content::WebContents* page,content::RenderFrameHost* frame,ui::AXNodeData expected,ui::AXActionData action,BrowserTools::Reply reply)
      :broker_(broker),page_(page->GetWeakPtr()),main_(page->GetPrimaryMainFrame()->GetWeakDocumentPtr()),frame_(frame->GetWeakDocumentPtr()),expected_(std::move(expected)),action_(std::move(action)),reply_(std::move(reply)),generation_(broker->generation()),deadline_(base::TimeTicks::Now()+base::Seconds(2)){}
  void Start(){
    if(!reply_)return;if(base::TimeTicks::Now()>=deadline_){Timeout();return;}
    if(!broker_||!page_||generation_!=broker_->generation()||broker_->ActivePage()!=page_.get()||main_.AsRenderFrameHostIfValid()!=page_->GetPrimaryMainFrame()){Finish("cancelled","Context changed while grounding action");return;}
    auto* f=frame_.AsRenderFrameHostIfValid();auto* manager=f?ui::BrowserAccessibilityManager::FromID(f->GetAXTreeID()):nullptr;auto* node=manager?manager->GetFromID(expected_.id):nullptr;
    auto* main=main_.AsRenderFrameHostIfValid();auto* root=main?ui::BrowserAccessibilityManager::FromID(main->GetAXTreeID()):nullptr;
    auto* live=manager?manager->GetNode(expected_.id):nullptr;auto* view=page_->GetRenderWidgetHostView();
    if(!f||!f->IsActive()||!f->IsRenderFrameLive()||!node||!live||!Same(expected_,live->data())||live->data().IsIgnored()||!Visible(live)||Protected(live->data())||live->data().GetRestriction()==ax::mojom::Restriction::kDisabled||!root||!root->delegate()||!view){Finish("stale","Target or hit-test context unavailable");return;}
    auto screen=ViewportBounds(node);auto visible=screen;visible.Intersect(gfx::Rect(view->GetViewBounds().size()));
    if(node->IsOffscreen()||visible.IsEmpty()){
      geometry_ready_=false;
      if(!scrolled_){ui::AXActionData scroll;scroll.target_node_id=expected_.id;scroll.target_tree_id=f->GetAXTreeID();scroll.action=ax::mojom::Action::kScrollToMakeVisible;scroll.horizontal_scroll_alignment=ax::mojom::ScrollAlignment::kScrollAlignmentClosestEdge;scroll.vertical_scroll_alignment=ax::mojom::ScrollAlignment::kScrollAlignmentClosestEdge;scroll.scroll_behavior=ax::mojom::ScrollBehavior::kDoNotScrollIfVisible;f->AccessibilityPerformAction(scroll);scrolled_=true;}
      Schedule();return;
    }
    // AX existence is not layout stability. Require two equal geometry samples
    // before asking the renderer for the actual hit target; no click is retried.
    auto bounds=node->GetBoundsRect(ui::AXCoordinateSystem::kRootFrame,ui::AXClippingBehavior::kClipped);
    if(bounds.IsEmpty()){Finish("rejected","Target has no actionable bounds");return;}
    if(!geometry_ready_||screen!=screen_||bounds!=root_bounds_){screen_=screen;root_bounds_=bounds;geometry_ready_=true;Schedule();return;}
    const auto center=visible.CenterPoint();const float dsf=root->device_scale_factor(),page_scale=root->GetPageScaleFactor();
    if(dsf<=0||page_scale<=0){Finish("stale","Invalid viewport scale");return;}
    const gfx::Point point=gfx::ScaleToRoundedPoint(center,dsf/page_scale);
    root->delegate()->AccessibilityHitTest(point,ax::mojom::Event::kNone,0,base::BindOnce(&GuardedAction::Hit,shared_from_this()));
    base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(FROM_HERE,base::BindOnce(&GuardedAction::Timeout,shared_from_this()),std::max(base::Milliseconds(1),deadline_-base::TimeTicks::Now()));
  }
 private:
  void Finish(std::string status,std::string reason){if(reply_)std::move(reply_).Run(status=="dispatched"?0:2,Encode(base::DictValue().Set("status",status).Set("reason",reason).Set("verified",false).Set("activation_dispatched",status=="dispatched").Set("preparatory_scroll_dispatched",scrolled_).Set("input_semantics","accessibility activation").Set("business_outcome_verified",false)));}
  void Timeout(){Finish("timeout","Grounding deadline exceeded; no activation dispatched, preparatory scrolling may have occurred");}
  void Schedule(){base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(FROM_HERE,base::BindOnce(&GuardedAction::Start,shared_from_this()),base::Milliseconds(50));}
  void Hit(ui::AXPlatformTreeManager* hit,ui::AXNodeID id){
    if(!reply_)return;if(base::TimeTicks::Now()>=deadline_){Timeout();return;}auto* f=frame_.AsRenderFrameHostIfValid();
    if(!broker_||!page_||generation_!=broker_->generation()||broker_->ActivePage()!=page_.get()||main_.AsRenderFrameHostIfValid()!=page_->GetPrimaryMainFrame()||!f||!f->IsActive()||!f->IsRenderFrameLive()){Finish("cancelled","Context changed before action");return;}
    auto* manager=ui::AXTreeManager::FromID(f->GetAXTreeID());auto* node=manager?manager->GetNode(expected_.id):nullptr;
    if(!node||!Same(expected_,node->data())||node->data().IsIgnored()||!Visible(node)||Protected(node->data())||node->data().GetRestriction()==ax::mojom::Restriction::kDisabled){Finish("stale","Target changed before dispatch");return;}
    auto* platform=ui::BrowserAccessibilityManager::FromID(f->GetAXTreeID());auto* bounds_node=platform?platform->GetFromID(expected_.id):nullptr;
    if(!bounds_node||bounds_node->IsOffscreen()||ViewportBounds(bounds_node)!=screen_||bounds_node->GetBoundsRect(ui::AXCoordinateSystem::kRootFrame,ui::AXClippingBehavior::kClipped)!=root_bounds_){Finish("stale","Target geometry changed during hit test; observe again");return;}
    bool matches=false;if(hit&&hit->GetTreeID()==f->GetAXTreeID())for(auto* n=hit->GetNode(id);n;n=n->parent())if(n->id()==expected_.id)matches=true;
    if(!matches){Finish("rejected","Target is covered or hit test resolved another element");return;}
    f->AccessibilityPerformAction(action_);Finish("dispatched","Native input dispatched; observe or wait to verify effect");
  }
  base::WeakPtr<BrowserTools> broker_;base::WeakPtr<content::WebContents> page_;content::WeakDocumentPtr main_,frame_;ui::AXNodeData expected_;ui::AXActionData action_;BrowserTools::Reply reply_;uint64_t generation_;base::TimeTicks deadline_;gfx::Rect screen_,root_bounds_;bool geometry_ready_=false,scrolled_=false;
};
// Finite local checks avoid paid model polling. Navigation is a valid ready/URL
// transition, but invalidates element/text waits bound to the previous document.
class Waiter:public std::enable_shared_from_this<Waiter>{
 public:
  Waiter(base::WeakPtr<BrowserTools> b,content::WebContents* p,base::DictValue a,BrowserTools::Reply r):broker_(b),page_(p->GetWeakPtr()),document_(p->GetPrimaryMainFrame()->GetWeakDocumentPtr()),args_(std::move(a)),reply_(std::move(r)),start_(base::TimeTicks::Now()),generation_(b->generation()){}
  void Poll(){
    if(!broker_||!page_||generation_!=broker_->generation()){Finish("cancelled","Wait cancelled");return;}
    const auto kind=S(args_,"condition");if(kind!="ready"&&kind!="url"&&document_.AsRenderFrameHostIfValid()!=page_->GetPrimaryMainFrame()){Finish("stale","Document changed while waiting");return;}
    bool match=kind=="ready"?broker_->NavigationReady(page_.get()):kind=="url"?URL(page_.get())==S(args_,"url"):false;unsigned matches=0;bool complete=true;size_t scanned=0,frames=0;
    if(kind=="text"||kind=="element")page_->GetPrimaryMainFrame()->ForEachRenderFrameHost([&](content::RenderFrameHost* f){
      if(++frames>32||!f->IsActive()||!f->IsRenderFrameLive()||f->IsNestedWithinFencedFrame()){complete=false;return;}
      auto* m=ui::AXTreeManager::FromID(f->GetAXTreeID());if(!m||!m->GetRoot()){complete=false;return;}
      std::vector<const ui::AXNode*> pending{m->GetRoot()};while(!pending.empty()&&++scanned<=8192){auto* n=pending.back();pending.pop_back();for(auto c=n->children().rbegin();c!=n->children().rend();++c){if(pending.size()+scanned>=8192){complete=false;break;}pending.push_back(c->get());}
        if(!Visible(n)||Protected(n->data())||n->data().IsIgnored())continue;auto name=n->data().GetStringAttribute(ax::mojom::StringAttribute::kName);
        if(kind=="text")match=match||name.find(S(args_,"text"))!=std::string::npos||n->data().GetStringAttribute(ax::mojom::StringAttribute::kValue).find(S(args_,"text"))!=std::string::npos;
        else if(name==S(args_,"name")&&(S(args_,"role").empty()||std::string(ui::ToString(n->data().role))==S(args_,"role")))++matches;
      }if(!pending.empty())complete=false;
    });
    if(kind=="element")match=matches==1&&complete;if(matches>1){Finish("ambiguous","Multiple matching elements");return;}
    if(match){Finish("completed","Declared condition observed");return;}
    if(base::TimeTicks::Now()-start_>=base::Milliseconds(args_.FindInt("timeout_ms").value_or(5000))){Finish("timeout","Condition not observed before deadline");return;}
    base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(FROM_HERE,base::BindOnce(&Waiter::Poll,shared_from_this()),base::Milliseconds(100));
  }
 private:
  void Finish(std::string state,std::string reason){if(reply_)std::move(reply_).Run(state=="completed"?0:2,Encode(base::DictValue().Set("status",state).Set("reason",reason).Set("condition",S(args_,"condition")).Set("elapsed_ms",static_cast<int>((base::TimeTicks::Now()-start_).InMilliseconds())).Set("tab_id",page_?TabId(page_.get()):"").Set("business_outcome_verified",false)));}
  base::WeakPtr<BrowserTools> broker_;base::WeakPtr<content::WebContents> page_;content::WeakDocumentPtr document_;base::DictValue args_;BrowserTools::Reply reply_;base::TimeTicks start_;uint64_t generation_;
};
class LocalGoal:public std::enable_shared_from_this<LocalGoal>{
 public:
  LocalGoal(base::WeakPtr<BrowserTools> b,content::WebContents* p,base::ListValue steps,BrowserTools::Reply reply):broker_(b),page_(p->GetWeakPtr()),document_(p->GetPrimaryMainFrame()->GetWeakDocumentPtr()),tab_(TabId(p)),steps_(std::move(steps)),reply_(std::move(reply)),start_(base::TimeTicks::Now()),generation_(b->generation()){}
  void Observe(){if(!Valid()){Finish(2,"handoff_required","Cancelled, context changed or deadline exceeded");return;}broker_->Run("browser_observe",Encode(base::DictValue().Set("tab_id",tab_).Set("max_nodes",2048).Set("max_bytes",65536)),base::BindOnce(&LocalGoal::Observed,shared_from_this()));}
 private:
  bool Valid(){return broker_&&page_&&broker_->generation()==generation_&&broker_->ActivePage()==page_.get()&&document_.AsRenderFrameHostIfValid()==page_->GetPrimaryMainFrame()&&base::TimeTicks::Now()-start_<base::Seconds(20);}
  void Finish(uint32_t code,std::string status,std::string reason){if(reply_)std::move(reply_).Run(code,Encode(base::DictValue().Set("status",status).Set("reason",reason).Set("checks",std::move(checks_)).Set("effects_dispatched",static_cast<int>(effects_)).Set("preparatory_scrolls_dispatched",static_cast<int>(scrolls_)).Set("last_action",std::move(last_action_)).Set("needs_reconciliation",effects_>0||scrolls_>0).Set("business_outcome_verified",false)));}
  void Observed(uint32_t code,std::string encoded){
    if(code||!Valid()){Finish(2,"handoff_required",code?encoded:"Context changed during observation");return;}
    auto state=base::JSONReader::ReadDict(encoded,base::JSON_PARSE_RFC);auto* nodes=state?state->FindList("nodes"):nullptr;if(!nodes||!state->FindString("observation_id")){Finish(2,"handoff_required","Missing semantic observation");return;}
    const auto& step=steps_[step_].GetDict();const auto expected=S(step,"expect_text");
    if(waiting_){if(!target_document_.AsRenderFrameHostIfValid()){Finish(2,"handoff_required","Target frame document replaced after dispatch");return;}bool matched=false;unsigned fill_matches=0;
      for(const auto& v:*nodes){const auto& n=v.GetDict();if(S(step,"op")=="fill"){if(n.FindInt("ref").value_or(0)==target_ref_&&S(n,"value")==S(step,"text"))++fill_matches;}else matched=matched||S(n,"name").find(expected)!=std::string::npos||S(n,"value").find(expected)!=std::string::npos;}
      if(S(step,"op")=="fill")matched=fill_matches==1&&!state->FindBool("possibly_truncated").value_or(true);
      if(!matched){if(++polls_>=30){Finish(2,"handoff_required","Postcondition not observed; reconcile before replay");return;}base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(FROM_HERE,base::BindOnce(&LocalGoal::Observe,shared_from_this()),base::Milliseconds(100));return;}
      checks_.Append(base::DictValue().Set("step",static_cast<int>(step_)).Set("observation_id",S(*state,"observation_id")).Set("matched_text",expected));waiting_=false;polls_=0;if(++step_==steps_.size()){Finish(0,"local_goal_completed","All declared local postconditions observed");return;}Observe();return;
    }
    if(S(step,"op")!="fill")for(const auto& v:*nodes){const auto& n=v.GetDict();if(S(n,"name").find(expected)!=std::string::npos||S(n,"value").find(expected)!=std::string::npos){Finish(2,"handoff_required","Postcondition already exists; specify a changed-state condition");return;}}
    unsigned count=0;int target=0;for(const auto& v:*nodes){const auto& n=v.GetDict();if(S(n,"name")==S(step,"name")&&S(n,"role")==S(step,"role")){++count;target=n.FindInt("ref").value_or(0);}}
    if(count!=1||!target||state->FindBool("possibly_truncated").value_or(true)){Finish(2,"handoff_required","Missing, ambiguous target or incomplete observation");return;}
    // Never skip a step because expected text exists somewhere else on the page.
    target_ref_=target;target_document_=broker_->TargetDocument(S(*state,"observation_id"),target);
    auto action=base::DictValue().Set("tab_id",tab_).Set("observation_id",S(*state,"observation_id")).Set("target",target).Set("op",S(step,"op"));if(auto* text=step.FindString("text"))action.Set("text",*text);
    broker_->Run("browser_act",Encode(std::move(action)),base::BindOnce(&LocalGoal::Executed,shared_from_this()));
  }
  void Executed(uint32_t code,std::string result){auto action=base::JSONReader::ReadDict(result,base::JSON_PARSE_RFC);if(action){if(action->FindBool("preparatory_scroll_dispatched").value_or(false))++scrolls_;last_action_=std::move(*action);}if(code){Finish(code,"handoff_required",result);return;}++effects_;waiting_=true;Observe();}
  base::WeakPtr<BrowserTools> broker_;base::WeakPtr<content::WebContents> page_;content::WeakDocumentPtr document_;std::string tab_;base::ListValue steps_,checks_;base::DictValue last_action_;BrowserTools::Reply reply_;base::TimeTicks start_;uint64_t generation_;size_t step_=0,effects_=0,scrolls_=0;unsigned polls_=0;bool waiting_=false;int target_ref_=0;content::WeakDocumentPtr target_document_;
};
}
class BrowserTools::NavigationWatch:public content::WebContentsObserver{
 public:
  NavigationWatch(BrowserTools* owner,content::WebContents* page,std::string id):content::WebContentsObserver(page),owner_(owner),id_(std::move(id)){}
  void DidStartNavigation(content::NavigationHandle* handle) override {
    if(!handle->IsInPrimaryMainFrame())return;auto it=owner_->navigations_.find(id_);
    if(it!=owner_->navigations_.end())it->second.id=handle->GetNavigationId();
  }
  void DidFinishNavigation(content::NavigationHandle* handle) override {
    if(!handle->IsInPrimaryMainFrame())return;auto it=owner_->navigations_.find(id_);
    if(it!=owner_->navigations_.end()&&(it->second.id==handle->GetNavigationId()||(it->second.id==0&&handle->GetURL().spec()==it->second.url)))owner_->navigations_.erase(it);
  }
  void WebContentsDestroyed() override {owner_->navigations_.erase(id_);}
 private:
  raw_ptr<BrowserTools> owner_;std::string id_;
};
BrowserTools::BrowserTools(BrowserWindowInterface* browser):browser_(browser){}
BrowserTools::~BrowserTools()=default;
base::ListValue BrowserTools::ToolCatalog(){auto value=base::JSONReader::Read(kBrowserToolCatalog,base::JSON_PARSE_RFC);return value&&value->is_list()?std::move(value->GetList()):base::ListValue();}
bool BrowserTools::IsReadOnly(std::string_view name){for(const auto& v:ToolCatalog())if(S(v.GetDict(),"name")==name)return v.GetDict().FindDict("annotations")->FindBool("readOnlyHint").value_or(false);return false;}
bool BrowserTools::ValidateArguments(std::string_view name,const base::DictValue& args){for(const auto& v:ToolCatalog())if(S(v.GetDict(),"name")==name)return ValidValue(base::Value(args.Clone()),*v.GetDict().FindDict("inputSchema"));return false;}
void BrowserTools::Cancel(){++generation_;pending_action_=0;for(auto& [id,s]:snapshots_)s.consumed=true;}
void BrowserTools::Invalidate(content::WebContents* page){for(auto& [id,s]:snapshots_)if(s.page.get()==page)s.consumed=true;}
content::WebContents* BrowserTools::ActivePage(){return browser_->GetTabStripModel()->GetActiveWebContents();}
content::WebContents* BrowserTools::FindPage(std::string_view id){auto* tabs=browser_->GetTabStripModel();for(int i=0;i<tabs->count();++i)if(TabId(tabs->GetWebContentsAt(i))==id)return tabs->GetWebContentsAt(i);return nullptr;}
void BrowserTools::TrackNavigation(content::WebContents* page,const std::string& url){
  auto id=TabId(page);if(!navigation_watches_.contains(id))navigation_watches_[id]=std::make_unique<NavigationWatch>(this,page,id);
  navigations_[id]=Navigation{0,url};
}
bool BrowserTools::NavigationReady(content::WebContents* page){return !navigations_.contains(TabId(page))&&!page->IsLoading();}
content::WeakDocumentPtr BrowserTools::TargetDocument(const std::string& observation,int target){
  auto it=snapshots_.find(observation);if(it==snapshots_.end()||it->second.consumed)return {};
  auto found=it->second.targets.find(target);return found==it->second.targets.end()?content::WeakDocumentPtr():found->second.document;
}
std::string BrowserTools::Context(){auto* p=ActivePage();return p?Encode(base::DictValue().Set("tab_id",TabId(p)).Set("document_id",DocumentId(p)).Set("url",URL(p)).Set("title",Cut(base::UTF16ToUTF8(p->GetTitle()))).Set("loading",p->IsLoading())):"{}";}
void BrowserTools::Observe(base::WeakPtr<content::WebContents> page,base::DictValue args,Reply reply){
  if(!page){Error(std::move(reply),"Closed tab","stale");return;}const auto tab=TabId(page.get());if(!accessibility_.contains(tab))accessibility_[tab]=content::BrowserAccessibilityState::GetInstance()->CreateScopedModeForWebContents(page.get(),ui::kAXModeComplete);
  const auto document=page->GetPrimaryMainFrame()->GetWeakDocumentPtr();
  base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(FROM_HERE,base::BindOnce([](base::WeakPtr<BrowserTools> self,uint64_t generation,base::WeakPtr<content::WebContents> page,content::WeakDocumentPtr document,base::DictValue args,Reply reply){
    if(!self||generation!=self->generation()){Error(std::move(reply),"Observation cancelled","cancelled");return;}
    ui::AXTreeUpdate unused;self->Collected(page,document,std::move(args),std::move(reply),unused);
  },weak_.GetWeakPtr(),generation_,page,document,std::move(args),std::move(reply)),base::Milliseconds(50));
}
void BrowserTools::Collected(base::WeakPtr<content::WebContents> page,content::WeakDocumentPtr doc,base::DictValue args,Reply reply,ui::AXTreeUpdate&){
  if(!page||doc.AsRenderFrameHostIfValid()!=page->GetPrimaryMainFrame()){Error(std::move(reply),"Document changed during capture","stale");return;}
  const int max_nodes=std::clamp(args.FindInt("max_nodes").value_or(256),1,2048),max_bytes=std::clamp(args.FindInt("max_bytes").value_or(16384),8192,65536);
  const bool interactive=args.FindBool("interactive").value_or(false),compact=args.FindBool("compact").value_or(true);const auto query=S(args,"query"),selected=S(args,"frame_id");
  Snapshot snapshot;snapshot.page=page;snapshot.document=doc;snapshot.captured=base::TimeTicks::Now();snapshot.signature=Encode(base::DictValue().Set("interactive",interactive).Set("compact",compact).Set("query",query).Set("frame_id",selected).Set("max_nodes",max_nodes).Set("max_bytes",max_bytes));
  base::ListValue frames;size_t scanned=0,frame_count=0,node_bytes=0;bool truncated=false,missing=false,found_frame=selected.empty();
  for(auto i=refs_.begin();i!=refs_.end();)if(!i->second.first.AsRenderFrameHostIfValid())i=refs_.erase(i);else ++i;if(refs_.size()>16384)refs_.clear();
  page->GetPrimaryMainFrame()->ForEachRenderFrameHostWithAction([&](content::RenderFrameHost* f){
    using Action=content::RenderFrameHost::FrameIterationAction;if(++frame_count>32){truncated=true;return Action::kStop;}
    if(!f->IsActive()||!f->IsRenderFrameLive()||f->IsNestedWithinFencedFrame())return Action::kSkipChildren;
    const auto frame=f->GetAXTreeID().ToString();found_frame=found_frame||frame==selected;const bool chosen=selected.empty()||frame==selected;
    auto* m=ui::AXTreeManager::FromID(f->GetAXTreeID());bool available=m&&m->GetRoot();frames.Append(base::DictValue().Set("frame_id",frame).Set("origin",Cut(f->GetLastCommittedOrigin().Serialize(),128)).Set("available",available).Set("selected",chosen));
    if(!chosen)return Action::kContinue;if(!available){missing=true;return Action::kContinue;}
    auto frame_doc=f->GetWeakDocumentPtr();std::vector<const ui::AXNode*> pending{m->GetRoot()};
    while(!pending.empty()){
      if(++scanned>8192){truncated=true;break;}auto* n=pending.back();pending.pop_back();for(auto c=n->children().rbegin();c!=n->children().rend();++c){if(pending.size()+scanned>=8192){truncated=true;break;}pending.push_back(c->get());}const auto& d=n->data();
      if(!Visible(n)||d.IsIgnored()||(interactive&&!Interactive(d))||(compact&&Structural(d)&&!Interactive(d)))continue;
      auto name=d.GetStringAttribute(ax::mojom::StringAttribute::kName),value=Protected(d)?std::string():d.GetStringAttribute(ax::mojom::StringAttribute::kValue);if(!query.empty()&&name.find(query)==std::string::npos&&value.find(query)==std::string::npos)continue;
      if(snapshot.nodes.size()>=static_cast<size_t>(max_nodes)){truncated=true;continue;}
      auto key=frame+":"+base::NumberToString(d.id);auto r=refs_.find(key);if(r==refs_.end()||r->second.first.AsRenderFrameHostIfValid()!=f){if(next_ref_==std::numeric_limits<int>::max()){truncated=true;continue;}r=refs_.insert_or_assign(key,std::pair(frame_doc,next_ref_++)).first;}
      int ref=r->second.second;auto item=Node(d,ref,frame);const size_t bytes=base::WriteJson(item).value_or("").size()+1;
      if(node_bytes+bytes>static_cast<size_t>(max_bytes-4096)){truncated=true;continue;}node_bytes+=bytes;
      if(name.size()<=65536&&value.size()<=65536&&!Protected(d))snapshot.targets.emplace(ref,Target{frame_doc,Identity(d),frame});
      else item.Set("detail_omitted",true);
      snapshot.nodes.Append(std::move(item));if(name.size()>1024||value.size()>1024)truncated=true;
    }return Action::kContinue;
  });
  if(!found_frame){Error(std::move(reply),"Unknown frame_id; observe coverage again","stale");return;}
  if(snapshot.nodes.empty()&&missing){Error(std::move(reply),"Accessibility initializing; observe again","not_ready");return;}
  const auto observation=Id();auto result=base::DictValue().Set("status","completed").Set("observation_id",observation).Set("tab_id",TabId(page.get())).Set("document_id",DocumentId(page.get())).Set("url",Cut(URL(page.get()),2048)).Set("untrusted",true).Set("coverage","live AX trees; max32 frames/8192 scanned nodes; excludes fenced frames").Set("scanned_nodes",static_cast<int>(scanned)).Set("frames",std::move(frames)).Set("possibly_truncated",truncated||missing).Set("mode","semantic").Set("nodes",snapshot.nodes.Clone());
  while(Encode(result.Clone()).size()>static_cast<size_t>(max_bytes-512)&&!snapshot.nodes.empty()){int ref=snapshot.nodes.back().GetDict().FindInt("ref").value_or(0);snapshot.targets.erase(ref);snapshot.nodes.erase(snapshot.nodes.end()-1);result.Set("nodes",snapshot.nodes.Clone());result.Set("possibly_truncated",true);}
  while(Encode(result.Clone()).size()>static_cast<size_t>(max_bytes-512)&&!result.FindList("frames")->empty()){auto* v=result.FindList("frames");v->erase(v->end()-1);result.Set("frame_details_truncated",true);result.Set("possibly_truncated",true);}
  snapshot.truncated=result.FindBool("possibly_truncated").value_or(true);
  if(S(args,"mode")=="delta"){
    auto baseline=S(args,"baseline_id");auto old=snapshots_.find(baseline);
    if(old!=snapshots_.end()&&old->second.page.get()==page.get()&&old->second.document.AsRenderFrameHostIfValid()==doc.AsRenderFrameHostIfValid()&&old->second.signature==snapshot.signature){
      std::map<int,std::string> previous;for(const auto& n:old->second.nodes)previous[n.GetDict().FindInt("ref").value_or(0)]=base::WriteJson(n).value_or("");base::ListValue changed,removed,order;
      for(const auto& n:snapshot.nodes){order.Append(n.GetDict().FindInt("ref").value_or(0));int ref=n.GetDict().FindInt("ref").value_or(0);auto p=previous.find(ref);if(p==previous.end()||p->second!=base::WriteJson(n).value_or(""))changed.Append(n.Clone());previous.erase(ref);}for(const auto& [ref,text]:previous)removed.Append(ref);
      result.Set("mode","delta");result.Set("baseline_id",baseline);result.Set("nodes",std::move(changed));result.Set("removed_refs",std::move(removed));result.Set("ordered_refs",std::move(order));
      if(Encode(result.Clone()).size()>static_cast<size_t>(max_bytes)){result.Set("mode","semantic");result.Set("nodes",snapshot.nodes.Clone());result.Set("delta_fallback","delta exceeds budget");result.Remove("removed_refs");result.Remove("ordered_refs");}
    }else result.Set("delta_fallback","missing/incompatible baseline; full observation returned");
  }
  while(snapshots_.size()>=8){auto oldest=std::min_element(snapshots_.begin(),snapshots_.end(),[](const auto& a,const auto& b){return a.second.captured<b.second.captured;});snapshots_.erase(oldest);}snapshots_.emplace(observation,std::move(snapshot));std::move(reply).Run(0,Encode(std::move(result)));
}
void BrowserTools::ReadTarget(content::WebContents* page,std::string name,const base::DictValue& args,Reply reply){
  auto i=snapshots_.find(S(args,"observation_id"));if(i==snapshots_.end()||i->second.consumed||i->second.page.get()!=page||i->second.document.AsRenderFrameHostIfValid()!=page->GetPrimaryMainFrame()||base::TimeTicks::Now()-i->second.captured>base::Seconds(30)){Error(std::move(reply),"Stale observation; observe again","stale");return;}
  auto& snapshot=i->second;auto target=args.FindInt("target");if((name=="browser_inspect"||name=="browser_act")&&!target){Error(std::move(reply),"Explicit target required");return;}if(target&&!snapshot.targets.contains(*target)){Error(std::move(reply),"Unknown ref","stale");return;}
  if(name=="browser_act"){
    if(page!=ActivePage()){Error(std::move(reply),"Activate target tab before acting","handoff_required");return;}const Target binding=snapshot.targets.at(*target);auto* f=binding.document.AsRenderFrameHostIfValid();auto* m=f?ui::AXTreeManager::FromID(f->GetAXTreeID()):nullptr;auto* n=m?m->GetNode(binding.node.id):nullptr;
    if(!n||!Same(binding.node,n->data())||n->data().IsIgnored()||!Visible(n)){Error(std::move(reply),"Target changed since observation","stale");return;}if(Protected(n->data())||n->data().GetRestriction()==ax::mojom::Restriction::kDisabled){Error(std::move(reply),"Protected or disabled target");return;}
    ui::AXActionData a;a.target_node_id=n->id();a.target_tree_id=f->GetAXTreeID();auto op=S(args,"op");
    if(op=="click"||op=="select"){
      if(op=="select"&&n->data().role!=ax::mojom::Role::kListBoxOption){Error(std::move(reply),"select requires observed option ref");return;}a.action=ax::mojom::Action::kDoDefault;
    }else if(op=="focus")a.action=ax::mojom::Action::kFocus;
    else if(op=="fill"){auto* text=args.FindString("text");if(!text||text->size()>65536||!n->data().IsTextField()||n->data().GetRestriction()==ax::mojom::Restriction::kReadOnly){Error(std::move(reply),"fill requires editable text field and bounded text");return;}a.action=ax::mojom::Action::kSetValue;a.value=*text;}
    else if(op=="scroll_down")a.action=ax::mojom::Action::kScrollDown;
    else if(op=="scroll_up")a.action=ax::mojom::Action::kScrollUp;
    else if(op=="scroll_into_view"){a.action=ax::mojom::Action::kScrollToMakeVisible;a.horizontal_scroll_alignment=ax::mojom::ScrollAlignment::kScrollAlignmentClosestEdge;a.vertical_scroll_alignment=ax::mojom::ScrollAlignment::kScrollAlignmentClosestEdge;a.scroll_behavior=ax::mojom::ScrollBehavior::kDoNotScrollIfVisible;}
    else if(op=="check"||op=="uncheck"){auto checked=n->data().GetCheckedState();if(checked==ax::mojom::CheckedState::kNone||checked==ax::mojom::CheckedState::kMixed){Error(std::move(reply),"Not a binary checkable control");return;}if((checked==ax::mojom::CheckedState::kTrue)==(op=="check")){std::move(reply).Run(0,Encode(base::DictValue().Set("status","completed").Set("already_satisfied",true)));return;}a.action=ax::mojom::Action::kDoDefault;}
    else{Error(std::move(reply),"Unsupported action");return;}
    Invalidate(page);
    if(a.action==ax::mojom::Action::kDoDefault){
      const auto action_id=++action_id_;pending_action_=action_id;
      auto done=base::BindOnce([](base::WeakPtr<BrowserTools> self,base::WeakPtr<content::WebContents> page,uint64_t action_id,Reply reply,uint32_t code,std::string result){if(self&&self->pending_action_==action_id){self->pending_action_=0;if(page)self->Invalidate(page.get());}std::move(reply).Run(code,std::move(result));},weak_.GetWeakPtr(),page->GetWeakPtr(),action_id,std::move(reply));
      std::make_shared<GuardedAction>(weak_.GetWeakPtr(),page,f,binding.node,a,std::move(done))->Start();return;
    }
    f->AccessibilityPerformAction(a);std::move(reply).Run(0,Encode(base::DictValue().Set("status","dispatched").Set("tab_id",TabId(page)).Set("verified",false).Set("input_semantics","accessibility action").Set("business_outcome_verified",false).Set("next","Wait and observe to verify effect")));return;
  }
  auto kind=name=="browser_inspect"?"inspect":S(args,"kind");if(kind!="inspect"&&kind!="text"&&kind!="links"&&kind!="table"){Error(std::move(reply),"Unknown extraction kind");return;}
  int max_bytes=std::clamp(args.FindInt("max_bytes").value_or(16384),8192,65536),max_nodes=std::clamp(args.FindInt("max_nodes").value_or(256),1,256);base::ListValue records;bool truncated=snapshot.truncated;size_t scanned=0;
  auto append=[&](const Target& binding,int ref,bool subtree){
    auto* f=binding.document.AsRenderFrameHostIfValid();auto* m=f?ui::AXTreeManager::FromID(f->GetAXTreeID()):nullptr;auto* root=m?m->GetNode(binding.node.id):nullptr;if(!root||!Same(binding.node,root->data())){truncated=true;return;}
    std::vector<const ui::AXNode*> pending{root};while(!pending.empty()&&++scanned<=8192){auto* n=pending.back();pending.pop_back();if(subtree)for(auto c=n->children().rbegin();c!=n->children().rend();++c){if(pending.size()+scanned>=8192){truncated=true;break;}pending.push_back(c->get());}if(!Visible(n)||Protected(n->data())||n->data().IsIgnored())continue;
      std::string role=ui::ToString(n->data().role);if(kind=="links"&&role!="link")continue;if(kind=="table"&&role!="table"&&role!="row"&&role!="cell"&&role!="columnHeader"&&role!="rowHeader")continue;
      auto row=Node(n->data(),ref,binding.frame_id);if(n!=root)row.Remove("ref");if(kind=="links"){GURL url(n->data().GetStringAttribute(ax::mojom::StringAttribute::kUrl));if(!url.SchemeIsHTTPOrHTTPS())continue;row.Set("href",Cut(url.spec(),2048));}
      if(records.size()>=static_cast<size_t>(max_nodes)){truncated=true;break;}records.Append(std::move(row));
    }if(!pending.empty()||scanned>8192)truncated=true;
  };
  if(target)append(snapshot.targets.at(*target),*target,true);else for(const auto& item:snapshot.nodes){auto ref=item.GetDict().FindInt("ref").value_or(0);auto found=snapshot.targets.find(ref);if(found!=snapshot.targets.end())append(found->second,ref,false);else truncated=true;}
  auto result=base::DictValue().Set("status","completed").Set("kind",kind).Set("observation_id",S(args,"observation_id")).Set("tab_id",TabId(page)).Set("document_id",DocumentId(page)).Set("url",Cut(URL(page),2048)).Set("untrusted",true).Set("coverage",target?"bounded live target subtree; no pagination guarantee":"observed set only; no full-page or pagination guarantee").Set("possibly_truncated",truncated).Set("records",std::move(records));
  while(Encode(result.Clone()).size()>static_cast<size_t>(max_bytes)&&!result.FindList("records")->empty()){auto* v=result.FindList("records");v->erase(v->end()-1);result.Set("possibly_truncated",true);}std::move(reply).Run(0,Encode(std::move(result)));
}
void BrowserTools::Run(std::string name,std::string arguments,Reply reply){
  auto args=base::JSONReader::ReadDict(arguments,base::JSON_PARSE_RFC);if(!args||arguments.size()>128*1024||!ValidateArguments(name,*args)){Error(std::move(reply),"Invalid typed arguments or unknown tool");return;}
  if(pending_action_&&!IsReadOnly(name)){Error(std::move(reply),"Another guarded action is pending","busy");return;}
  auto* tabs=browser_->GetTabStripModel();if(name=="browser_tabs"){
    if(args->contains("op")&&S(*args,"op")!="list"){Error(std::move(reply),"Use separate mutation tools");return;}base::ListValue list;for(int i=0;i<tabs->count()&&i<256;++i){auto* p=tabs->GetWebContentsAt(i);list.Append(base::DictValue().Set("tab_id",TabId(p)).Set("index",i).Set("active",p==ActivePage()).Set("url",Cut(URL(p),2048)).Set("title",Cut(base::UTF16ToUTF8(p->GetTitle()))).Set("loading",p->IsLoading()));}std::move(reply).Run(0,Encode(base::DictValue().Set("tabs",std::move(list)).Set("possibly_truncated",tabs->count()>256)));return;
  }
  if(name=="browser_tab_open"){
    GURL u(S(*args,"url"));if(!u.is_valid()||!u.SchemeIsHTTPOrHTTPS()||u.has_username()||u.has_password()||u.spec().size()>8192){Error(std::move(reply),"Expected HTTP(S) URL without credentials");return;}
    auto page=content::WebContents::Create(content::WebContents::CreateParams(browser_->GetProfile()));auto id=TabId(page.get());Cancel();TrackNavigation(page.get(),u.spec());page->GetController().LoadURL(u,content::Referrer(),ui::PAGE_TRANSITION_TYPED,std::string());tabs->AppendWebContents(std::move(page),true);std::move(reply).Run(0,Encode(base::DictValue().Set("status","dispatched").Set("tab_id",id).Set("verified",false)));return;
  }
  auto* page=args->contains("tab_id")?FindPage(S(*args,"tab_id")):ActivePage();
  if(!args->contains("tab_id")&&args->FindString("observation_id")){auto snapshot=snapshots_.find(S(*args,"observation_id"));if(snapshot!=snapshots_.end())page=snapshot->second.page.get();}if(!page){Error(std::move(reply),"Unknown or closed tab","stale");return;}
  if(name=="browser_tab_activate"||name=="browser_tab_close"){
    if(S(*args,"tab_id").empty()){Error(std::move(reply),"Explicit tab_id required");return;}int index=0;while(index<tabs->count()&&tabs->GetWebContentsAt(index)!=page)++index;
    if(name=="browser_tab_close"&&(tabs->count()<=1||page->NeedToFireBeforeUnloadOrUnloadEvents())){Error(std::move(reply),"Last tab or unsaved state requires user interaction","handoff_required");return;}Cancel();if(name=="browser_tab_activate")tabs->ActivateTabAt(index);else{accessibility_.erase(TabId(page));tabs->CloseWebContentsAt(index,0);}std::move(reply).Run(0,Encode(base::DictValue().Set("status","completed")));return;
  }
  if(name=="browser_status"){std::move(reply).Run(0,Encode(base::DictValue().Set("tab_id",TabId(page)).Set("document_id",DocumentId(page)).Set("url",Cut(URL(page),2048)).Set("title",Cut(base::UTF16ToUTF8(page->GetTitle()))).Set("loading",page->IsLoading()).Set("ready",NavigationReady(page)).Set("active",page==ActivePage())));return;}
  if(name!="browser_navigate"&&!(name=="browser_wait"&&(S(*args,"condition")=="ready"||S(*args,"condition")=="url"))&&!page->GetLastCommittedURL().SchemeIsHTTPOrHTTPS()){Error(std::move(reply),"Only HTTP(S) pages supported");return;}
  if((name=="browser_navigate"||name=="browser_execute")&&S(*args,"document_id")!=DocumentId(page)){Error(std::move(reply),"Approved document changed before execution","stale");return;}
  if(name=="browser_navigate"){
    GURL u(S(*args,"url"));if(page!=ActivePage()||!u.is_valid()||!u.SchemeIsHTTPOrHTTPS()||u.has_username()||u.has_password()||u.spec().size()>8192){Error(std::move(reply),"Expected active tab and HTTP(S) URL without credentials");return;}Cancel();TrackNavigation(page,u.spec());page->GetController().LoadURL(u,content::Referrer(),ui::PAGE_TRANSITION_TYPED,std::string());std::move(reply).Run(0,Encode(base::DictValue().Set("status","dispatched").Set("verified",false)));return;
  }
  if(name=="browser_wait"){
    auto kind=S(*args,"condition");int timeout=args->FindInt("timeout_ms").value_or(5000);
    if((kind!="ready"&&kind!="url"&&kind!="text"&&kind!="element")||timeout<100||timeout>10000||(kind=="text"&&(S(*args,"text").empty()||S(*args,"text").size()>512))||(kind=="element"&&S(*args,"name").empty())||(kind=="url"&&!GURL(S(*args,"url")).SchemeIsHTTPOrHTTPS())){Error(std::move(reply),"Invalid wait condition/deadline");return;}
    auto tab=TabId(page);if(!accessibility_.contains(tab))accessibility_[tab]=content::BrowserAccessibilityState::GetInstance()->CreateScopedModeForWebContents(page,ui::kAXModeComplete);std::make_shared<Waiter>(weak_.GetWeakPtr(),page,std::move(*args),std::move(reply))->Poll();return;
  }
  if(name=="browser_execute"){
    auto* steps=args->FindList("steps");if(page!=ActivePage()||!steps||steps->empty()||steps->size()>12){Error(std::move(reply),"Expected active tab and 1..12 steps");return;}for(const auto& v:*steps){if(!v.is_dict()){Error(std::move(reply),"Invalid step");return;}const auto& s=v.GetDict();auto op=S(s,"op");if(S(s,"name").empty()||S(s,"role").empty()||S(s,"expect_text").empty()||S(s,"expect_text").size()>512||(op!="click"&&op!="fill"&&op!="focus"&&op!="scroll_down"&&op!="scroll_up")||(op=="fill"&&(!s.FindString("text")||S(s,"text")!=S(s,"expect_text")))){Error(std::move(reply),"Each step requires exact name/role, supported op and bounded postcondition");return;}}
    std::make_shared<LocalGoal>(weak_.GetWeakPtr(),page,steps->Clone(),std::move(reply))->Observe();return;
  }
  if(name=="browser_observe"){
    auto mode=S(*args,"mode");if(mode=="visual"){
      auto* v=page->GetRenderWidgetHostView();if(page!=ActivePage()||!v||v->GetViewBounds().IsEmpty()){Error(std::move(reply),"Active visible surface required","not_ready");return;}
      const bool annotate=args->FindBool("annotate").value_or(false);
      const auto observation=S(*args,"observation_id");
      const auto view_bounds=v->GetViewBounds();
      struct Label {int ref;Target binding;gfx::Rect screen_bounds;};
      std::vector<Label> labels;
      if(annotate){
        auto i=snapshots_.find(observation);
        if(i==snapshots_.end()||i->second.consumed||i->second.page.get()!=page||i->second.document.AsRenderFrameHostIfValid()!=page->GetPrimaryMainFrame()||base::TimeTicks::Now()-i->second.captured>base::Seconds(30)){Error(std::move(reply),"Fresh observation_id required for annotations","stale");return;}
        for(const auto& entry:i->second.nodes){
          if(entry.GetDict().FindBool("protected").value_or(false)||entry.GetDict().FindBool("detail_omitted").value_or(false))continue;
          const int ref=entry.GetDict().FindInt("ref").value_or(0);
          auto target=i->second.targets.find(ref);
          if(target==i->second.targets.end()){Error(std::move(reply),"Missing annotation binding","stale");return;}
          const auto& binding=target->second;
          if(Protected(binding.node))continue;
          auto* frame=binding.document.AsRenderFrameHostIfValid();
          auto* manager=frame?ui::BrowserAccessibilityManager::FromID(frame->GetAXTreeID()):nullptr;
          auto* node=manager?manager->GetFromID(binding.node.id):nullptr;
          auto* live=manager?manager->GetNode(binding.node.id):nullptr;
          if(!live||!Visible(live)||live->data().IsIgnored()||!frame||!frame->IsActive()||frame->GetAXTreeID().ToString()!=binding.frame_id||!node||!Same(binding.node,node->GetData())||Protected(node->GetData())){Error(std::move(reply),"Annotation target changed or platform AX unavailable","stale");return;}
          if(node->IsOffscreen())continue;
          const auto bounds=ViewportBounds(node);
          auto clipped=bounds;clipped.Intersect(gfx::Rect(view_bounds.size()));
          if(clipped.IsEmpty())continue;
          labels.push_back({ref,binding,bounds});if(labels.size()==64)break;
        }
      }
      auto doc=page->GetPrimaryMainFrame()->GetWeakDocumentPtr();auto size=view_bounds.size();float scale=std::min(1.0f,std::min(1280.0f/size.width(),960.0f/size.height()));
      v->CopyFromSurface(gfx::Rect(),gfx::ScaleToRoundedSize(size,scale),base::Seconds(3),base::BindPostTaskToCurrentDefault(base::BindOnce([](base::WeakPtr<BrowserTools> self,uint64_t generation,base::WeakPtr<content::WebContents> page,content::WeakDocumentPtr doc,content::RenderWidgetHostView* view,gfx::Rect view_bounds,float scale,bool annotate,std::string observation,std::vector<Label> labels,Reply reply,const content::CopyFromSurfaceResult& image){
        if(!self||generation!=self->generation()||!page||self->ActivePage()!=page.get()||doc.AsRenderFrameHostIfValid()!=page->GetPrimaryMainFrame()){Error(std::move(reply),"Capture cancelled or context changed","cancelled");return;}
        if(page->GetRenderWidgetHostView()!=view||view->GetViewBounds()!=view_bounds){Error(std::move(reply),"Capture viewport changed","stale");return;}
        if(!image.has_value()||image->bitmap.drawsNothing()){Error(std::move(reply),"Capture failed","not_ready");return;}
        const auto& bitmap=image->bitmap;
        if(gfx::Size(bitmap.width(),bitmap.height())!=gfx::ScaleToRoundedSize(view_bounds.size(),scale)){Error(std::move(reply),"Unexpected capture image dimensions","not_ready");return;}
        if(annotate){
          auto i=self->snapshots_.find(observation);
          if(i==self->snapshots_.end()||i->second.consumed||i->second.page.get()!=page.get()||i->second.document.AsRenderFrameHostIfValid()!=doc.AsRenderFrameHostIfValid()||base::TimeTicks::Now()-i->second.captured>base::Seconds(30)){Error(std::move(reply),"Annotation observation expired during capture","stale");return;}
          for(const auto& label:labels){
            auto binding=i->second.targets.find(label.ref);
            auto* frame=label.binding.document.AsRenderFrameHostIfValid();
            auto* manager=frame?ui::BrowserAccessibilityManager::FromID(frame->GetAXTreeID()):nullptr;
            auto* node=manager?manager->GetFromID(label.binding.node.id):nullptr;
            auto* live=manager?manager->GetNode(label.binding.node.id):nullptr;
            if(!live||!Visible(live)||live->data().IsIgnored()||binding==i->second.targets.end()||binding->second.document.AsRenderFrameHostIfValid()!=frame||!Same(binding->second.node,label.binding.node)||!frame||!frame->IsActive()||frame->GetAXTreeID().ToString()!=label.binding.frame_id||!node||!Same(label.binding.node,node->GetData())||Protected(node->GetData())||(node->IsOffscreen()||ViewportBounds(node)!=label.screen_bounds)){Error(std::move(reply),"Annotation target or bounds changed during capture","stale");return;}
          }
        }
        base::ListValue annotations;
        gfx::Canvas canvas(gfx::Size(bitmap.width(),bitmap.height()),1.0f,false);
        canvas.DrawImageInt(gfx::ImageSkia::CreateFrom1xBitmap(bitmap),0,0);
        for(const auto& label:labels){
          auto rect=label.screen_bounds;rect.Intersect(gfx::Rect(view_bounds.size()));
          // Convert root-view DIPs with the actual returned bitmap dimensions.
          const double sx=static_cast<double>(bitmap.width())/view_bounds.width(),sy=static_cast<double>(bitmap.height())/view_bounds.height();
          const double x=rect.x()*sx,y=rect.y()*sy,w=rect.width()*sx,h=rect.height()*sy;
          annotations.Append(base::DictValue().Set("ref",label.ref).Set("x",x).Set("y",y).Set("width",w).Set("height",h));
          gfx::Rect outline(static_cast<int>(x),static_cast<int>(y),std::max(1,static_cast<int>(w)),std::max(1,static_cast<int>(h)));
          cc::PaintFlags flags;flags.setColor(SK_ColorRED);flags.setStyle(cc::PaintFlags::kStroke_Style);flags.setStrokeWidth(2);canvas.DrawRect(outline,flags);
          const auto text=base::NumberToString(label.ref);
          const int label_width=std::min(bitmap.width(),static_cast<int>(text.size())*9+8),label_height=std::min(20,bitmap.height());
          gfx::Rect badge(std::clamp(outline.x(),0,bitmap.width()-label_width),std::clamp(outline.y(),0,bitmap.height()-label_height),label_width,label_height);
          flags.setStyle(cc::PaintFlags::kFill_Style);canvas.DrawRect(badge,flags);
          canvas.DrawStringRect(base::UTF8ToUTF16(text),gfx::FontList(),SK_ColorWHITE,badge);
        }
        auto png=gfx::PNGCodec::EncodeBGRASkBitmap(annotate?canvas.GetBitmap():bitmap,false);if(!png||png->size()>3*1024*1024){Error(std::move(reply),"Image budget exceeded");return;}
        auto result=base::DictValue().Set("type","image").Set("media_type","image/png").Set("data",base::Base64Encode(*png)).Set("tab_id",TabId(page.get())).Set("document_id",DocumentId(page.get())).Set("width",bitmap.width()).Set("height",bitmap.height()).Set("scale",scale).Set("scale_x",static_cast<double>(bitmap.width())/view_bounds.width()).Set("scale_y",static_cast<double>(bitmap.height())/view_bounds.height()).Set("viewport",base::DictValue().Set("width",view_bounds.width()).Set("height",view_bounds.height()).Set("unit","DIP")).Set("coordinate_space","viewport image; not an authorized coordinate target").Set("annotated",annotate).Set("annotations",std::move(annotations));
        if(annotate){
          result.Set("observation_id",observation);
          result.Set("annotation_limit",64);
          result.Set("annotation_coverage","first 64 visible unprotected refs in the supplied observation; AX viewport DIP bounds, not hit-test guarantees");
        }
        std::move(reply).Run(0,Encode(std::move(result)));
      },weak_.GetWeakPtr(),generation_,page->GetWeakPtr(),doc,v,view_bounds,scale,annotate,observation,std::move(labels),std::move(reply))));return;
    }if((!mode.empty()&&mode!="semantic"&&mode!="delta")||S(*args,"query").size()>256){Error(std::move(reply),"Unsupported mode or oversized query");return;}Observe(page->GetWeakPtr(),std::move(*args),std::move(reply));return;
  }
  ReadTarget(page,name,*args,std::move(reply));
}
}
