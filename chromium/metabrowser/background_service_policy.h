#ifndef METABROWSER_BACKGROUND_SERVICE_POLICY_H_
#define METABROWSER_BACKGROUND_SERVICE_POLICY_H_

#include <string_view>
#include "base/command_line.h"

namespace metabrowser {

// Browser-internal Google services are separate from website navigation and
// from MetaBrowser's explicitly configured AgentCore providers. The override is
// for native baseline diagnostics, never supplied by a website or renderer.
inline bool AllowGoogleBrowserBackgroundServices() {
  return base::CommandLine::InitializedForCurrentProcess() &&
         base::CommandLine::ForCurrentProcess()->HasSwitch(
             "metabrowser-enable-google-background-services");
}

// Chromium's push messaging service installs this handler only for existing or
// pending website subscriptions. Preserve that permission-controlled transport;
// unrelated built-in clients must not piggyback on it to request their tokens.
inline bool IsWebsitePushApp(std::string_view app_id) {
  return app_id.starts_with("wp:");
}

}  // namespace metabrowser
#endif
