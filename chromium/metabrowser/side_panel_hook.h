#ifndef METABROWSER_SIDE_PANEL_HOOK_H_
#define METABROWSER_SIDE_PANEL_HOOK_H_
#include "chrome/browser/ui/side_panel/side_panel_entry.h"
class SidePanelRegistry;
namespace metabrowser {
// The embedding supplies a native view factory. No extension or remote URL.
// Factory lifetime must exceed the registry. Called on the browser UI sequence.
bool RegisterMetaCodesPanel(SidePanelRegistry& registry);
bool RegisterMetaCodesPanel(SidePanelRegistry& registry,
                           SidePanelEntry::CreateContentCallback factory);
}
#endif
