#!/usr/bin/env python3
"""Stage independent hook sources into the pinned Chromium tree, idempotently."""
import argparse, os, pathlib, re, shutil, time


def copy_authored_file(source, destination):
    """Keep identical staged inputs untouched; bound copied future mtimes."""
    source_path = pathlib.Path(source)
    destination_path = pathlib.Path(destination)
    if (destination_path.is_file() and
            source_path.read_bytes() == destination_path.read_bytes()):
        return str(destination)
    result = shutil.copy2(source, destination)
    copied = destination_path.stat()
    now = time.time_ns()
    if copied.st_mtime_ns > now:
        os.utime(destination, ns=(copied.st_atime_ns, now))
    return result


def write_if_changed(path, text):
    """Preserve mtimes for identical engine inputs and their Ninja consumers."""
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def replace_required(source, old, new, label):
    if source.count(old) != 1:
        raise SystemExit('Settings anchor changed: ' + label)
    return source.replace(old, new, 1)


def stage_personalization_html(source):
    marker = '<!-- METABROWSER_PERSONALIZATION_ACCOUNT_CLEANUP -->'
    if marker not in source:
        if 'id="signinAllowedToggle"' in source:
            start = source.find('<if expr="not is_chromeos">', source.find('#html_wrapper_imports_end'))
            end = source.find('</if><!-- not chromeos -->', start)
            if start < 0 or end < 0 or 'id="chromeSigninUserChoiceSelection"' not in source[start:end]:
                raise SystemExit('Google signin preferences anchor changed')
            source = source[:start] + source[end + len('</if><!-- not chromeos -->'):]
        source = source.replace("import {ChromeSigninUserChoice} from '/shared/settings/people_page/sync_browser_proxy.js';\n", '')
        source = replace_required(source, '''    ${this.showSignoutDialog_ ? html`
      <settings-signout-dialog .syncStatus="${this.syncStatus}"
          @close="${this.onSignoutDialogClose_}">
      </settings-signout-dialog>
    ` : ''}
''', '', 'personalization signout dialog')
        source = replace_required(source, '''    <cr-toast id="toast">
      <div>$i18n{restartToApplyChanges}</div>
      <cr-button @click="${this.onRestartClick_}">$i18n{restart}</cr-button>
    </cr-toast>
''', '', 'signin restart toast')
        source = replace_required(source, '''    <cr-toast id="chromeSigninUserChoiceToast" duration="5000">
      <div>$i18n{chromeSigninChoiceToast}</div>
    </cr-toast>
''', '', 'signin choice toast')
        source += '\n' + marker + '\n'
    for token in ('signinAllowedToggle', 'chromeSigninUserChoice', 'showSignoutDialog_', 'onSignoutDialogClose_'):
        if token in source:
            raise SystemExit('Stale personalization HTML reference: ' + token)
    return source


