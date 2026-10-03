// Opened briefly by the daemon at startup. chrome.sidePanel.open() requires a user gesture;
// the daemon invokes openPanel() via CDP Runtime.evaluate(userGesture=true), then closes this tab.
"use strict";
async function openPanel() {
  const win = await chrome.windows.getCurrent();
  await chrome.sidePanel.open({ windowId: win.id });
  return win.id;
}
window.openPanel = openPanel;
