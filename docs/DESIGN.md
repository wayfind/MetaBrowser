# Metask browser design

The native browser follows Metask's public visual identity and takes interaction
inspiration from Comet's collapsible, page-adjacent assistant. This is an independent
implementation, not Perplexity's private design system.

References inspected 2026-10-15:
- https://app.metask-ai.com/
- https://www.perplexity.ai/comet/resources/articles/comet-quick-start-guide

## Visual language

Public Metask rendered colors: #FAFAFA canvas, #FFFFFF surface, #1F1F1F text,
#595959 secondary text, #E6E6E6 borders, #8A4ED1 brand. Native design tokens live
in chromium/metabrowser/design_tokens.h. Purple identifies selection and brand;
primary actions use ink with white text. Chromium system emphasis uses the actual
brand purple; a zero-saturation seed otherwise falls back to cyan. Avoid full-panel lavender and default
Chrome-blue button outlines. System SF Pro / PingFang preserve native typography
and Chinese readability. Focus rings remain platform supplied for accessibility.

The rail uses the official Metask SVG geometry, converted losslessly into native
vector path commands (brand_mark.h); the source SVG is preserved in branding/.
Icon buttons use Chromium's native ink-drop, hover and focus behavior.

## Hierarchy and behavior

- Web content retains the main canvas. The assistant remains resizable/collapsible
  through Chromium's side panel; its four navigation icons remain on the far right.
- A single compact top row contains scrollable conversation tabs, history and new
  conversation. Closing a tab preserves history, draft and committed checkpoint.
- The assistant header contains identity and real lifecycle status. Empty state
  uses Metask's “今天，想完成什么？” with three task starters. Starters only fill and
  focus the composer; they never submit, run tools or overwrite a running task.
- Composer is a small white surface: multiline input above attachment/screenshot
  icons, actual model selector and send. Remove appears only with attachments;
  stop replaces send only while busy. Enter/Shift+Enter and IME semantics unchanged.
- User messages are neutral surfaces. Assistant content is open reading space;
  tool detail remains collapsed. Permission requests are distinguishable inline
  decisions with explicit allow/reject and no hidden auto-approval.
- Configuration starts with account and workspace; provider endpoints, API keys
  and fallback login flows are behind “高级连接设置”. Fields keep visible labels
  after values are entered. No changes to authentication,
  provider selection, permission defaults or SDK ownership.

## Verification scope

Build the native Views code on H200 targeting macOS ARM64, verify the copied
framework digest, inspect the real packaged window, exercise task starters,
conversation switching, settings disclosure, all four sections and attachment
controls. Local fixtures cover send/stop, permission, MCP, Skills and history;
real account/model verification does not require a paid inference request.

## Space refinement

The entry opts out of Chromium's separate side-panel header. Conversation tabs,
history, new conversation, pin and sidebar close now share one compact toolbar.
Pin uses the real per-profile PinnedToolbarActionsModel and observes external
changes; it is not a decorative state. Close uses the existing side-panel lifecycle
so active Runs are cancelled by the same entry observer.

A tab's title and 24×28 close target share one rounded selection surface. Close is
queued using the stable conversation ID. Closing an inactive tab preserves the
active conversation, including when its index shifts. The tab viewport scrolls
with compositor layers, uses the strip’s natural width, and reveals the selected
tab without reserving a scrollbar row. Closing the final tab creates
a fresh usable conversation while keeping the closed record in history.

The repeated assistant heading is removed; the rail retains the brand. Lifecycle
status uses the footer on non-chat sections. Chat has no standalone footer;
keyboard help lives in tooltips and Stop replaces Send while a Run is active. The default composer has two rows:
a 22 logical px text area followed by a single Plus menu on the left and
context percentage, a model/reasoning menu, and circular Send/Stop on the right. Send stays at the trailing edge after navigation between sections.
Plus exposes image/file upload, page capture, local Skill and MCP controls.
Every model exposes light/standard/deep/extended reasoning. An explicit
Host selection reaches OpenAI-compatible servers as the original reasoning_effort
without model-family gating or local strength collapse. Server errors remain
visible; the client never silently switches to model default. The percentage uses committed-context estimates and an
effective input limit after output reserve and learned endpoint caps. Tooltips
state whether the estimate has a provider anchor or excludes full system/tool
overhead. Drafts are excluded. Refresh and compaction are explicit menu actions.
The prompt grouping follows the requested ChatGPT-style two-row interaction.
The text area grows with actual wrapped/newline content
to 112 px, then scrolls internally. Draft, task-starter and resize paths update the
same native measurement. The empty state removes repeated branding and tightens
spacing without changing its explicit-submit behavior.

The model selector clears and reapplies its selected index after catalogue changes
so its accessible value matches the displayed model even when index zero remains
selected. Independent API settings do not invoke the account-only model path.

Native geometry acceptance covers the single toolbar row, close target alignment,
background-tab preservation, text-area growth/shrink, a 600-high window, real pin /
close / reopen, last-tab recovery, and no inference request from layout actions.

Chromium intentionally destroys the side-panel view on a full close. A window-owned
SidePanelEntry property therefore retains the ordered UI snapshots and selected
tab, including volatile private connection controls. Only credential-free record
snapshots go to ConversationStore; private controls remain in window memory and
are released with the entry. Reopening restores UI state and recreates SDK Sessions
under the existing checkpoint/permission rules. It never automatically replays a
user request. The QA-only demo prompt is admitted once per entry, not on reopen.
