#ifndef METABROWSER_ACCOUNT_ENTRY_H_
#define METABROWSER_ACCOUNT_ENTRY_H_
#include <string>
#include "base/callback_list.h"
#include "base/functional/callback.h"
class BrowserWindowInterface;
namespace views { class View; }
namespace content { class WebContents; }
namespace metabrowser {
// UI-sequence-only, public identity metadata. Never credentials or Google state.
struct BrowserAccountState {
  bool logged_in=false;
  bool busy=false;
  std::u16string name,email,detail;
};
BrowserAccountState GetBrowserAccountState();
base::CallbackListSubscription ObserveBrowserAccount(base::RepeatingClosure);
void BindBrowserAccountEntry(views::View*, base::RepeatingClosure);
void OpenBrowserAccount(BrowserWindowInterface*, views::View* anchor);
void OpenBrowserAccountSettings(content::WebContents*);
}
#endif
