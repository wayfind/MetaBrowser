#include "metabrowser/privacy_context.h"

#include "base/test/scoped_command_line.h"
#include "base/unguessable_token.h"
#include "chrome/test/base/testing_profile.h"
#include "content/public/test/browser_task_environment.h"
#include "net/base/schemeful_site.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace metabrowser {
namespace {
class MetaBrowserPrivacyContextTest : public testing::Test {
 protected:
  void SetUp() override {
    command_line_.GetProcessCommandLine()->RemoveSwitch("metabrowser-privacy");
  }
  blink::StorageKey Key(const char* origin = "https://frame.example.net",
                        const char* top = "https://example.com") {
    return blink::StorageKey::Create(
        url::Origin::Create(GURL(origin)), net::SchemefulSite(GURL(top)),
        blink::mojom::AncestorChainBit::kCrossSite);
  }
  content::StoragePartitionConfig Partition(const char* name = "tenant",
                                            bool memory = false) {
    return content::StoragePartitionConfig::Create(&profile_, "app", name, memory);
  }
  content::BrowserTaskEnvironment task_environment_;
  base::test::ScopedCommandLine command_line_;
  TestingProfile profile_;
};

TEST_F(MetaBrowserPrivacyContextTest, DefaultBalancedKnownHmacAndScopeSeparation) {
  profile_.GetPrefs()->SetString(kPrivacyRootSecretPref,
                                 base::Base64Encode(std::string(32, 'r')));
  const auto token = GetPrivacyContextToken(&profile_, Key(), Partition());
  ASSERT_TRUE(token);
  // Independent HMAC-SHA256 vector for the documented length-framed v1 fields.
  EXPECT_EQ(UINT64_C(0x54941a4615cb6c04), *token);
  EXPECT_EQ(token, GetPrivacyContextToken(&profile_, Key(), Partition()));
  EXPECT_NE(token, GetPrivacyContextToken(&profile_, Key("https://other.example.net"), Partition()));
  EXPECT_NE(token, GetPrivacyContextToken(&profile_, Key("https://frame.example.net", "http://example.com"), Partition()));
  EXPECT_NE(token, GetPrivacyContextToken(&profile_, Key(), Partition("other")));
  EXPECT_NE(token, GetPrivacyContextToken(&profile_, Key(), Partition("tenant", true)));
}

TEST_F(MetaBrowserPrivacyContextTest, OnlyExplicitOffDisablesProtection) {
  auto* command_line = command_line_.GetProcessCommandLine();
  command_line->AppendSwitchASCII("metabrowser-privacy", "off");
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, Key(), Partition()));
  EXPECT_TRUE(profile_.GetPrefs()->GetString(kPrivacyRootSecretPref).empty());
  command_line->RemoveSwitch("metabrowser-privacy");
  const auto token = GetPrivacyContextToken(&profile_, Key(), Partition());
  ASSERT_TRUE(token);
  const auto root = profile_.GetPrefs()->GetString(kPrivacyRootSecretPref);
  for (const char* mode : {"unknown", ""}) {
    command_line->AppendSwitchASCII("metabrowser-privacy", mode);
    EXPECT_EQ(token, GetPrivacyContextToken(&profile_, Key(), Partition()));
    EXPECT_EQ(root, profile_.GetPrefs()->GetString(kPrivacyRootSecretPref));
  }
  command_line->RemoveSwitch("metabrowser-privacy");
}

TEST_F(MetaBrowserPrivacyContextTest, UnsupportedScopesCreateNoSecret) {
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, blink::StorageKey(), Partition()));
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, Key("file:///tmp/test"), Partition()));
  EXPECT_FALSE(GetPrivacyContextToken(
      &profile_, blink::StorageKey::CreateWithNonce(
                     url::Origin::Create(GURL("https://example.com")),
                     base::UnguessableToken::Create()), Partition()));
  EXPECT_TRUE(profile_.GetPrefs()->GetString(kPrivacyRootSecretPref).empty());
}

