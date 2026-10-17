#!/usr/bin/env python3
"""Stage service-specific native background network policy; no host blocking."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('privacy_context_stage', Path(__file__).with_name('stage-privacy-context.py'))
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


def make_plan(source, project):
    if (source/'chrome/VERSION').read_text().splitlines() != context.VERSION:
        raise ValueError('expected pinned Chromium 154.0.8037.97')
    p = context.Plan(source)
    p.helper(project, 'background_service_policy.h')
    target = '''source_set("background_service_policy") {
  public = [ "background_service_policy.h" ]
  public_deps = [ "//base" ]
}'''
    path = 'metabrowser/BUILD.gn'
    text = p.read(path)
    if target not in text:
        if 'source_set("background_service_policy")' in text:
            raise ValueError('background policy GN target drift')
        p.result[path] = text+'\n'+target+'\n'
    targets = [
        ('chrome/browser/BUILD.gn', 'source_set("core") {'),
        ('chrome/browser/component_updater/BUILD.gn', 'source_set("impl") {'),
        ('components/omnibox/browser/BUILD.gn', 'static_library("browser") {'),
        ('components/network_time/BUILD.gn', 'static_library("network_time") {'),
        ('components/gcm_driver/BUILD.gn', 'static_library("gcm_driver") {'),
        ('components/signin/internal/identity_manager/BUILD.gn', 'source_set("identity_manager") {'),
        ('components/optimization_guide/core/BUILD.gn', 'component("features") {'),
        ('chrome/browser/navigation_predictor/BUILD.gn', 'source_set("impl") {'),
        ('chrome/browser/signin/BUILD.gn', 'source_set("impl") {'),
    ]
    for path, signature in targets:
        p.gn_list(path, signature, 'deps', '//metabrowser:background_service_policy')

    def guard(path, anchor, body, tag):
        # All files use their own primary header as an exact, reviewed anchor.
        primary = '#include "'+path.removesuffix('.cc')+'.h"'
        p.include(path, '#include "metabrowser/background_service_policy.h"', primary, 'network-policy-'+tag+'-include')
        p.replace(path, anchor, anchor+'\n'+body, 'network-policy-'+tag)

    guard('components/omnibox/browser/aim_eligibility_service.cc',
          'void AimEligibilityService::StartServerEligibilityRequest(\n    RequestSource request_source,\n    const std::string& locale) {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return;', 'aim-fetch')
    guard('components/omnibox/browser/aim_eligibility_service.cc',
          'bool AimEligibilityService::IsAimLocallyEligible() const {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return false;', 'aim-local')
    guard('chrome/browser/chrome_content_browser_client.cc',
          'GURL ChromeContentBrowserClient::GetPrewarmUrl() {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return GURL();', 'search-prewarm')
    guard('components/network_time/network_time_tracker.cc',
          'bool NetworkTimeTracker::AreTimeFetchesEnabled() const {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return false;', 'network-time')
    guard('components/signin/internal/identity_manager/gaia_cookie_manager_service.cc',
          'void GaiaCookieManagerService::TriggerListAccounts() {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) {
    // Browser account enumeration is not website sign-in. Do not read or
    // mutate the site's cookies; complete the browser-side observer contract.
    accounts_.clear();
    list_accounts_stale_ = false;
    if (gaia_accounts_updated_in_cookie_callback_) {
      gaia_accounts_updated_in_cookie_callback_.Run(
          CreateAccountsInCookieJarInfo(), GoogleServiceAuthError::AuthErrorNone());
    }
    return;
  }''', 'browser-account-list')
    guard('components/optimization_guide/core/optimization_guide_features.cc',
          'bool IsOnDeviceExecutionEnabled() {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return false;', 'google-model-execution')
    guard('components/optimization_guide/core/optimization_guide_features.cc',
          'bool IsModelQualityLoggingEnabled() {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return false;', 'google-model-logging')
    guard('chrome/browser/component_updater/optimization_guide_on_device_model_installer.cc',
          '  void MaybeRegisterManifestComponent() {',
          '    if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return;', 'google-model-manifest')
    guard('components/gcm_driver/gcm_driver_desktop.cc',
          'GCMClient::Result GCMDriverDesktop::EnsureStarted(\n    GCMClient::StartMode start_mode) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices() &&
      !app_handlers().contains("wp:")) {
    return GCMClient::GCM_DISABLED;
  }''', 'gcm-start')
    guard('components/gcm_driver/gcm_driver_desktop.cc',
          'void GCMDriverDesktop::GetToken(const std::string& app_id,\n                                const std::string& authorized_entity,\n                                const std::string& scope,\n                                base::TimeDelta time_to_live,\n                                GetTokenCallback callback) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices() &&
      !metabrowser::IsWebsitePushApp(app_id)) {
    std::move(callback).Run(std::string(), GCMClient::GCM_DISABLED);
    return;
  }''', 'gcm-token')
    guard('components/gcm_driver/gcm_driver.cc',
          'void GCMDriver::Register(const std::string& app_id,\n                         const std::vector<std::string>& sender_ids,\n                         RegisterCallback callback) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices() &&
      !metabrowser::IsWebsitePushApp(app_id)) {
    std::move(callback).Run(std::string(), GCMClient::GCM_DISABLED);
    return;
  }''', 'gcm-register')
    guard('components/gcm_driver/gcm_driver.cc',
          'void GCMDriver::Send(const std::string& app_id,\n                     const std::string& receiver_id,\n                     const OutgoingMessage& message,\n                     SendCallback callback) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices() &&
      !metabrowser::IsWebsitePushApp(app_id)) {
    std::move(callback).Run(std::string(), GCMClient::GCM_DISABLED);
    return;
  }''', 'gcm-send')
    guard('components/gcm_driver/gcm_driver_desktop.cc',
          'void GCMDriverDesktop::DeleteToken(const std::string& app_id,\n                                   const std::string& authorized_entity,\n                                   const std::string& scope,\n                                   DeleteTokenCallback callback) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices() &&
      !metabrowser::IsWebsitePushApp(app_id)) {
    std::move(callback).Run(GCMClient::GCM_DISABLED);
    return;
  }''', 'gcm-delete-token')
    guard('components/gcm_driver/gcm_driver_desktop.cc',
          'void GCMDriverDesktop::SetAccountTokens(\n    const std::vector<GCMClient::AccountTokenInfo>& account_tokens) {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return;', 'gcm-browser-account-tokens')
    guard('chrome/browser/navigation_predictor/search_engine_preconnector.cc',
          'void SearchEnginePreconnector::StartPreconnecting(bool with_startup_delay) {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return;', 'search-engine-preconnect-start')
    guard('chrome/browser/navigation_predictor/search_engine_preconnector.cc',
          'void SearchEnginePreconnector::PreconnectDSE(bool is_startup) {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return;', 'search-engine-preconnect-attempt')
    guard('chrome/browser/signin/account_consistency_mode_manager.cc',
          'signin::AccountConsistencyMethod ComputeAccountConsistencyMethod(\n    Profile* profile) {',
          '''  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) {
    return AccountConsistencyMethod::kDisabled;
  }''', 'browser-account-consistency')
    guard('chrome/browser/signin/account_consistency_mode_manager.cc',
          'bool AccountConsistencyModeManager::IsDiceSignInAllowed(\n    ProfileAttributesEntry* entry) {',
          '  if (!metabrowser::AllowGoogleBrowserBackgroundServices()) return false;', 'browser-dice-signin')
    return p


if __name__ == '__main__':
    context.make_plan = make_plan
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        context.main()
    plan = json.loads(output.getvalue())
    result = {key:plan[key] for key in ('applied', 'changed_files', 'all_files', 'sha256')}
    result.update(runtime_policy='Browser Google services disabled by default; permission-controlled website push retained; no domain blocking',
                  diagnostic_override='--metabrowser-enable-google-background-services',
                  full_network_privacy_proven=False)
    print(json.dumps(result, indent=2))
