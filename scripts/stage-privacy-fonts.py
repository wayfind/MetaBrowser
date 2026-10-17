#!/usr/bin/env python3
"""Close native macOS font-cache and glyph-fallback privacy bypasses.

Only implicit system fonts are filtered. WebFont data remains usable. The
FontSelector virtual boundary keeps platform code independent of Blink core
and provides an unchanged default for non-web/native selectors and privacy off.
Preview by default; preflights every edit before writes. No build/network.
"""
import argparse
import hashlib
import json
from pathlib import Path

CORE = 'third_party/blink/renderer/core/'
PLATFORM = 'third_party/blink/renderer/platform/fonts/'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    if (root / 'chrome/VERSION').read_text().splitlines() != [
            'MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']:
        raise SystemExit('Expected pinned Chromium 154.0.8037.97')
    before, after = {}, {}

    def read(path):
        if path not in before:
            p = root / path
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError('Path escapes source checkout')
            before[path] = p.read_text()
            after[path] = before[path]
        return after[path]

    def edit(path, old, new, label, previous=None):
        text = read(path)
        marker = '// METABROWSER_FONT_SOURCE_V1: ' + label + '\n'
        value = marker + new
        if previous is not None and marker + previous in text:
            if text.count(marker + previous) != 1:
                raise ValueError('Duplicate prior font patch: ' + label)
            after[path] = text.replace(marker + previous, value, 1)
            return
        if value in text:
            if text.count(value) != 1:
                raise ValueError('Duplicate font patch: ' + label)
            return
        if marker in text or text.count(old) != 1:
            raise ValueError('Pinned font source drift: ' + path + ': ' + label)
        after[path] = text.replace(old, value, 1)

    path = PLATFORM + 'font_selector.h'
    edit(path, '  ~FontSelector() override = default;',
         '  ~FontSelector() override = default;\n'
         '  virtual bool IsSystemFontFilteringEnabled() const { return false; }',
         'selector-policy')
    edit(path, 'class UseCounter;', 'class UseCounter;\nclass SimpleFontData;',
         'simple-font-forward')
    edit(path, '  virtual ExecutionContext* GetExecutionContext() const = 0;',
         '''  virtual bool IsSystemFontAllowed(const SimpleFontData* data) const {
    return true;
  }
  virtual const SimpleFontData* FilterSystemFallback(
      const FontDescription&, const SimpleFontData* data) const {
    return data;
  }
  virtual ExecutionContext* GetExecutionContext() const = 0;''', 'selector-boundary')

    path = PLATFORM + 'font_platform_data.h'
    edit(path, '  CTFontRef CtFont() const;',
         '  CTFontRef CtFont() const;\n  bool IsPrivacySafeSystemFont() const;', 'native-source-query')
    path = PLATFORM + 'mac/font_platform_data_mac.mm'
    old = 'namespace blink {\n'
    native = old + '''
bool FontPlatformData::IsPrivacySafeSystemFont() const {
  CTFontRef font = CtFont();
  if (!font) return false;
  ScopedCFTypeRef<CFTypeRef> attribute(CTFontCopyAttribute(font, kCTFontURLAttribute));
  const auto url = base::apple::CFCast<CFURLRef>(attribute.get());
  if (!url) return false;
  ScopedCFTypeRef<CFStringRef> path(CFURLCopyFileSystemPath(url, kCFURLPOSIXPathStyle));
  // SIP-owned OS fonts, including FontServices' reserved CJK fonts and Apple's
  // system font assets. No user-font directory, mutable /Library/Fonts or
  // family-name-only trust. WebFonts retain their original data and metrics.
  return path && (
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/Fonts/")) ||
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/PrivateFrameworks/FontServices.framework/")) ||
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/AssetsV2/com_apple_MobileAsset_Font")));
}
'''
    previous = native.replace('''  // SIP-owned OS fonts, including FontServices' reserved CJK fonts and Apple's
  // system font assets. No user-font directory, mutable /Library/Fonts or
  // family-name-only trust. WebFonts retain their original data and metrics.
  return path && (
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/Fonts/")) ||
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/PrivateFrameworks/FontServices.framework/")) ||
      CFStringHasPrefix(path.get(), CFSTR("/System/Library/AssetsV2/com_apple_MobileAsset_Font")));''', '''  // SIP-owned stock fonts. No user-font directory, mutable /Library/Fonts,
  // downloaded assets, or family-name-only trust. WebFonts bypass this implicit
  // system-font path and retain their original data and metrics.
  return path && CFStringHasPrefix(path.get(), CFSTR("/System/Library/Fonts/"));''')
    edit(path, old, native, 'coretext-source', previous=previous)

    path = CORE + 'css/css_font_selector_base.h'
    old = '// METABROWSER_FONT_SOURCE_V1: core-selector-boundary\n'
    # Install after the original boundary below has been established.
    edit(path, '  void ReportNotDefGlyph() const override;',
         '''  bool IsSystemFontAllowed(const SimpleFontData*) const override;
  const SimpleFontData* FilterSystemFallback(
      const FontDescription&, const SimpleFontData*) const override;
  void ReportNotDefGlyph() const override;''', 'core-selector-boundary')
    edit(path, old, '  bool IsSystemFontFilteringEnabled() const override;\n' + old,
         'core-selector-policy')
    path = CORE + 'css/css_font_selector_base.cc'
    old = '#include "third_party/blink/renderer/platform/fonts/font_cache.h"'
    edit(path, old, old + '\n#include "third_party/blink/renderer/platform/fonts/simple_font_data.h"\n'
         '#include "third_party/blink/renderer/platform/font_family_names.h"', 'core-dependencies')
    old = 'bool CSSFontSelectorBase::IsPlatformFamilyMatchAvailable(\n'
    edit(path, old, '''bool CSSFontSelectorBase::IsSystemFontAllowed(const SimpleFontData* data) const {
  if (!data) return false;
#if BUILDFLAG(IS_MAC)
  if (MetaBrowserSurfaceProtected(GetExecutionContext()))
    return data->PlatformData().IsPrivacySafeSystemFont();
#endif
  return true;
}

const SimpleFontData* CSSFontSelectorBase::FilterSystemFallback(
    const FontDescription& description, const SimpleFontData* data) const {
  if (!data || IsSystemFontAllowed(data)) return data;
  const auto* safe = FontCache::Get().GetFontData(description, font_family_names::kSystemUi);
  if (IsSystemFontAllowed(safe)) return safe;
  for (const char* family : {"Helvetica", "Times"}) {
    safe = FontCache::Get().GetFontData(description, AtomicString(family));
    if (IsSystemFontAllowed(safe)) return safe;
  }
  return nullptr;
}

''' + old, 'core-source-filter')
    old = '// METABROWSER_FONT_SOURCE_V1: core-source-filter\n'
    edit(path, old, '''bool CSSFontSelectorBase::IsSystemFontFilteringEnabled() const {
#if BUILDFLAG(IS_MAC)
  return MetaBrowserSurfaceProtected(GetExecutionContext());
#else
  return false;
#endif
}

''' + old, 'core-policy')
    # Keep the preceding Mac-stage marker/replacement intact for idempotence.
    old = '// METABROWSER_MAC_PRIVACY_V1: font-check-visibility\n'
    prior = '''  if (!MetaBrowserFontVisible(GetExecutionContext(), family)) return false;
  if (!IsSystemFontAllowed(FontCache::Get().GetFontData(font_description, family)))
    return false;
''' + old
    edit(path, old, '''  if (!MetaBrowserFontVisible(GetExecutionContext(), family)) return false;
  if (IsSystemFontFilteringEnabled() &&
      !IsSystemFontAllowed(FontCache::Get().GetFontData(font_description, family)))
    return false;
''' + old, 'font-check-source', previous=prior)

    path = CORE + 'css/css_font_selector.cc'
    old = '  return font_data;'
    edit(path, old, '  return IsSystemFontAllowed(font_data) ? font_data : nullptr;', 'css-source')
    path = CORE + 'css/offscreen_font_selector.cc'
    old = '  return FontCache::Get().GetFontData(font_description, settings_family_name);'
    edit(path, old, '''  const auto* data = FontCache::Get().GetFontData(font_description, settings_family_name);
  return IsSystemFontAllowed(data) ? data : nullptr;''', 'worker-source')

    for path in (CORE + 'css/local_font_face_source.cc', CORE + 'css/remote_font_face_source.cc'):
        old = '''  const SimpleFontData* temporary_font =
      FontCache::Get().GetLastResortFallbackFont(font_description);'''
        edit(path, old, old + '''
  temporary_font = font_selector_->FilterSystemFallback(font_description, temporary_font);''', 'loading-fallback-source')
    path = CORE + 'css/local_font_face_source.cc'
    old = '  // TODO(crbug.com/1025945): Properly handle Windows prior to 10 and Android.'
    # Do not alter the Mac-stage exact marker above this comment.
    old = '''  bool font_available = FontCache::Get().IsPlatformFontUniqueNameMatchAvailable(
      font_description, font_name_);'''
    edit(path, old, '''  const auto* data = FontCache::Get().GetFontData(font_description,
      font_name_, AlternateFontName::kLocalUniqueFace);
  if (!font_selector_->IsSystemFontAllowed(data)) return false;
''' + old, 'unique-source')
    old = '  if (!unique_lookup_result) {'
    edit(path, old, '  if (!unique_lookup_result ||\n'
         '      !font_selector_->IsSystemFontAllowed(unique_lookup_result)) {', 'unique-loaded-source')

    path = PLATFORM + 'font_fallback_list.cc'
    old = '''    if (!result && !curr_family->FamilyName().empty()) {
      result = FontCache::Get().GetFontData(font_description,
                                            curr_family->FamilyName());
    }'''
    previous = '''    if (!result && !curr_family->FamilyName().empty() &&
        font_selector_->IsPlatformFamilyMatchAvailable(font_description, *curr_family)) {
      const auto* data = FontCache::Get().GetFontData(font_description,
                                                    curr_family->FamilyName());
      if (font_selector_->IsSystemFontAllowed(data)) result = data;
    }'''
    edit(path, old, '''    if (!result && !curr_family->FamilyName().empty() &&
        (!font_selector_->IsSystemFontFilteringEnabled() ||
         font_selector_->IsPlatformFamilyMatchAvailable(font_description, *curr_family))) {
      const auto* data = FontCache::Get().GetFontData(font_description,
                                                    curr_family->FamilyName());
      if (font_selector_->IsSystemFontAllowed(data)) result = data;
    }''', 'selector-miss-bypass', previous=previous)
    old = '''      const SimpleFontData* last_resort_fallback =
          font_cache.GetLastResortFallbackFont(font_description);'''
    edit(path, old, old + '''
      if (font_selector_)
        last_resort_fallback = font_selector_->FilterSystemFallback(
            font_description, last_resort_fallback);''', 'primary-last-resort')
    old = '''  auto* last_resort =
      FontCache::Get().GetLastResortFallbackFont(font_description);'''
    edit(path, old, old + '''
  if (font_selector_)
    last_resort = font_selector_->FilterSystemFallback(font_description, last_resort);''', 'list-last-resort')

    path = PLATFORM + 'font_fallback_iterator.cc'
    old = '''    const SimpleFontData* last_resort =
        font_cache.GetLastResortFallbackFont(font_description_);'''
    edit(path, old, old + '''
    if (auto* selector = font_fallback_list_->GetFontSelector())
      last_resort = selector->FilterSystemFallback(font_description_, last_resort);''', 'iterator-last-resort')
    for signature, label in (
            ('const SimpleFontData* FontFallbackIterator::FallbackPriorityFont(UChar32 hint) {', 'priority-fallback'),
            ('const SimpleFontData* FontFallbackIterator::UniqueSystemFontForHintList(', 'glyph-fallback')):
        text = read(path)
        marker = '// METABROWSER_FONT_SOURCE_V1: ' + label + '\n'
        if marker in text:
            # edit() below validates the exact inserted return body as well.
            expected = '''  if (auto* selector = font_fallback_list_->GetFontSelector())
    return selector->FilterSystemFallback(font_description_, font_data);
  return font_data;'''
            if text.count(marker + expected) != 1:
                raise ValueError('Existing glyph fallback patch drift')
            continue
        start = text.index(signature)
        end = text.index('\n}', start)
        body = text[start:end]
        if body.count('  return font_data;') != 1 or body.count('FallbackFontForCharacter(') != 1:
            raise ValueError('Glyph fallback signature drift')
        after[path] = text[:start] + body.replace('  return font_data;', marker + '''  if (auto* selector = font_fallback_list_->GetFontSelector())
    return selector->FilterSystemFallback(font_description_, font_data);
  return font_data;''', 1) + text[end:]

    for path, value in before.items():
        if (root / path).read_text() != value:
            raise SystemExit('Source changed during preflight: ' + path)
    changed = [p for p in after if before[p] != after[p]]
    if args.apply:
        for path in changed:
            (root / path).write_text(after[path])
    print(json.dumps({'applied': args.apply, 'changed': changed,
                      'all_files': {p: hashlib.sha256(t.encode()).hexdigest()
                                    for p, t in after.items()}}, indent=2))


if __name__ == '__main__':
    main()