def stage_personalization_ts(source):
    marker = '// METABROWSER_PERSONALIZATION_ACCOUNT_CLEANUP'
    if marker not in source:
        replacements = [
            ("import '../people_page/signout_dialog.js';\n", ''),
            ("import '//resources/cr_elements/cr_toast/cr_toast.js';\n", ''),
            ("import type {CrToastElement} from '//resources/cr_elements/cr_toast/cr_toast.js';\n", ''),
            ("import {assert} from '//resources/js/assert.js';\n", ''),
            ('import type {ChromeSigninUserChoiceInfo, SyncBrowserProxy, SyncStatus}', 'import type {SyncStatus}'),
            ('import {ChromeSigninUserChoice, SignedInState, StatusAction, SyncBrowserProxyImpl}', 'import {SignedInState, StatusAction}'),
            ("import type {SettingsSignoutDialogElement} from '../people_page/signout_dialog.js';\n", ''),
            ('    toast: CrToastElement,\n', ''),
            ('    signinAllowedToggle: SettingsToggleButtonElement,\n', ''),
            ('    chromeSigninUserChoiceSelection: HTMLSelectElement,\n', ''),
            ('    chromeSigninUserChoiceToast: CrToastElement,\n', ''),
            ('      showSignoutDialog_: {type: Boolean},\n\n', ''),
            ('''      // <if expr="not is_chromeos">
      signinAvailable_: {type: Boolean},

      chromeSigninUserChoiceInfo_: {type: Object},
      // </if>

''', ''),
            ('  protected accessor showSignoutDialog_: boolean = false;\n', ''),
            ('''  // <if expr="not is_chromeos">
  protected accessor signinAvailable_: boolean =
      loadTimeData.getBoolean('signinAvailable');

  protected accessor chromeSigninUserChoiceInfo_: ChromeSigninUserChoiceInfo|
      undefined;
  // </if>

''', ''),
            ('''  private syncBrowserProxy_: SyncBrowserProxy =
      SyncBrowserProxyImpl.getInstance();

''', ''),
            ('''    // <if expr="not is_chromeos">
    this.syncBrowserProxy_.getChromeSigninUserChoiceInfo().then(
        this.setChromeSigninUserChoiceInfo_.bind(this));
    this.addWebUiListener(
        'chrome-signin-user-choice-info-change',
        this.setChromeSigninUserChoiceInfo_.bind(this));
    // </if>

''', ''),
        ]
        for old, new in replacements:
            source = replace_required(source, old, new, old.splitlines()[0])
        for method in ('onSignoutDialogClose_', 'onSigninAllowedSettingsBooleanControlChange_',
                       'setChromeSigninUserChoiceInfo_', 'onChromeSigninChoiceChange_'):
            pattern = r'^  (?:protected|private) ' + method + r'\([^\n]*\) \{.*?^  \}\n\n?'
            source, count = re.subn(pattern, '', source, flags=re.M | re.S)
            if count != 1:
                raise SystemExit('Settings method anchor changed: ' + method)
        source += '\n' + marker + '\n'
    for token in ('signinAllowedToggle', 'chromeSigninUserChoice', 'ChromeSigninUserChoice',
                  'signinAvailable_', 'showSignoutDialog_', 'SignoutDialog', 'onSignoutDialogClose_',
                  'onSigninAllowedSettingsBooleanControlChange_', 'syncBrowserProxy_', 'CrToastElement'):
        if token in source:
            raise SystemExit('Stale personalization TS reference: ' + token)
    return source


def stage_people_ts(source):
    handler = "  protected onMetabrowserAccountClick_() {\n    chrome.send('metabrowserAccountOpen');\n  }\n\n"
    if 'onMetabrowserAccountClick_' not in source:
        source = replace_required(source, '  protected onProfileClick_() {',
                                  handler + '  protected onProfileClick_() {', 'Metask account handler')
    elif source.count(handler) != 1:
        raise SystemExit('Metask account handler changed')
    if source.count('importDataDialogTrigger: HTMLElement,') != 1 or source.count('focusWithoutInk(this.$.importDataDialogTrigger);') != 1:
        raise SystemExit('Import dialog focus contract changed')
    return source


p = argparse.ArgumentParser()
p.add_argument('source', type=pathlib.Path)
a = p.parse_args()
project = pathlib.Path(__file__).resolve().parents[1]
version = (a.source / 'chrome/VERSION').read_text()
if version.splitlines() != ['MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']:
    raise SystemExit('Unexpected Chromium version')
shutil.copytree(project / 'chromium/metabrowser', a.source / 'metabrowser',
                dirs_exist_ok=True, copy_function=copy_authored_file)
f = a.source / 'chrome/browser/ui/side_panel/side_panel_entry_id.h'
s = f.read_text()
if 'V(kMetaCodes,' not in s:
    anchor = '  /* Extensions (nothing more should be added below here) */'
    if s.count(anchor) != 1: raise SystemExit('Side panel anchor changed')
    s = s.replace(anchor, '  V(kMetaCodes, std::nullopt, "MetaCodes")' + ' ' * 35 + '\\\n' + anchor)
    write_if_changed(f, s)
f = a.source / 'BUILD.gn'
s = f.read_text()
if 'group("metabrowser_hooks")' not in s:
    write_if_changed(f, s + '\nif (is_mac || is_linux || is_win) {\n  group("metabrowser_hooks") {\n    deps = [ "//metabrowser:side_panel_hook" ]\n  }\n}\n')

