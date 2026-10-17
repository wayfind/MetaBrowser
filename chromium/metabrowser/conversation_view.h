#ifndef METABROWSER_CONVERSATION_VIEW_H_
#define METABROWSER_CONVERSATION_VIEW_H_
#include "ui/views/view.h"
#include "base/values.h"
#include "base/functional/callback.h"
#include <set>
#include <string>
#include <vector>
#include "base/memory/weak_ptr.h"
#include "ui/base/metadata/metadata_header_macros.h"
namespace metabrowser {
// A native, selectable message timeline; tool details are collapsed by default.
class ConversationView:public views::View {
  METADATA_HEADER(ConversationView,views::View)
 public:
  ConversationView();
  ~ConversationView() override;
  void SetStarterCallback(base::RepeatingCallback<void(std::string)> callback){starter_=std::move(callback);}
  void Render(const base::ListValue& messages);
 private:
  void Toggle(size_t index);
  base::RepeatingCallback<void(std::string)> starter_;
  base::ListValue messages_;
  std::set<size_t> expanded_;
  std::vector<std::string> signatures_;
  base::WeakPtrFactory<ConversationView> weak_{this};
};
}
#endif
