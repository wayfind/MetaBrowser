// Toolbar click opens the side panel; it stays available on every tab (browser-wide scope).
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