f = a.source / 'chrome/browser/ui/browser_window/internal/browser_window_features.cc'
s = f.read_text()
if '#include "metabrowser/side_panel_hook.h"' not in s:
    anchor = '#include <memory>'
    if s.count(anchor) != 1: raise SystemExit('Window include anchor changed')
    s = s.replace(anchor, anchor + '\n#include "metabrowser/side_panel_hook.h"')
    anchor = '      GetUserDataFactory().CreateInstance<SidePanelRegistry>(*browser, browser);'
    if s.count(anchor) != 1: raise SystemExit('Window registry anchor changed')
    s = s.replace(anchor, anchor + '\n  if (side_panel_registry_) {\n    metabrowser::RegisterMetaCodesPanel(*side_panel_registry_);\n  }')
    write_if_changed(f, s)
# Remove an earlier staging-only dependency from the wrong target.
f = a.source / 'chrome/browser/ui/BUILD.gn'
s = f.read_text()
write_if_changed(f, s.replace('      "//metabrowser:side_panel_hook",\n', ''))
f = a.source / 'chrome/browser/ui/browser_window/internal/BUILD.gn'
s = f.read_text()
anchor = '"//chrome/browser/ui/views/side_panel",'
if '"//metabrowser:side_panel_hook"' not in s:
    if s.count(anchor) != 1: raise SystemExit('Window dependency anchor changed')
    write_if_changed(f, s.replace(anchor, anchor + '\n      "//metabrowser:side_panel_hook",'))
f = a.source / 'tools/metrics/histograms/metadata/browser/histograms.xml'
s = f.read_text()
anchor = '<variants name="SidePanelEntry">'
if '<variant name="MetaCodes"' not in s:
    if s.count(anchor) != 1: raise SystemExit('Histogram anchor changed')
    write_if_changed(f, s.replace(anchor, anchor + '\n  <variant name="MetaCodes" summary="MetaCodes native agent panel"/>'))

# Give the native entry a real action (the coordinator requires one).
f = a.source / 'chrome/browser/ui/actions/chrome_action_id.h'
s = f.read_text()
anchor = '  E(kActionSidePanelShowSearchCompanion)'
if 'E(kActionSidePanelShowMetaCodes)' not in s:
    if s.count(anchor) != 1: raise SystemExit('Action id anchor changed')
    write_if_changed(f, s.replace(anchor, '  E(kActionSidePanelShowMetaCodes) \\\n' + anchor))
f = a.source / 'chrome/browser/ui/side_panel/side_panel_entry_id.h'
s = f.read_text().replace('V(kMetaCodes, std::nullopt,', 'V(kMetaCodes, kActionSidePanelShowMetaCodes,')
write_if_changed(f, s)

# Google browser-signin controls are not available through service settings.
f = a.source / 'chrome/browser/resources/settings/privacy_page/personalization_options.html'
write_if_changed(f, stage_personalization_html(f.read_text()))
f = a.source / 'chrome/browser/resources/settings/privacy_page/personalization_options.ts'
write_if_changed(f, stage_personalization_ts(f.read_text()))

# Lightweight header dependencies; no dependency on the complete native host.
for path in ['chrome/browser/ui/toolbar/BUILD.gn','chrome/browser/ui/webui/settings/BUILD.gn']:
    f=a.source/path;s=f.read_text();start=s.find('source_set("impl") {')
    if start<0:raise SystemExit('Native account implementation GN target changed: '+path)
    pos=s.find('deps = [',start)
    if pos<0:raise SystemExit('Native account implementation deps changed')
    end=s.find(']',pos)
    if '"//metabrowser:account_entry"' not in s[pos:end]:
        s=s[:pos+len('deps = [')]+'\n    "//metabrowser:account_entry",'+s[pos+len('deps = ['):]
        write_if_changed(f, s)
f = a.source / 'chrome/browser/ui/browser_actions.cc'
s = f.read_text()
anchor = '  if (TabsFromOtherDevicesSidePanelCoordinator::IsSupported(profile)) {'
if 'SidePanelEntryId::kMetaCodes' not in s:
    if s.count(anchor) != 1: raise SystemExit('Browser actions anchor changed')
    s = s.replace(anchor, '  root_action_item_->AddChild(\n      SidePanelAction(SidePanelEntryId::kMetaCodes, IDS_READ_LATER_TITLE,\n                      IDS_READ_LATER_TITLE, kListAltIcon,\n                      kActionSidePanelShowMetaCodes, bwi, true)\n          .SetText(u"MetaCodes").SetTooltipText(u"MetaCodes").Build());\n' + anchor)
    write_if_changed(f, s)
