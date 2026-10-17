#ifndef METABROWSER_IDENTITY_PROFILES_H_
#define METABROWSER_IDENTITY_PROFILES_H_

#include <memory>
#include <string>
#include "ui/views/view.h"

namespace metabrowser {
// UI only. Creating an identity never copies website or agent credentials.
std::unique_ptr<views::View> CreateIdentityProfilesView();
// Independent global browser settings window; never creates an Agent session.
void ShowIdentityProfilesSettings(const std::u16string& account_summary);
}  // namespace metabrowser
#endif
