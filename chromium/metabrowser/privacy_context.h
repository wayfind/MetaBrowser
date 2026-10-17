#ifndef METABROWSER_PRIVACY_CONTEXT_H_
#define METABROWSER_PRIVACY_CONTEXT_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

#include "base/base64.h"
#include "base/check.h"
#include "base/command_line.h"
#include "base/containers/span.h"
#include "base/files/file_path.h"
#include "base/logging.h"
#include "base/rand_util.h"
#include "base/supports_user_data.h"
#include "chrome/browser/profiles/profile.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/storage_partition_config.h"
#include "crypto/hmac.h"
#include "third_party/blink/public/common/storage_key/storage_key.h"

namespace metabrowser {

inline constexpr char kPrivacyRootSecretPref[] = "metabrowser.privacy.root_secret";
inline constexpr char kPrivacyEnabledPref[] = "metabrowser.privacy.enabled";
inline constexpr char kPrivacyCompatibilitySitesPref[] =
    "metabrowser.privacy.compatibility_sites";

inline void RegisterPrivacyContextPrefs(user_prefs::PrefRegistrySyncable* registry) {
  // No SYNCABLE_PREF flags: neither the identity nor compatibility choices sync.
  registry->RegisterStringPref(kPrivacyRootSecretPref, std::string());
  registry->RegisterBooleanPref(kPrivacyEnabledPref, true);
  registry->RegisterListPref(kPrivacyCompatibilitySitesPref);
}

// Absence is a new identity. An explicitly stored malformed/empty value is
// corruption, including a wrong JSON type that PrefService otherwise ignores.
// Validate before profile initialization, without creating or rewriting a key.
inline bool HasInvalidPrivacyRoot(const PrefService* prefs) {
  const auto status = prefs->GetInitializationStatus();
  // A failed read has no trustworthy user values. It must not be confused with
  // a genuinely new profile and silently mint a replacement identity.
  if (status != PrefService::INITIALIZATION_STATUS_SUCCESS &&
      status != PrefService::INITIALIZATION_STATUS_CREATED_NEW_PREF_STORE) {
    return true;
  }
  const auto* pref = prefs->FindPreference(kPrivacyRootSecretPref);
  if (!pref || !pref->HasUserSetting()) return false;
  std::string decoded;
  return !base::Base64Decode(prefs->GetString(kPrivacyRootSecretPref), &decoded) ||
         decoded.size() != 32;
}

namespace privacy_context_internal {
inline constexpr char kStateKey[] = "metabrowser.privacy.context.v1";

// BrowserContext owns this state. OTR never reads or writes the normal-profile
// root, even though its PrefService can fall through to original-profile prefs.
class State final : public base::SupportsUserData::Data {
 public:
  explicit State(Profile* profile) {
    if (!profile->IsOffTheRecord()) {
      if (HasInvalidPrivacyRoot(profile->GetPrefs())) {
        LOG(ERROR) << "MetaBrowser privacy identity invalid; profile must be restored";
        return;
      }
      const auto& encoded = profile->GetPrefs()->GetString(kPrivacyRootSecretPref);
      if (!encoded.empty()) {
        if (!base::Base64Decode(encoded, &root_) || root_.size() != 32) {
          root_.clear();
          LOG(ERROR) << "MetaBrowser privacy root is invalid; tokens disabled without rotating identity";
          return;
        }
        valid_ = true;
        return;
      }
    }
    const auto random = base::RandBytesAsVector(32);
    root_.assign(random.begin(), random.end());
    if (!profile->IsOffTheRecord()) {
      profile->GetPrefs()->SetString(kPrivacyRootSecretPref,
                                     base::Base64Encode(random));
    }
    valid_ = true;
  }
  bool valid() const { return valid_; }
  const std::string& root() const { return root_; }