f = a.source / 'chrome/browser/ui/browser_window/internal/browser_window_features.cc'
s = f.read_text()
anchor = '  embedder_browser_window_features_->InitPostWindowConstruction(browser);'
if 'Show(SidePanelEntryId::kMetaCodes)' not in s:
    if s.count(anchor) != 1: raise SystemExit('Post-window anchor changed')
    write_if_changed(f, s.replace(anchor, anchor + '\n  if (auto* panel = SidePanelUI::From(browser)) {\n    panel->Show(SidePanelEntryId::kMetaCodes);\n  }'))

# Replace the real toolbar account entry, including its interaction and all
# identity presentation. Do not merely overlay or relabel a Google sign-in UI.
f = a.source / 'chrome/browser/ui/views/profiles/avatar_toolbar_button.cc'
s = f.read_text()
include = '#include "metabrowser/account_entry.h"'
if include not in s:
    anchor = '#include "chrome/browser/ui/views/profiles/avatar_toolbar_button.h"'
    if s.count(anchor) != 1: raise SystemExit('Avatar include anchor changed')
    s = s.replace(anchor, anchor + '\n' + include)
def replace_body(source, signature, body):
    start = source.find(signature)
    if start < 0: raise SystemExit('Avatar function anchor changed: '+signature)
    brace = source.find('{', start)
    # Chromium method terminators are at column zero; nested blocks are not.
    end = source.find('\n}', brace)
    if end < 0: raise SystemExit('Avatar method terminator changed')
    return source[:brace] + '{\n' + body.rstrip() + '\n}' + source[end+2:]
s = replace_body(s, 'void AvatarToolbarButton::UpdateText()', '''  if (!GetWidget()) return;
  const auto account = metabrowser::GetBrowserAccountState();
  const std::u16string text = account.busy ? u"账户连接中…" :
      account.logged_in ? account.name.substr(0, 24) : u"登录 Metask";
  slide_animation_.Reset(1.0);
  SetHighlight(text, std::nullopt);
  label()->SetElideBehavior(gfx::ELIDE_TAIL);
  SetTooltipText(account.logged_in ? u"Metask 账户 · " + account.name : u"登录 app.metask-ai.com 账户");
  UpdateAccessibilityLabel();
  UpdateLayoutInsets();
  UpdateInkdrop();
  views::FocusRing::Get(this)->SetOutsetFocusRingDisabled(false);
  SizeToPreferredSize();
  InvalidateLayout();''')
s = replace_body(s, 'void AvatarToolbarButton::UpdateIcon()', '''  if (!GetWidget()) return;
  const int size = GetIconSize();
  const SkColor color = GetColorProvider()->GetColor(kColorToolbarButtonIcon);
  auto icon = ui::ImageModel::FromImage(profiles::GetSizedAvatarIcon(
      profiles::GetPlaceholderAvatarIconWithColors(color, color, size,
          profiles::PlaceholderAvatarIconParams{.has_padding=false, .has_background=false}),
      size, size, profiles::SHAPE_CIRCLE));
  forced_colors_normal_icon_ = ui::ImageModel();
  forced_colors_hovered_icon_ = ui::ImageModel();
  SetImageModel(ButtonState::STATE_NORMAL, icon);
  SetImageModel(ButtonState::STATE_DISABLED, ui::GetDefaultDisabledIconFromImageModel(icon));
  SetImageModel(ButtonState::STATE_HOVERED, std::nullopt);
  SetImageModel(ButtonState::STATE_PRESSED, std::nullopt);
  UpdateLayoutInsets();
  state_manager_.NotifyIconUpdated();''')
s = replace_body(s, 'void AvatarToolbarButton::UpdateAccessibilityLabel()', '''  const auto account = metabrowser::GetBrowserAccountState();
  GetViewAccessibility().SetName(account.logged_in ? u"Metask 账户 · " + account.name : u"登录 Metask");
  GetViewAccessibility().SetDescription(u"打开 app.metask-ai.com 账户");''')
s = replace_body(s, 'void AvatarToolbarButton::ButtonPressed(bool is_source_accelerator)', '''  metabrowser::OpenBrowserAccount(state_manager_.browser(), this);''')
s = replace_body(s, 'void AvatarToolbarButton::UpdateLayoutInsets()', '''  SetLayoutInsets(gfx::Insets::VH(6, 10));
  SetHorizontalAlignment(gfx::ALIGN_LEFT);''')
