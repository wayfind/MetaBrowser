#!/usr/bin/env python3
"""Hide user-installed TTS voices without replacing the speech engine.

Protected pages see the stock system voices with their real names and URIs, as
official Chrome lists them. Downloaded quality variants ("Enhanced"/"Premium")
depend on the user's own installs and stay hidden. Earlier staging reduced the
list to one generically named voice per locale, which no official Chrome shows.
Explicit voice selection still routes the native name. Preview by default.
"""
import argparse
import hashlib
import json
from pathlib import Path


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
    prefix = 'third_party/blink/renderer/modules/speech/'

    def edit(name, old, new, tag, previous=None):
        path = prefix + name
        if path not in before:
            p = root / path
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError('Speech path escapes source checkout')
            before[path] = p.read_text()
            after[path] = before[path]
        text = after[path]
        marker = '// METABROWSER_SPEECH_PRIVACY_V1: ' + tag + '\n'
        value = marker + new
        for prior in ((previous,) if isinstance(previous, str) else (previous or ())):
            if marker + prior in text:
                if text.count(marker + prior) != 1:
                    raise ValueError('Duplicate prior speech patch: ' + tag)
                after[path] = text.replace(marker + prior, value, 1)
                return
        if value in text:
            if text.count(value) != 1:
                raise ValueError('Duplicate speech patch: ' + tag)
            return
        if marker in text or text.count(old) != 1:
            raise ValueError('Pinned speech source drift: ' + tag)
        after[path] = text.replace(old, value, 1)

    edit('speech_synthesis_voice.h',
         '      mojom::blink::SpeechSynthesisVoicePtr mojom_voice);',
         '      mojom::blink::SpeechSynthesisVoicePtr mojom_voice, bool protect_identity = false);',
         'constructor-parameter')
    edit('speech_synthesis_voice.h',
         '  const String& voiceURI() const { return mojom_voice_->voice_uri; }\n'
         '  const String& name() const { return mojom_voice_->name; }',
         '''  const String& voiceURI() const { return protect_identity_ ? public_uri_ : mojom_voice_->voice_uri; }
  const String& name() const { return protect_identity_ ? public_name_ : mojom_voice_->name; }
  // Not a WebIDL member: native speech routing must never use the public alias.
  const String& NativeName() const { return mojom_voice_->name; }''', 'public-aliases')
    edit('speech_synthesis_voice.h',
         '  mojom::blink::SpeechSynthesisVoicePtr mojom_voice_;',
         '''  bool protect_identity_ = false;
  String public_name_;
  String public_uri_;
  mojom::blink::SpeechSynthesisVoicePtr mojom_voice_;''', 'private-fields')
    old = '#include "third_party/blink/renderer/modules/speech/speech_synthesis_voice.h"'
    edit('speech_synthesis_voice.cc', old, old + '\n'
         '#include "third_party/blink/renderer/platform/wtf/text/string_builder.h"', 'string-builder')
    edit('speech_synthesis_voice.cc',
         '''    mojom::blink::SpeechSynthesisVoicePtr mojom_voice)
    : mojom_voice_(std::move(mojom_voice)) {}''',
         '''    mojom::blink::SpeechSynthesisVoicePtr mojom_voice, bool protect_identity)
    : protect_identity_(protect_identity), mojom_voice_(std::move(mojom_voice)) {
  if (protect_identity_) {
    StringBuilder name;
    name.Append("System voice ("); name.Append(mojom_voice_->lang); name.Append(")");
    public_name_ = name.ToString();
    StringBuilder uri;
    uri.Append("urn:metabrowser:voice:"); uri.Append(mojom_voice_->lang);
    public_uri_ = uri.ToString();
  }
}''', 'construct-aliases')
    old = '#include "third_party/blink/renderer/modules/speech/speech_synthesis.h"'
    edit('speech_synthesis.cc', old, old + '''
#include <algorithm>
#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_surface_privacy.h"
#include "third_party/blink/renderer/core/frame/navigator.h"
#include "third_party/blink/renderer/platform/wtf/hash_set.h"''', 'dependencies')
    visibility_before = '''  voice_list_.clear();
  for (auto& mojom_voice : mojom_voices) {
    voice_list_.push_back(
        MakeGarbageCollected<SpeechSynthesisVoice>(std::move(mojom_voice)));
  }'''
    visibility_previous = '''  voice_list_.clear();
  const bool protect = MetaBrowserSurfaceProtected(GetSupplementable());
  const String language = protect ? GetSupplementable()->navigator()->language() : String();
  if (protect) {
    // Keep the real default when a locale has multiple installed voices.
    std::stable_sort(mojom_voices.begin(), mojom_voices.end(),
        [](const auto& a, const auto& b) { return a->is_default && !b->is_default; });
  }
  HashSet<String> exposed;
  for (auto& mojom_voice : mojom_voices) {
    if (protect && ((!EqualIgnoringAsciiCase(mojom_voice->lang, language) &&
                     !EqualIgnoringAsciiCase(mojom_voice->lang, "en-US")) ||
                    !exposed.insert(mojom_voice->lang).is_new_entry)) continue;
    voice_list_.push_back(MakeGarbageCollected<SpeechSynthesisVoice>(
        std::move(mojom_voice), protect));
  }'''
    visibility_after = visibility_previous.replace(
        "exposed.insert(mojom_voice->lang)",
        "exposed.insert(mojom_voice->lang.ToAsciiLower())")
    visibility_stock = '''  voice_list_.clear();
  const bool protect = MetaBrowserSurfaceProtected(GetSupplementable());
  for (auto& mojom_voice : mojom_voices) {
    // Stock voices keep real names; downloaded quality variants identify the
    // user's own installs and are not listed for protected pages.
    if (protect && (mojom_voice->name.contains("(Enhanced)") ||
                    mojom_voice->name.contains("(Premium)"))) {
      continue;
    }
    voice_list_.push_back(
        MakeGarbageCollected<SpeechSynthesisVoice>(std::move(mojom_voice)));
  }'''
    # The first v20n staging used String::Contains, which this WTF lacks.
    visibility_stock_contains = visibility_stock.replace('.contains(', '.Contains(')
    edit('speech_synthesis.cc', visibility_before, visibility_stock,
         'voice-visibility', previous=(visibility_after, visibility_stock_contains))
    edit('speech_synthesis_utterance.cc',
         '  mojom_utterance_->voice = voice_ ? voice_->name() : String();',
         '  mojom_utterance_->voice = voice_ ? voice_->NativeName() : String();', 'native-routing')
    for path, value in before.items():
        if (root / path).read_text() != value:
            raise SystemExit('Speech source changed during preflight: ' + path)
    changed = [p for p in after if before[p] != after[p]]
    if args.apply:
        for path in changed:
            (root / path).write_text(after[path])
    print(json.dumps({'applied': args.apply, 'changed': changed,
                      'all_files': {p: hashlib.sha256(t.encode()).hexdigest()
                                    for p, t in after.items()}}, indent=2))


if __name__ == '__main__':
    main()