 private:
  std::string root_;
  bool valid_ = false;
};

inline void AppendField(std::string& bytes, std::string_view value) {
  // Length framing prevents ambiguous concatenations of origins/partitions.
  bytes += std::to_string(value.size());
  bytes += ':';
  bytes.append(value);
}
}  // namespace privacy_context_internal

// UI-sequence only. The master key and unsalted profile identity NEVER cross
// Mojo, enter command-line switches, or reach a renderer. Only this context's
// 64-bit derived token is sent. Zero is a valid engaged token, not "disabled".
inline std::optional<uint64_t> GetPrivacyContextToken(
    Profile* profile, const blink::StorageKey& input_key,
    const content::StoragePartitionConfig& partition,
    std::optional<url::Origin> trusted_top_origin = std::nullopt) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  // Finder/native launches have no switch: the enabled profile pref controls
  // balanced mode. Explicit off provides the unmodified baseline for testing.
  const auto* command_line = base::CommandLine::ForCurrentProcess();
  if (!profile) {
    return std::nullopt;
  }
  const bool has_mode = command_line->HasSwitch("metabrowser-privacy");
  const auto mode = command_line->GetSwitchValueNative("metabrowser-privacy");
  if (has_mode && mode == FILE_PATH_LITERAL("off")) {
    return std::nullopt;
  }
  if (has_mode && mode != FILE_PATH_LITERAL("balanced")) {
    // Report once, without echoing arbitrary arguments or any derived identity.
    static const bool reported = [] {
      LOG(WARNING) << "Unsupported --metabrowser-privacy mode: using balanced protection";
      return true;
    }();
    (void)reported;
  }
  if (!profile->GetPrefs()->GetBoolean(kPrivacyEnabledPref)) {
    return std::nullopt;
  }
  // Preserve the real top-level site even with upstream 3P partitioning off.
  const auto key = input_key.CopyWithForceEnabledThirdPartyStoragePartitioning();
  const auto site = trusted_top_origin ? net::SchemefulSite(*trusted_top_origin)
                                      : key.top_level_site();
  const bool ephemeral = key.origin().opaque() || key.nonce().has_value();
  if (site.opaque() || (ephemeral && !trusted_top_origin) ||
      (!ephemeral && !key.origin().GetURL().SchemeIsHTTPOrHTTPS()) ||
      !site.GetURL().SchemeIsHTTPOrHTTPS()) {
    return std::nullopt;
  }
  const std::string site_string = site.Serialize();
  // Exact canonical schemeful sites; no wildcards, permission changes, or URL
  // pattern reinterpretation. Changes take effect on the next context creation.
  for (const auto& entry : profile->GetPrefs()->GetList(
           kPrivacyCompatibilitySitesPref)) {
    if (entry.is_string() && entry.GetString() == site_string) {
      return std::nullopt;
    }
  }
  using namespace privacy_context_internal;
  auto* state = static_cast<State*>(profile->GetUserData(kStateKey));
  if (!state) {
    auto owned = std::make_unique<State>(profile);
    state = owned.get();
    profile->SetUserData(kStateKey, std::move(owned));
  }
  // Normal profiles reject this at load with a native error dialog. This is a
  // last guard for callers bypassing profile initialization (or later mutation),
  // never permission to run a protected context without its identity.
  CHECK(state->valid()) << "MetaBrowser privacy identity invalid; refusing unprotected fallback";
  // Opaque/credentialless/fenced scopes under a browser-verified protected top
  // site must not become raw-readback escapes. Their identity is ephemeral per
  // newly committed context, never the parent's persistent origin token.
  if (ephemeral) {
    return base::RandUint64();
  }
  std::string input;
  AppendField(input, "metabrowser/privacy-context/v1/balanced");
  AppendField(input, site_string);
  AppendField(input, key.origin().Serialize());
  AppendField(input, partition.partition_domain());
  AppendField(input, partition.partition_name());
  AppendField(input, partition.in_memory() ? "memory" : "disk");
  const auto digest = crypto::hmac::SignSha256(
      base::as_byte_span(state->root()), base::as_byte_span(input));
  uint64_t token = 0;
  for (size_t i = 0; i < 8; ++i) {
    token = (token << 8) | digest[i];
  }
  return token;
}
}  // namespace metabrowser

#endif  // METABROWSER_PRIVACY_CONTEXT_H_