s = replace_body(s, 'bool AvatarToolbarButton::ShouldPaintBorder() const', '  return true;')
s = replace_body(s, 'std::optional<SkColor> AvatarToolbarButton::GetHighlightTextColor() const', '''  if (!GetWidget()) return std::nullopt;
  return GetColorProvider()->GetColor(kColorToolbarButtonIcon);''')
for signature in [
    'void AvatarToolbarButton::MaybeShowProfileSwitchIPH()',
    'void AvatarToolbarButton::MaybeShowSupervisedUserSignInIPH()',
    'void AvatarToolbarButton::MaybeShowSignInBenefitsIPH()',
    'void AvatarToolbarButton::MaybeShowExplicitBrowserSigninPreferenceRememberedIPH(']:
    s = replace_body(s, signature, '  // MetaBrowser owns browser identity and sign-in UI.')
s = s.replace('SetHasPopup(ax::mojom::HasPopup::kMenu)', 'SetHasPopup(ax::mojom::HasPopup::kDialog)')
if 'metabrowser::BindBrowserAccountEntry(this,' not in s:
    anchor = '  slide_animation_.SetSlideDuration(base::Milliseconds(200));'
    if s.count(anchor) != 1: raise SystemExit('Avatar subscription anchor changed')
    s = s.replace(anchor, anchor + '''
  metabrowser::BindBrowserAccountEntry(this,
      base::BindRepeating(&AvatarToolbarButton::UpdateText, weak_ptr_factory_.GetWeakPtr()));''')
write_if_changed(f, s)
# Keep AvatarToolbarButton's class layout intact. Its existing callers were
# compiled with the pinned engine; subscription ownership is a View property.
f = a.source / 'chrome/browser/ui/views/profiles/BUILD.gn'
s = f.read_text()
anchor = '  source_set("avatar_toolbar_button_impl") {'
start = s.find(anchor)
if start < 0: raise SystemExit('Avatar GN target changed')
end = s.find('  source_set(', start+len(anchor))
end = len(s) if end < 0 else end
target = s[start:end]
if '"//metabrowser:account_entry"' not in target:
    target = target.replace('    deps = [', '    deps = [\n      "//metabrowser:account_entry",', 1)
    s = s[:start]+target+s[end:]
    write_if_changed(f, s)

# App menu account subsection uses Metask as well; no Google sync/management UI.
f = a.source / 'chrome/browser/ui/toolbar/app_menu_model.cc'
s = f.read_text()
if include not in s:
    s = include+'\n'+s
s = replace_body(s, 'bool ProfileSubMenuModel::BuildSyncSection()', '''  const auto account = metabrowser::GetBrowserAccountState();
  AddItem(IDC_SHOW_AVATAR_MENU, account.logged_in ? u"Metask 账户 · " + account.name : u"登录 Metask 账户");
  return true;''')
s = replace_body(s, 'void ProfileSubMenuModel::BuildManageGoogleAccountRow(Profile* profile)', '  // Browser accounts are provided by app.metask-ai.com.')
s = s.replace('[[maybe_unused]] std::u16string GetSyncSectionTitle(', 'std::u16string GetSyncSectionTitle(')
s = s.replace('std::u16string GetSyncSectionTitle(', '[[maybe_unused]] std::u16string GetSyncSectionTitle(')
anchor = '  BuildManageGoogleAccountRow(profile);'
if '  // METABROWSER_ACCOUNT_MENU' not in s:
    if s.count(anchor) != 1: raise SystemExit('Profile menu presentation anchor changed')
    s = s.replace(anchor, '''  // METABROWSER_ACCOUNT_MENU
  const auto metask = metabrowser::GetBrowserAccountState();
  profile_name_ = metask.logged_in ? metask.name : u"Metask · app.metask-ai.com";
  accessible_name_ = profile_name_;
  avatar_image_model_ = ui::ImageModel::FromVectorIcon(kAccountCircleIcon, ui::kColorMenuIcon, avatar_icon_size);
''' + anchor)
write_if_changed(f, s)
# Old command IDs remain internal ABI, but can no longer initiate Google auth.
f = a.source / 'chrome/browser/ui/browser_command_controller.cc'
s = f.read_text()
for command in ['IDC_TURN_ON_SYNC','IDC_SHOW_SIGNIN','IDC_SHOW_SIGNIN_WHEN_PAUSED','IDC_SHOW_SYNC_SETTINGS']:
    pattern = r'(    case '+command+r':\n).*?(      break;)'
    s,count = re.subn(pattern,lambda m:m[1]+'      ShowAvatarMenu(browser_);\n'+m[2],s,count=1,flags=re.S)
    if count != 1: raise SystemExit('Account command anchor changed: '+command)
