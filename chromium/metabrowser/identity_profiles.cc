#include "metabrowser/identity_profiles.h"
#include "components/metabrowser_identity/platform_version_policy.h"
#include "third_party/blink/public/common/user_agent/metabrowser_persona.h"

#include <cstdlib>
#include <array>
#include <memory>
#include <set>
#include <string>
#include <vector>
#include <CoreFoundation/CoreFoundation.h>

#include "base/apple/foundation_util.h"
#include "base/apple/scoped_cftyperef.h"
#include "base/command_line.h"
#include "base/base_paths.h"
#include "base/files/file.h"
#include "base/files/file_enumerator.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/i18n/tag_converters.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/path_service.h"
#include "base/process/launch.h"
#include "base/strings/string_util.h"
#include "base/strings/sys_string_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/thread_pool.h"
#include "base/uuid.h"
#include "metabrowser/design_tokens.h"
#include "third_party/icu/source/common/unicode/strenum.h"
#include "third_party/icu/source/i18n/unicode/timezone.h"
#include "ui/base/models/simple_combobox_model.h"
#include "ui/base/l10n/l10n_util.h"
#include "ui/color/color_id.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/combobox/combobox.h"
#include "ui/views/controls/label.h"
#include "ui/views/controls/textfield/textfield.h"
#include "ui/views/controls/scroll_view.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/window/dialog_delegate.h"
#include "ui/views/widget/widget.h"