TEST_F(MetaBrowserPrivacyContextTest, RootPrefReloadAndOtrIsolation) {
  const auto token = GetPrivacyContextToken(&profile_, Key(), Partition());
  ASSERT_TRUE(token);
  const auto persisted = profile_.GetPrefs()->GetString(kPrivacyRootSecretPref);
  ASSERT_FALSE(persisted.empty());
  TestingProfile reloaded;
  reloaded.GetPrefs()->SetString(kPrivacyRootSecretPref, persisted);
  EXPECT_EQ(token, GetPrivacyContextToken(&reloaded, Key(), Partition()));
  TestingProfile independent;
  EXPECT_NE(token, GetPrivacyContextToken(&independent, Key(), Partition()));
  TestingProfile::Builder builder;
  auto* otr = builder.BuildIncognito(&profile_);
  ASSERT_TRUE(otr->IsOffTheRecord());
  const auto inherited_pref = otr->GetPrefs()->GetString(kPrivacyRootSecretPref);
  // Deliberately use the SAME partition descriptor: this isolates the OTR root
  // difference from the partition's separate in_memory bit.
  const auto private_token = GetPrivacyContextToken(otr, Key(), Partition());
  ASSERT_TRUE(private_token);
  EXPECT_NE(token, private_token);
  EXPECT_EQ(private_token, GetPrivacyContextToken(otr, Key(), Partition()));
  EXPECT_EQ(inherited_pref, otr->GetPrefs()->GetString(kPrivacyRootSecretPref));
  EXPECT_EQ(persisted, profile_.GetPrefs()->GetString(kPrivacyRootSecretPref));
}

TEST_F(MetaBrowserPrivacyContextTest, SettingsExceptionsAndForcedBalancedRespectPref) {
  const auto token = GetPrivacyContextToken(&profile_, Key(), Partition());
  ASSERT_TRUE(token);
  command_line_.GetProcessCommandLine()->AppendSwitchASCII("metabrowser-privacy", "balanced");
  profile_.GetPrefs()->SetBoolean(kPrivacyEnabledPref, false);
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, Key(), Partition()));
  profile_.GetPrefs()->SetBoolean(kPrivacyEnabledPref, true);
  base::ListValue exceptions;
  exceptions.Append("https://example.com");
  profile_.GetPrefs()->SetList(kPrivacyCompatibilitySitesPref, std::move(exceptions));
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, Key(), Partition()));
  EXPECT_TRUE(GetPrivacyContextToken(&profile_, Key("https://frame.example.net", "https://other.test"), Partition()));
  profile_.GetPrefs()->SetList(kPrivacyCompatibilitySitesPref, base::ListValue());
  EXPECT_EQ(token, GetPrivacyContextToken(&profile_, Key(), Partition()));
}

TEST_F(MetaBrowserPrivacyContextTest, InvalidPersistedRootNeverRotatesAndOtrIgnoresIt) {
  const std::string corrupt = "not-a-valid-base64-root";
  profile_.GetPrefs()->SetString(kPrivacyRootSecretPref, corrupt);
  EXPECT_TRUE(HasInvalidPrivacyRoot(profile_.GetPrefs()));
  EXPECT_DEATH_IF_SUPPORTED(
      GetPrivacyContextToken(&profile_, Key(), Partition()),
      "refusing unprotected fallback");
  EXPECT_EQ(corrupt, profile_.GetPrefs()->GetString(kPrivacyRootSecretPref));
  TestingProfile short_root;
  const auto short_value = base::Base64Encode("short");
  short_root.GetPrefs()->SetString(kPrivacyRootSecretPref, short_value);
  EXPECT_TRUE(HasInvalidPrivacyRoot(short_root.GetPrefs()));
  EXPECT_DEATH_IF_SUPPORTED(
      GetPrivacyContextToken(&short_root, Key(), Partition()),
      "refusing unprotected fallback");
  EXPECT_EQ(short_value, short_root.GetPrefs()->GetString(kPrivacyRootSecretPref));
  TestingProfile::Builder builder;
  auto* otr = builder.BuildIncognito(&profile_);
  EXPECT_TRUE(GetPrivacyContextToken(otr, Key(), Partition()));
  EXPECT_EQ(corrupt, profile_.GetPrefs()->GetString(kPrivacyRootSecretPref));
}

TEST_F(MetaBrowserPrivacyContextTest, OpaqueAndNonceContextsMintIndependentEphemeralTokens) {
  const auto top = url::Origin::Create(GURL("https://example.com"));
  const auto parent = GetPrivacyContextToken(&profile_, Key(), Partition(), top);
  const auto opaque_one = GetPrivacyContextToken(&profile_, blink::StorageKey(), Partition(), top);
  const auto opaque_two = GetPrivacyContextToken(&profile_, blink::StorageKey(), Partition(), top);
  ASSERT_TRUE(parent);
  ASSERT_TRUE(opaque_one);
  ASSERT_TRUE(opaque_two);
  EXPECT_NE(parent, opaque_one);
  EXPECT_NE(opaque_one, opaque_two);
  EXPECT_TRUE(GetPrivacyContextToken(
      &profile_, blink::StorageKey::CreateWithNonce(top, base::UnguessableToken::Create()),
      Partition(), top));
  profile_.GetPrefs()->SetBoolean(kPrivacyEnabledPref, false);
  EXPECT_FALSE(GetPrivacyContextToken(&profile_, blink::StorageKey(), Partition(), top));
}
}  // namespace
}  // namespace metabrowser