pattern = r'    case IDC_MANAGE_GOOGLE_ACCOUNT: \{.*?\n    \}'
s,count = re.subn(pattern,'    case IDC_MANAGE_GOOGLE_ACCOUNT: {\n      ShowAvatarMenu(browser_);\n      break;\n    }',s,count=1,flags=re.S)
if count != 1: raise SystemExit('Manage account command anchor changed')
write_if_changed(f, s)

# Settings renders an actual Metask account card. Google sync/account routes
# show this same card instead of rebranding unsupported Google sync as Metask.
f = a.source / 'chrome/browser/resources/settings/people_page/people_page.ts'
write_if_changed(f, stage_people_ts(f.read_text()))
f = a.source / 'chrome/browser/resources/settings/people_page/people_page.html.ts'
write_if_changed(f, '''import {html} from '//resources/lit/v3_0/lit.rollup.js';
import type {SettingsPeoplePageElement} from './people_page.js';
export function getHtml(this: SettingsPeoplePageElement) {
  return html`<!--_html_template_start_-->
    <settings-section page-title="Metask 账户">
      <div class="cr-row first two-line" style="padding-block:24px;gap:24px">
        <div class="flex cr-padded-text"><div style="font-size:24px;font-weight:600">Metask</div><div class="secondary" style="margin-top:8px">app.metask-ai.com</div></div>
        <cr-button class="action-button" @click="${this.onMetabrowserAccountClick_}">打开 Metask 账户</cr-button>
      </div>
      <div class="cr-row">使用 Metask 账户连接浏览器、模型与 Agent。</div>
      <cr-link-row id="importDataDialogTrigger" label="导入书签与设置" @click="${this.onImportDataClick_}"></cr-link-row>
    </settings-section>
    ${this.showImportDataDialog_ ? html`<settings-import-data-dialog @close="${this.onImportDataDialogClose_}"></settings-import-data-dialog>` : ''}
    <cr-toast id="toast" duration="3000"><span>设置已保存</span></cr-toast>
  <!--_html_template_end_-->`;
}
''')
f = a.source / 'chrome/browser/resources/settings/people_page/people_page_index.html.ts'
s = f.read_text()
for old in ['settings-sync-page','settings-sync-controls-page','settings-account-page']:
    s = s.replace('<'+old+' ', '<settings-people-page ').replace('</'+old+'>','</settings-people-page>')
write_if_changed(f, s)
f = a.source / 'chrome/browser/ui/webui/settings/people_handler.cc'
s = f.read_text()
if include not in s:s = include+'\n'+s
if '"metabrowserAccountOpen"' not in s:
    anchor = 'void PeopleHandler::RegisterMessages() {'
    if s.count(anchor) != 1: raise SystemExit('Settings handler anchor changed')
    s = s.replace(anchor,anchor+'''
  web_ui()->RegisterMessageCallback("metabrowserAccountOpen",
      base::BindRepeating([](PeopleHandler* self,const base::ListValue&){
        metabrowser::OpenBrowserAccountSettings(self->web_ui()->GetWebContents());
      },base::Unretained(this)));''')
write_if_changed(f, s)
f = a.source / 'chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc'
s = f.read_text()
start=s.find('void AddPeopleStrings(')
pos=s.find('  html_source->AddLocalizedStrings(kLocalizedStrings);',start)
if start<0 or pos<0:raise SystemExit('Settings account title anchor changed')
anchor='  html_source->AddLocalizedStrings(kLocalizedStrings);'
addition='\n  html_source->AddString("peoplePageTitle",u"Metask 账户");'
if s[pos+len(anchor):pos+len(anchor)+len(addition)]!=addition:
    s=s[:pos+len(anchor)]+addition+s[pos+len(anchor):]
write_if_changed(f, s)