namespace metabrowser {
namespace {
constexpr std::array<const char*, 4> kLanguages = {"system", "zh-CN,zh", "en-US,en", "ja-JP,ja"};
constexpr std::array<const char*, 3> kWindows = {"system", "1280,900", "1440,1000"};
constexpr std::array<const char*, 7> kTimezones = {
    "system", "UTC", "Asia/Shanghai", "Asia/Tokyo", "Europe/London",
    "America/New_York", "America/Los_Angeles"};
constexpr std::array<const char*, 3> kWebRTCPolicies = {
    "default_public_interface_only", "disable_non_proxied_udp", "system"};
constexpr std::array<const char*, 5> kDisplays = {
    "1440x900", "1680x1050", "1920x1200", "2560x1600", "system"};
constexpr std::array<const char*, 2> kGPUs = {"native", "software"};
constexpr std::array<const char*, 2> kPlatformVersionPolicies = {"major", "system"};
bool KnownTimezone(const std::string& timezone) {
  for (const auto* preset : kTimezones) if (timezone == preset) return true;
  // Named zones only. Custom GMT/POSIX syntax and arbitrary TZ paths are not
  // accepted; the pinned ICU database is authoritative for Date and Intl.
  static const base::NoDestructor<std::set<std::string>> zones([] {
    std::set<std::string> result;
    std::unique_ptr<icu::StringEnumeration> names(icu::TimeZone::createEnumeration());
    if (!names) return result;
    UErrorCode status = U_ZERO_ERROR;
    while (const char* name = names->next(nullptr, status)) {
      if (U_FAILURE(status)) break;
      result.insert(name);
    }
    return result;
  }());
  return zones->contains(timezone);
}
std::string Env(const char* name) {
  const char* value = getenv(name);
  return value ? value : "";
}
std::string SystemLanguages() {
  base::apple::ScopedCFTypeRef<CFArrayRef> preferred(CFLocaleCopyPreferredLanguages());
  std::vector<std::string> languages;
  std::set<std::string> seen;
  if (preferred) {
    for (CFIndex i = 0; i < CFArrayGetCount(preferred.get()) && languages.size() < 32; ++i) {
      const auto value = base::apple::CFCast<CFStringRef>(
          CFArrayGetValueAtIndex(preferred.get(), i));
      if (!value) continue;
      const auto tag = base::i18n::GetLanguageTagFromString(base::SysCFStringRefToUTF8(value));
      if (!tag) continue;
      std::string language(tag->tag_string());
      if (seen.insert(language).second) languages.push_back(std::move(language));
    }
  }
  languages = l10n_util::KeepAcceptedLanguages(languages);
  return languages.empty() ? "en-US,en" : base::JoinString(languages, ",");
}
base::FilePath Root() {
  const auto override = Env("METABROWSER_IDENTITY_HOME");
  return override.empty()
      ? base::FilePath(Env("HOME")).AppendASCII(
            "Library/Application Support/MetaBrowser/identities")
      : base::FilePath(override);
}
bool ValidId(const std::string& id) {
  return base::Uuid::ParseLowercase(id).is_valid();
}
bool SafeDirectory(const base::FilePath& path) {
  return path.IsAbsolute() && !base::IsLink(path) &&
         base::CreateDirectory(path) &&
         base::SetPosixFilePermissions(path, 0700);
}
bool Valid(const base::DictValue& value) {
  const auto* id = value.FindString("id");
  const auto* name = value.FindString("name");
  const auto* model = value.FindString("template");
  const auto* language = value.FindString("languages");
  const auto* window = value.FindString("window");
  const auto* timezone = value.FindString("timezone");
  const auto* webrtc = value.FindString("webrtc");
  const auto* display = value.FindString("display");
  const auto* gpu = value.FindString("gpu");
  const auto* version_policy = value.FindString("platform_version_policy");
  const bool valid_version_policy = !value.contains("platform_version_policy") ||
      (version_policy && ValidPlatformVersionPolicy(*version_policy));
  bool valid_gpu = !value.contains("gpu");
  for (const auto* item : kGPUs)
    if (gpu && *gpu == item) valid_gpu = true;
  bool valid_display = !value.contains("display");
  for (const auto* item : kDisplays)
    if (display && *display == item) valid_display = true;
  bool valid_webrtc = !value.contains("webrtc");
  for (const auto* item : kWebRTCPolicies)
    if (webrtc && *webrtc == item) valid_webrtc = true;
  bool valid_language = false, valid_window = false;
  bool valid_timezone = !value.contains("timezone");  // Older profiles use system.
  for (const auto* item : kLanguages) if (language && *language == item) valid_language = true;
  for (const auto* item : kWindows) if (window && *window == item) valid_window = true;
  if (timezone) valid_timezone = KnownTimezone(*timezone);
  return id && ValidId(*id) && name && !name->empty() && name->size() <= 160 &&
         base::IsStringUTF8(*name) && name->find_first_of("\r\n\t") == std::string::npos &&
         model && UserSelectablePersona(*model) &&
         value.FindInt("schema") == 1 && valid_language && valid_window &&
         valid_timezone && valid_webrtc && valid_display && valid_gpu && valid_version_policy;
}
base::DictValue Load(const base::FilePath& root, const std::string& id) {
  if (!ValidId(id) || base::IsLink(root) || base::IsLink(root.AppendASCII(id)))
    return {};
  const auto file = root.AppendASCII(id).AppendASCII("identity.json");
  if (base::IsLink(file)) return {};
  std::string text;
  if (!base::ReadFileToStringWithMaxSize(file, &text, 4096)) return {};
  auto value = base::JSONReader::ReadDict(text, base::JSON_PARSE_RFC);
  if (!value || !Valid(*value) || *value->FindString("id") != id) return {};
  return std::move(*value);
}
std::vector<base::DictValue> List(const base::FilePath& root) {
  std::vector<base::DictValue> values;
  if (!root.IsAbsolute() || base::IsLink(root)) return values;
  base::FileEnumerator files(root, false, base::FileEnumerator::DIRECTORIES);
  for (auto dir = files.Next(); !dir.empty(); dir = files.Next()) {
    auto value = Load(root, dir.BaseName().value());
    if (!value.empty()) values.push_back(std::move(value));
    if (values.size() == 32) break;
  }
  return values;
}
struct Result {
  bool ok = false;
  std::string message;
  base::DictValue value;
};
Result Save(const base::FilePath& root, base::DictValue value,
            const std::string& expected_revision) {
  if (const auto* timezone = value.FindString("timezone");
      timezone && !KnownTimezone(*timezone))
    return {false, "无法识别此 IANA 时区，例如 Asia/Kolkata、Asia/Kathmandu。", {}};
  if (!Valid(value) || !SafeDirectory(root))
    return {false, "配置无效，或身份目录不可写。", {}};
  const std::string id = *value.FindString("id");
  const auto dir = root.AppendASCII(id);
  if (!SafeDirectory(dir)) return {false, "身份目录不可写。", {}};
  const auto lock_path = root.AppendASCII("catalog.lock");
  if (base::IsLink(lock_path)) return {false, "身份目录包含无效链接。", {}};
  base::File lock(lock_path, base::File::FLAG_OPEN_ALWAYS | base::File::FLAG_WRITE);
  if (!lock.IsValid() || lock.Lock(base::File::LockMode::kExclusive) != base::File::FILE_OK)
    return {false, "身份正在被其他窗口修改，请刷新后重试。", {}};
  auto current = Load(root, id);
  if (current.empty() && List(root).size() >= 32)
    return {false, "最多创建 32 套身份。", {}};
  const auto* revision = current.FindString("revision");
  if ((!expected_revision.empty() && (!revision || *revision != expected_revision)) ||
      (expected_revision.empty() && base::PathExists(dir.AppendASCII("identity.json"))))
    return {false, "配置已在其他窗口变化，请刷新后重新编辑。", {}};
  value.Set("revision", base::Uuid::GenerateRandomV4().AsLowercaseString());
  const auto bytes = base::WriteJson(value);
  const auto temporary = dir.AppendASCII("identity-" +
      base::Uuid::GenerateRandomV4().AsLowercaseString() + ".tmp");
  if (!bytes || !base::WriteFile(temporary, *bytes) ||
      !base::SetPosixFilePermissions(temporary, 0600) ||
      !base::ReplaceFile(temporary, dir.AppendASCII("identity.json"), nullptr)) {
    base::DeleteFile(temporary);
    return {false, "保存失败；现有身份未修改。", {}};
  }
  return {true, "已保存。身份配置与登录数据分开存储。", std::move(value)};
}
Result Open(const base::FilePath& root, const std::string& id) {
  const auto value = Load(root, id);
  if (value.empty()) return {false, "配置不存在或校验失败，请刷新。", {}};
  const auto dir = root.AppendASCII(id);
  for (const auto* name : {"browser", "conversations", "account", "workspace"}) {
    if (!SafeDirectory(dir.AppendASCII(name)))
      return {false, "身份的数据目录无效，未启动。", {}};
  }
  base::FilePath executable;
  if (!base::PathService::Get(base::FILE_EXE, &executable))
    return {false, "无法定位当前浏览器。", {}};
  // Build a fresh command line: never forward profile, automation, debug,
  // provider credentials, startup prompts or site URLs from the parent.
  base::CommandLine command(executable);
  command.AppendSwitchPath("user-data-dir", dir.AppendASCII("browser"));
  command.AppendSwitch("no-first-run");
  command.AppendSwitchASCII(kPersonaTemplateSwitch, *value.FindString("template"));
  const auto* version_policy = value.FindString("platform_version_policy");
  command.AppendSwitchASCII(kPlatformVersionPolicySwitch,
      version_policy ? *version_policy : "major");
  command.AppendSwitch("no-default-browser-check");
  command.AppendSwitch("hide-crash-restore-bubble");
  // Honor an explicitly disabled updater in the parent (e.g. an offline QA
  // session). Do not start large component downloads from a fresh identity.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch("disable-component-update"))
    command.AppendSwitch("disable-component-update");
  // Explicit QA isolation only; normal launches keep the standard keychain.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch("use-mock-keychain"))
    command.AppendSwitch("use-mock-keychain");
  if (const auto* gpu = value.FindString("gpu"); gpu && *gpu == "software") {
    command.AppendSwitchASCII("use-gl", "angle");
    command.AppendSwitchASCII("use-angle", "swiftshader");
    command.AppendSwitchASCII("use-webgpu-adapter", "swiftshader");
    // Keep media on software paths too; otherwise codec capability queries and
    // video encode/decode can reopen the host's hardware acceleration profile.
    command.AppendSwitch("disable-accelerated-video-decode");
    command.AppendSwitch("disable-accelerated-video-encode");
  }
  const auto* webrtc = value.FindString("webrtc");
  command.AppendSwitchASCII("metabrowser-webrtc-policy",
                           webrtc ? *webrtc : kWebRTCPolicies[0]);
  // Always supply an explicit language list. Omitting the switch after a
  // fixed-language launch can revive its persisted Accept-Language preference.
  const auto& languages = *value.FindString("languages");
  command.AppendSwitchASCII("accept-lang", languages == "system" ? SystemLanguages() : languages);
  if (*value.FindString("window") != "system")
    command.AppendSwitchASCII("window-size", *value.FindString("window"));
  command.AppendArg("about:blank");
  base::LaunchOptions options;
  // An identity receives no inherited provider/MCP/gateway/test configuration.
  // Keep OS/UI variables needed by a native macOS browser.
  for (const auto* key : {"HOME", "PATH", "TMPDIR", "USER", "LOGNAME",
                          "SHELL", "LANG", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}) {
    const auto v = Env(key);
    if (!v.empty()) options.environment[key] = v;
  }
  options.clear_environment = true;
  options.environment["METABROWSER_IDENTITY_HOME"] = root.value();
  options.environment["METABROWSER_IDENTITY_ID"] = id;
  const auto* display = value.FindString("display");
  options.environment["METABROWSER_DISPLAY_SIZE"] = display ? *display : kDisplays[0];
  if (const auto* timezone = value.FindString("timezone"); timezone && *timezone != "system")
    options.environment["TZ"] = *timezone;
  options.environment["METABROWSER_CONVERSATION_HOME"] = dir.AppendASCII("conversations").value();
  options.environment["METABROWSER_ACCOUNT_HOME"] = dir.AppendASCII("account").value();
  options.environment["METABROWSER_WORKSPACE"] = dir.AppendASCII("workspace").value();
  auto process = base::LaunchProcess(command, options);
  if (!process.IsValid())
    return {false, "浏览器启动失败，当前窗口和数据保持原样。", {}};
  // Reap both long-lived browser children and short-lived singleton forwarders.
  // Waiting never blocks UI or parent shutdown, and never terminates a child.
  base::ThreadPool::PostTask(FROM_HERE,
      {base::MayBlock(), base::WithBaseSyncPrimitives(),
       base::TaskPriority::BEST_EFFORT,
       base::TaskShutdownBehavior::CONTINUE_ON_SHUTDOWN},
      base::BindOnce([](base::Process child) {
        int exit_code = 0;
        (void)child.WaitForExit(&exit_code);
      }, std::move(process)));
  return {true, "已请求打开独立窗口。已运行的身份沿用其现有窗口。", {}};
}

class IdentityProfilesView final : public views::View {
 public:
  IdentityProfilesView() : root_(Root()) {
    SetBackground(views::CreateSolidBackground(ui::kColorDialogBackground));
    SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kVertical, gfx::Insets(), 8));
    Label(u"浏览器身份", 15, true);
    current_ = Label(u"当前：默认身份 · 现有登录和窗口保留", 11);
    Label(u"每个身份使用独立窗口与网站数据。", 11);
    auto choices = std::make_unique<ui::SimpleComboboxModel>(
        std::vector<ui::SimpleComboboxModel::Item>{
            ui::SimpleComboboxModel::Item(u"正在读取身份…")});
    picker_ = AddChildView(std::make_unique<views::Combobox>(std::move(choices)));
    picker_->GetViewAccessibility().SetName(u"浏览器身份列表");
    picker_->SetCallback(base::BindRepeating(&IdentityProfilesView::Selected,
                                             base::Unretained(this)));
    name_ = AddChildView(std::make_unique<views::Textfield>());
    name_->SetPlaceholderText(u"身份名称，例如：工作、研究");
    name_->GetViewAccessibility().SetName(u"浏览器身份名称");
    Label(u"网页语言", 11, true);
    languages_ = Choices({u"跟随系统", u"简体中文 · zh-CN", u"English · en-US", u"日本語 · ja-JP"}, u"身份网页语言");
    Label(u"系统版本隐私", 11, true);
    platform_version_ = Choices({u"仅公开主版本", u"公开系统完整版本"}, u"身份系统版本策略");
    Label(u"同时作用于网页和请求头；系统平台与架构保持当前模板。", 11);
    Label(u"时区", 11, true);
    timezone_ = Choices({u"跟随系统时区", u"UTC", u"中国 · Asia/Shanghai", u"日本 · Asia/Tokyo", u"英国 · Europe/London", u"美国东部 · America/New_York", u"美国西部 · America/Los_Angeles", u"自定义 IANA 时区"}, u"身份时区");
    custom_timezone_ = AddChildView(std::make_unique<views::Textfield>());
    custom_timezone_->SetPlaceholderText(u"例如 Asia/Kolkata、Asia/Kathmandu");
    custom_timezone_->GetViewAccessibility().SetName(u"自定义 IANA 时区名称");
    custom_timezone_->SetVisible(false);
    timezone_->SetCallback(base::BindRepeating(&IdentityProfilesView::TimezoneChanged,
                                              base::Unretained(this)));
    Label(u"按所选时区处理日期与夏令时，不修改 Mac 的系统时区。", 11);
    Label(u"初始窗口尺寸", 11, true);
    window_ = Choices({u"浏览器默认", u"1280 × 900", u"1440 × 1000"}, u"身份窗口尺寸");
    Label(u"WebRTC 网络隐私", 11, true);
    webrtc_ = Choices({u"仅公共接口", u"严格代理 · 禁止 UDP 直连", u"兼容 · 沿用浏览器策略"}, u"身份 WebRTC 网络策略");
    Label(u"严格代理模式可能需要 TURN 中继才能通话；不会伪造连接成功。", 11);
    Label(u"网页可见显示区域", 11, true);
    display_ = Choices({u"1440 × 900", u"1680 × 1050", u"1920 × 1200", u"2560 × 1600", u"真实显示器 · 兼容"}, u"身份显示区域");
    Label(u"窗口超出时自动扩大；真实显示器详情需单独授权。", 11);
    Label(u"GPU 后端", 11, true);
    gpu_ = Choices({u"原生 GPU · 性能优先", u"软件 GPU · 隔离硬件型号"}, u"身份 GPU 后端");
    Label(u"软件后端使用 SwiftShader 运行图形与计算，性能较低；网页仍可识别软件渲染。", 11);
    auto* actions = AddChildView(std::make_unique<views::View>());
    actions->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kHorizontal, gfx::Insets(), 4));
    AddButton(actions, u"新建身份", &IdentityProfilesView::Create);
    AddButton(actions, u"保存配置", &IdentityProfilesView::Rename);
    AddButton(actions, u"打开身份", &IdentityProfilesView::Launch);
    auto* secondary = AddChildView(std::make_unique<views::View>());
    secondary->SetLayoutManager(std::make_unique<views::BoxLayout>(
        views::BoxLayout::Orientation::kHorizontal, gfx::Insets(), 4));
    AddButton(secondary, u"复制配置", &IdentityProfilesView::Duplicate);
    AddButton(secondary, u"刷新身份", &IdentityProfilesView::Refresh);
    AddButton(secondary, u"检查配置", &IdentityProfilesView::Check);
    Label(u"身份模板 · 原生 macOS / ARM64", 12, true);
    Label(u"支持原生或软件 GPU。跨平台及指定显卡型号的精确模拟尚未开放。", 11);
    Label(u"配置更改在该身份完全关闭后的下一次启动生效，不热改已打开网页。", 11);
    Label(u"独立 Cookie、权限、存储与指纹密钥。复制仅生成新配置，不复制登录记录或密钥。", 11);
    status_ = Label(u"一致性：原生模板；尚未代表目标网站验收通过。", 11);
    Refresh();
  }
 private:
  views::Label* Label(std::u16string text, int size, bool bold = false) {
    auto* label = AddChildView(std::make_unique<views::Label>(text));
    label->SetFontList(design::Font(size, bold));
    label->SetEnabledColor(bold ? ui::kColorLabelForeground
                               : ui::kColorLabelForegroundSecondary);
    label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
    label->SetMultiLine(true);
    return label;
  }
  void AddButton(views::View* parent, const std::u16string& text,
                 void (IdentityProfilesView::*method)()) {
    auto* button = parent->AddChildView(std::make_unique<views::MdTextButton>(
        base::BindRepeating(method, weak_.GetWeakPtr()), text));
    design::QuietButton(button);
    button->SetEnabledTextColors(ui::kColorButtonForeground);
  }
  views::Combobox* Choices(std::vector<std::u16string> labels, std::u16string name) {
    std::vector<ui::SimpleComboboxModel::Item> items;
    for (const auto& label : labels) items.emplace_back(label);
    auto* box = AddChildView(std::make_unique<views::Combobox>(
        std::make_unique<ui::SimpleComboboxModel>(std::move(items))));
    box->SetSelectedIndex(0);
    box->GetViewAccessibility().SetName(name);
    return box;
  }
  const base::DictValue* Selection() const {
    const auto index = picker_->GetSelectedIndex();
    return index && *index < entries_.size() ? &entries_[*index] : nullptr;
  }
  void TimezoneChanged() {
    custom_timezone_->SetVisible(timezone_->GetSelectedIndex().value_or(0) == kTimezones.size());
    InvalidateLayout();
  }
  std::string TimezoneValue() const {
    const auto index = timezone_->GetSelectedIndex().value_or(0);
    if (index < kTimezones.size()) return kTimezones[index];
    std::string value = base::UTF16ToUTF8(custom_timezone_->GetText());
    base::TrimWhitespaceASCII(value, base::TRIM_ALL, &value);
    return value;
  }
  void Selected() {
    const auto* selected = Selection();
    name_->SetText(selected ? base::UTF8ToUTF16(*selected->FindString("name")) : u"");
    size_t language = 0, window = 0, timezone = 0, webrtc = 0, display = 0, gpu = 0, platform_version = 0;
    custom_timezone_->SetText(u"");
    if (selected) {
      for (size_t i = 0; i < std::size(kLanguages); ++i)
        if (*selected->FindString("languages") == kLanguages[i]) language = i;
      for (size_t i = 0; i < std::size(kWindows); ++i)
        if (*selected->FindString("window") == kWindows[i]) window = i;
      if (const auto* zone = selected->FindString("timezone")) {
        timezone = kTimezones.size();
        for (size_t i = 0; i < std::size(kTimezones); ++i)
          if (*zone == kTimezones[i]) timezone = i;
        if (timezone == kTimezones.size())
          custom_timezone_->SetText(base::UTF8ToUTF16(*zone));
      }
      if (const auto* policy = selected->FindString("webrtc"))
        for (size_t i = 0; i < std::size(kWebRTCPolicies); ++i)
          if (*policy == kWebRTCPolicies[i]) webrtc = i;
      if (const auto* screen = selected->FindString("display"))
        for (size_t i = 0; i < std::size(kDisplays); ++i)
          if (*screen == kDisplays[i]) display = i;
      if (const auto* policy = selected->FindString("platform_version_policy"))
        for (size_t i = 0; i < std::size(kPlatformVersionPolicies); ++i)
          if (*policy == kPlatformVersionPolicies[i]) platform_version = i;
      if (const auto* backend = selected->FindString("gpu"))
        for (size_t i = 0; i < std::size(kGPUs); ++i)
          if (*backend == kGPUs[i]) gpu = i;
    }
    languages_->SetSelectedIndex(language);
    window_->SetSelectedIndex(window);
    timezone_->SetSelectedIndex(timezone);
    TimezoneChanged();
    webrtc_->SetSelectedIndex(webrtc);
    display_->SetSelectedIndex(display);
    gpu_->SetSelectedIndex(gpu);
    platform_version_->SetSelectedIndex(platform_version);
  }
  void Refresh() {
    SetEnabled(false);
    base::ThreadPool::PostTaskAndReplyWithResult(FROM_HERE, {base::MayBlock()},
        base::BindOnce(&List, root_),
        base::BindOnce(&IdentityProfilesView::Listed, weak_.GetWeakPtr()));
  }
  void Listed(std::vector<base::DictValue> entries) {
    entries_ = std::move(entries);
    std::vector<ui::SimpleComboboxModel::Item> choices;
    size_t selected = 0;
    const auto current = Env("METABROWSER_IDENTITY_ID");
    for (size_t i = 0; i < entries_.size(); ++i) {
      const auto& value = entries_[i];
      const bool active = *value.FindString("id") == current;
      choices.emplace_back(base::UTF8ToUTF16(*value.FindString("name")) +
                           (active ? u" · 当前身份" : u""));
      if (active) {
        current_->SetText(u"当前：" + base::UTF8ToUTF16(*value.FindString("name")));
        if (preferred_.empty()) selected = i;
      }
      if (*value.FindString("id") == preferred_) selected = i;
    }
    if (choices.empty()) choices.emplace_back(u"尚未创建独立身份");
    picker_->SetSelectedIndex(std::nullopt);
    picker_->SetOwnedModel(std::make_unique<ui::SimpleComboboxModel>(std::move(choices)));
    picker_->SetSelectedIndex(selected);
    Selected();
    SetEnabled(true);
  }
  void Persist(base::DictValue value, std::string revision) {
    SetEnabled(false);
    status_->SetText(u"正在保存…");
    base::ThreadPool::PostTaskAndReplyWithResult(FROM_HERE, {base::MayBlock()},
        base::BindOnce(&Save, root_, std::move(value), std::move(revision)),
        base::BindOnce([](base::WeakPtr<IdentityProfilesView> self, Result result) {
          if (!self) return;
          self->SetEnabled(true);
          self->status_->SetText(base::UTF8ToUTF16(result.message));
          if (result.ok) { self->preferred_ = *result.value.FindString("id"); self->Refresh(); }
        }, weak_.GetWeakPtr()));
  }
  void Create() {
    if (entries_.size() >= 32) { status_->SetText(u"最多创建 32 套身份。"); return; }
    auto name = base::UTF16ToUTF8(name_->GetText());
    base::TrimWhitespaceASCII(name, base::TRIM_ALL, &name);
    if (name.empty()) name = "独立身份 " + std::to_string(entries_.size() + 1);
    base::DictValue value;
    value.Set("schema", 1);
    value.Set("id", base::Uuid::GenerateRandomV4().AsLowercaseString());
    value.Set("name", name);
    value.Set("template", "native-macos-arm64-v1");
    value.Set("languages", kLanguages[languages_->GetSelectedIndex().value_or(0)]);
    value.Set("window", kWindows[window_->GetSelectedIndex().value_or(0)]);
    value.Set("timezone", TimezoneValue());
    value.Set("webrtc", kWebRTCPolicies[webrtc_->GetSelectedIndex().value_or(0)]);
    value.Set("display", kDisplays[display_->GetSelectedIndex().value_or(0)]);
    value.Set("gpu", kGPUs[gpu_->GetSelectedIndex().value_or(0)]);
    value.Set("platform_version_policy", kPlatformVersionPolicies[platform_version_->GetSelectedIndex().value_or(0)]);
    Persist(std::move(value), "");
  }
  void Rename() {
    const auto* selected = Selection();
    if (!selected) { status_->SetText(u"请先创建或选择身份。"); return; }
    auto value = selected->Clone();
    auto name = base::UTF16ToUTF8(name_->GetText());
    base::TrimWhitespaceASCII(name, base::TRIM_ALL, &name);
    value.Set("name", name);
    value.Set("languages", kLanguages[languages_->GetSelectedIndex().value_or(0)]);
    value.Set("window", kWindows[window_->GetSelectedIndex().value_or(0)]);
    value.Set("timezone", TimezoneValue());
    value.Set("webrtc", kWebRTCPolicies[webrtc_->GetSelectedIndex().value_or(0)]);
    value.Set("display", kDisplays[display_->GetSelectedIndex().value_or(0)]);
    value.Set("gpu", kGPUs[gpu_->GetSelectedIndex().value_or(0)]);
    value.Set("platform_version_policy", kPlatformVersionPolicies[platform_version_->GetSelectedIndex().value_or(0)]);
    const auto* revision = selected->FindString("revision");
    Persist(std::move(value), revision ? *revision : "");
  }
  void Duplicate() {
    const auto* selected = Selection();
    if (!selected) { status_->SetText(u"请先选择要复制的身份。"); return; }
    name_->SetText(base::UTF8ToUTF16(*selected->FindString("name")) + u" · 副本");
    Create();
  }
  void Launch() {
    const auto* selected = Selection();
    if (!selected) { status_->SetText(u"请先创建或选择身份。"); return; }
    status_->SetText(u"正在打开独立身份…");
    base::ThreadPool::PostTaskAndReplyWithResult(FROM_HERE, {base::MayBlock()},
        base::BindOnce(&Open, root_, *selected->FindString("id")),
        base::BindOnce([](base::WeakPtr<IdentityProfilesView> self, Result result) {
          if (self) self->status_->SetText(base::UTF8ToUTF16(result.message));
        }, weak_.GetWeakPtr()));
  }
  void Check() {
    const auto* selected = Selection();
    if (!selected || !Valid(*selected)) { status_->SetText(u"请先保存有效配置。"); return; }
    status_->SetText(u"配置检查通过：原生平台；网页语言使用浏览器偏好；窗口尺寸不改显示器；独立数据目录。尚未完成该身份的网站验收，IP 与主动登录账号仍可关联。");
  }
  const base::FilePath root_;
  std::string preferred_;
  std::vector<base::DictValue> entries_;
  raw_ptr<views::Label> current_;
  raw_ptr<views::Label> status_;
  raw_ptr<views::Textfield> name_;
  raw_ptr<views::Combobox> picker_;
  raw_ptr<views::Combobox> languages_;
  raw_ptr<views::Combobox> window_;
  raw_ptr<views::Combobox> timezone_;
  raw_ptr<views::Textfield> custom_timezone_;
  raw_ptr<views::Combobox> webrtc_;
  raw_ptr<views::Combobox> display_;
  raw_ptr<views::Combobox> gpu_;
  raw_ptr<views::Combobox> platform_version_;
  base::WeakPtrFactory<IdentityProfilesView> weak_{this};
};
}  // namespace
std::unique_ptr<views::View> CreateIdentityProfilesView() {
  return std::make_unique<IdentityProfilesView>();
}
void ShowIdentityProfilesSettings(const std::u16string& account_summary) {
  // Client owns both objects. Destroy the old Widget before its Delegate when
  // recreating a closed window; no deprecated self-owning DialogDelegateView.
  static base::NoDestructor<std::unique_ptr<views::DialogDelegate>> delegate;
  static base::NoDestructor<std::unique_ptr<views::Widget>> window;
  if (*window && !(*window)->IsClosed()) {
    (*window)->Show(); (*window)->Activate(); return;
  }
  window->reset();
  delegate->reset();
  auto dialog = std::make_unique<views::DialogDelegate>();
  dialog->SetOwnershipOfNewWidget(views::Widget::InitParams::CLIENT_OWNS_WIDGET);
  dialog->SetTitle(u"Metask 账户设置");
  dialog->SetButtons(0);
  dialog->SetCanResize(true);
  auto* content = dialog->SetContentsView(std::make_unique<views::View>());
  content->SetBackground(views::CreateSolidBackground(ui::kColorDialogBackground));
  content->SetPreferredSize(gfx::Size(580, 720));
  content->SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kVertical, gfx::Insets(24), 16));
  auto* summary = content->AddChildView(std::make_unique<views::Label>(account_summary));
  summary->SetFontList(design::Font(12));
  summary->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  summary->SetMultiLine(true);
  auto* scroll = content->AddChildView(std::make_unique<views::ScrollView>());
  scroll->SetBackgroundColor(ui::kColorDialogBackground);
  scroll->SetBorder(views::CreateEmptyBorder(0));
  scroll->SetContents(CreateIdentityProfilesView());
  static_cast<views::BoxLayout*>(content->GetLayoutManager())->SetFlexForView(scroll, 1);
  auto* widget = views::DialogDelegate::CreateDialogWidget(
      dialog.get(), gfx::NativeWindow(), gfx::NativeView());
  *delegate = std::move(dialog);
  window->reset(widget);
  widget->Show();
}
}  // namespace metabrowser
