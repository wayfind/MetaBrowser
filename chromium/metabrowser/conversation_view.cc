#include "metabrowser/conversation_view.h"
#include "metabrowser/design_tokens.h"
#include "base/functional/bind.h"
#include "base/json/json_writer.h"
#include "base/task/sequenced_task_runner.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/button/md_text_button.h"
namespace metabrowser {
namespace {
views::Label* Label(views::View* parent,std::u16string value,int size,SkColor color,bool bold=false,bool mono=false){
  auto* label=parent->AddChildView(std::make_unique<views::Label>(value));label->SetMultiLine(true);label->SetAllowCharacterBreak(true);label->SetSelectable(true);label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  label->SetFontList(gfx::FontList(mono?std::vector<std::string>{"SF Mono","Menlo"}:std::vector<std::string>{"SF Pro Text","PingFang SC"},gfx::Font::NORMAL,size,bold?gfx::Font::Weight::MEDIUM:gfx::Font::Weight::NORMAL));label->SetEnabledColor(color);return label;
}
void Markdown(views::View* parent,const std::string& text){
  bool code=false;std::string paragraph;
  auto flush=[&]{if(!paragraph.empty()){Label(parent,base::UTF8ToUTF16(paragraph),13,design::kInk);paragraph.clear();}};
  for(auto line:base::SplitStringPiece(text,"\n",base::KEEP_WHITESPACE,base::SPLIT_WANT_ALL)){
    if(base::StartsWith(line,"```")){flush();code=!code;continue;}
    if(code){auto* label=Label(parent,base::UTF8ToUTF16(line),11,design::kSecondary,false,true);label->SetBackground(views::CreateRoundedRectBackground(design::kSubtle,6));label->SetBorder(views::CreateEmptyBorder(gfx::Insets::VH(4,8)));continue;}
    if(line.empty()){flush();continue;}
    std::string value(line);bool heading=base::StartsWith(line,"#");bool bullet=base::StartsWith(line,"- ")||base::StartsWith(line,"* ");
    if(heading||bullet){flush();if(heading){auto first=value.find_first_not_of("# ");value=first==std::string::npos?"":value.substr(first);}else value="• "+value.substr(2);base::ReplaceSubstringsAfterOffset(&value,0,"**","");Label(parent,base::UTF8ToUTF16(value),heading?15:13,design::kInk,heading);}
    else {base::ReplaceSubstringsAfterOffset(&value,0,"**","");if(!paragraph.empty())paragraph+="\n";paragraph+=value;}
  }flush();
}
}
ConversationView::ConversationView(){SetLayoutManager(std::make_unique<views::BoxLayout>(views::BoxLayout::Orientation::kVertical,gfx::Insets::VH(8,2),14));}
ConversationView::~ConversationView()=default;
void ConversationView::Render(const base::ListValue& messages){
  messages_=messages.Clone();
  if(messages.empty()){RemoveAllChildViews();signatures_.clear();}
  if(messages.empty()){
    auto* empty=AddChildView(std::make_unique<views::View>());empty->SetLayoutManager(std::make_unique<views::BoxLayout>(views::BoxLayout::Orientation::kVertical,gfx::Insets::VH(12,6),10));
    Label(empty,u"今天，想完成什么？",20,design::kInk,true);
    Label(empty,u"连接网页信息，推进跨站任务与本地工作。",12,design::kSecondary);
    const std::pair<std::u16string,std::string> suggestions[]={
      {u"总结与梳理  →","请总结当前网页，梳理关键内容和需要进一步确认的问题。"},
      {u"跨网站查证  →","我想在多个网站之间核对信息。请先帮我明确目标与需要用到的网站。"},
      {u"处理本地文件  →","我想处理工作区里的文件。请先查看目录，再和我确认具体任务。"}};
    for(const auto& [title,prompt]:suggestions){auto* button=empty->AddChildView(std::make_unique<views::MdTextButton>(base::BindRepeating([](base::WeakPtr<ConversationView> self,std::string prompt){if(self&&self->starter_)self->starter_.Run(std::move(prompt));},weak_.GetWeakPtr(),prompt),title));design::QuietButton(button);button->SetHorizontalAlignment(gfx::ALIGN_LEFT);button->SetBgColorOverrideDeprecated(design::kSurface);button->SetStrokeColorOverrideDeprecated(design::kBorder);button->SetCustomPadding(gfx::Insets::VH(8,10));}
    return;
  }
  if(signatures_.empty()&&!messages.empty())RemoveAllChildViews();
  size_t index=0;
  for(const auto& item:messages){if(!item.is_dict())continue;const auto& record=item.GetDict();const auto* role=record.FindString("role"),*text=record.FindString("text");if(!role||!text)continue;
    const auto signature=base::WriteJson(record).value_or("")+(expanded_.contains(index)?"expanded":"collapsed");
    if(index<signatures_.size()&&signatures_[index]==signature){index++;continue;}
    const bool replace=index<signatures_.size();if(replace){auto old=RemoveChildViewT(children()[index].get());old.reset();signatures_[index]=signature;}else signatures_.push_back(signature);
    auto* card=AddChildView(std::make_unique<views::View>());ReorderChildView(card,index);index++;card->SetLayoutManager(std::make_unique<views::BoxLayout>(views::BoxLayout::Orientation::kVertical,gfx::Insets(12),8));
    if(const auto* state=record.FindString("state");state&&*state=="discarded"){card->SetVisible(false);continue;}
    if(*role=="user"){card->SetBackground(views::CreateRoundedRectBackground(design::kSubtle,10));Label(card,base::UTF8ToUTF16(*text),13,design::kInk);}
    else if(*role=="tool"){
      card->SetBackground(views::CreateRoundedRectBackground(design::kSubtle,8));const auto* state=record.FindString("state");std::u16string title=(state&&*state=="failed"?u"未完成 · ":state&&*state=="running"?u"执行中 · ":u"已执行 · ")+base::UTF8ToUTF16(*text);
      auto* detail=Label(card,base::UTF8ToUTF16(record.FindString("details")?*record.FindString("details"):""),11,design::kSecondary,false,true);detail->SetVisible(expanded_.contains(index-1));
      auto* button=card->AddChildView(std::make_unique<views::MdTextButton>(base::BindRepeating([](base::WeakPtr<ConversationView> self,size_t index){if(self)base::SequencedTaskRunner::GetCurrentDefault()->PostTask(FROM_HERE,base::BindOnce(&ConversationView::Toggle,self,index));},weak_.GetWeakPtr(),index-1),title));design::QuietButton(button);button->SetHorizontalAlignment(gfx::ALIGN_LEFT);card->ReorderChildView(button,0);
    }else if(*role=="error"||*role=="notice"){
      card->SetBackground(views::CreateRoundedRectBackground(*role=="error"?SkColorSetRGB(255,239,235):design::kSubtle,9));Label(card,*role=="error"?u"需要处理":u"会话提示",10,*role=="error"?SkColorSetRGB(158,70,54):design::kAccent,true);Label(card,base::UTF8ToUTF16(*text),12,SkColorSetRGB(90,71,79));
    }else{card->SetBackground(views::CreateRoundedRectBackground(design::kSurface,10));Markdown(card,*text);if(text->empty())Label(card,u"正在组织回复…",12,design::kMuted);}
  }InvalidateLayout();
}
void ConversationView::Toggle(size_t index){if(expanded_.contains(index))expanded_.erase(index);else expanded_.insert(index);Render(messages_);}
BEGIN_METADATA(ConversationView)
END_METADATA
}
