#!/usr/bin/env python3
"""Stage token-gated offline WebAudio privacy for Chromium 154.0.8037.97.

Only this script belongs in MetaBrowser. Running it against a source checkout
patches offline_audio_context.cc and its existing _test.cc (no GN/header edits).
--check previews without writing; --self-test needs a local C++17 compiler;
--print-probe emits an actual browser/worker probe, without launching a browser.

Isolation contract: CanvasNoiseToken must already be browser-derived for the
profile + top-level site + requesting origin, and delivered on every document
creation/commit. This consumer neither verifies that transport nor derives a
site from a URL. No token means byte-for-byte passthrough. There is no global,
command-line, random, or JS-visible fallback. Dedicated/shared worker and
worklet transport remains the gateway's responsibility. Chromium 154's
OfflineAudioContext itself is Window-only; realtime AnalyserNode is untouched.

The integer mixer domain-separates this surface; it is NOT a cryptographic KDF
and does not turn the existing 64-bit canvas token into a stronger secret.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


VERSION = "MAJOR=154\nMINOR=0\nBUILD=8037\nPATCH=97"
DIRECTORY = Path("third_party/blink/renderer/modules/webaudio")

# Kept standalone so --self-test compiles these exact production functions.
SCALAR = r'''// METABROWSER_PRIVACY_AUDIO_SCALAR_BEGIN
uint64_t MixOfflineAudioPrivacyBits(uint64_t value) {
  value ^= value >> 30;
  value *= UINT64_C(0xbf58476d1ce4e5b9);
  value ^= value >> 27;
  value *= UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}

float OfflineAudioPrivacySample(float sample,
                                uint64_t channel_key,
                                uint64_t sample_index) {
  // Preserve signed silence and exceptional DSP outputs verbatim. In
  // particular, do not clamp legitimate audio to [-1, 1].
  if (sample == 0.0f || !std::isfinite(sample)) {
    return sample;
  }
  const uint64_t bits = MixOfflineAudioPrivacyBits(channel_key ^ sample_index);
  const double unit = static_cast<double>(bits >> 11) * 0x1.0p-53;
  const double original = static_cast<double>(sample);
  const double limit = static_cast<double>(std::numeric_limits<float>::max());
  const double candidate = std::clamp(original + (unit * 2.0 - 1.0) * 5.0e-8,
                                      -limit, limit);
  const float result = static_cast<float>(candidate);
  // Bound the ACTUAL float32 change, including rounding. Large-magnitude
  // samples whose ULP exceeds the budget may correctly remain unchanged.
  return std::isfinite(result) &&
                 std::abs(static_cast<double>(result) - original) <= 1.0e-7
             ? result
             : sample;
}

uint64_t OfflineAudioPrivacyChannelKey(uint64_t token, unsigned channel) {
  // Stable domain "MBAUDv01"; no canvas NoiseHash state is reused.
  const uint64_t surface_key =
      MixOfflineAudioPrivacyBits(token ^ UINT64_C(0x4d42415544763031));
  return MixOfflineAudioPrivacyBits(
      surface_key ^ (UINT64_C(0x9e3779b97f4a7c15) *
                     (static_cast<uint64_t>(channel) + 1)));
}
// METABROWSER_PRIVACY_AUDIO_SCALAR_END
'''

HELPER = SCALAR + r'''
// METABROWSER_PRIVACY_AUDIO_BUFFER_BEGIN
void ApplyOfflineAudioPrivacy(AudioBuffer* buffer,
                              ExecutionContext* execution_context) {
  const auto& token = execution_context->CanvasNoiseToken();
  if (!token) {
    return;
  }
  for (unsigned channel = 0; channel < buffer->numberOfChannels(); ++channel) {
    auto samples = buffer->getChannelData(channel)->AsSpan();
    const uint64_t key = OfflineAudioPrivacyChannelKey(token->Value(), channel);
    for (size_t i = 0; i < samples.size(); ++i) {
      samples[i] = OfflineAudioPrivacySample(samples[i], key, i);
    }
  }
}
// METABROWSER_PRIVACY_AUDIO_BUFFER_END
'''

TESTS = r'''
// METABROWSER_PRIVACY_AUDIO_TEST_BEGIN
TEST_F(OfflineAudioContextTest, PrivacyCompletionReadback) {
  V8TestingScope scope;
  constexpr unsigned kFrames = 512;
  constexpr unsigned kChannels = 2;
  auto render = [&](std::optional<NoiseToken> token) -> std::vector<float> {
    scope.GetExecutionContext()->SetCanvasNoiseToken(token);
    auto* context = OfflineAudioContext::Create(
        scope.GetExecutionContext(), kChannels, kFrames, 44100.0f,
        ASSERT_NO_EXCEPTION);
    if (!context) {
      ADD_FAILURE() << "Offline context creation failed";
      return {};
    }
    auto* input = AudioBuffer::Create(kChannels, kFrames, 44100.0f);
    if (!input) {
      ADD_FAILURE() << "AudioBuffer creation failed";
      return {};
    }
    for (unsigned ch = 0; ch < kChannels; ++ch) {
      auto data = input->getChannelData(ch)->AsSpan();
      for (unsigned i = 0; i < kFrames; ++i) {
        data[i] = i % 8 == 0 ? 0.0f : 0.125f;
      }
    }
    auto* source = context->createBufferSource(ASSERT_NO_EXCEPTION);
    source->setBuffer(input, ASSERT_NO_EXCEPTION);
    source->connect(context->destination(), 0, 0, ASSERT_NO_EXCEPTION);
    source->start(ASSERT_NO_EXCEPTION);
    ScriptPromiseTester tester(
        scope.GetScriptState(),
        context->startOfflineRendering(scope.GetScriptState(),
                                       ASSERT_NO_EXCEPTION));
    tester.WaitUntilSettled();
    EXPECT_TRUE(tester.IsFulfilled());
    auto* buffer = context->destinationNode()->DestinationBuffer();
    if (!buffer) {
      ADD_FAILURE() << "Missing completed audio buffer";
      return {};
    }
    std::vector<float> result;
    for (unsigned ch = 0; ch < kChannels; ++ch) {
      const auto data = buffer->getChannelData(ch)->AsSpan();
      auto copied = NotShared<DOMFloat32Array>(DOMFloat32Array::Create(kFrames));
      buffer->copyFromChannel(copied, ch, ASSERT_NO_EXCEPTION);
      for (unsigned i = 0; i < kFrames; ++i) {
        EXPECT_EQ(data[i], copied->AsSpan()[i]);
      }
      result.insert(result.end(), data.begin(), data.end());
    }
    // A duplicate completion must not apply noise again or re-resolve.
    context->FireCompletionEvent();
    for (unsigned ch = 0; ch < kChannels; ++ch) {
      const auto data = buffer->getChannelData(ch)->AsSpan();
      for (unsigned i = 0; i < kFrames; ++i) {
        EXPECT_EQ(data[i], result[ch * kFrames + i]);
      }
    }
    return result;
  };
  const auto plain = render(std::nullopt);
  const auto first = render(NoiseToken(0));  // Zero is a valid supplied token.
  const auto repeat = render(NoiseToken(0));
  const auto other = render(NoiseToken(1));
  ASSERT_EQ(plain.size(), kFrames * kChannels);
  ASSERT_EQ(first.size(), plain.size());
  ASSERT_EQ(repeat.size(), plain.size());
  ASSERT_EQ(other.size(), plain.size());
  EXPECT_EQ(first, repeat);
  EXPECT_NE(first, plain);
  EXPECT_NE(first, other);
  bool channels_differ = false;
  for (unsigned i = 0; i < kFrames * kChannels; ++i) {
    EXPECT_EQ(plain[i], i % 8 == 0 ? 0.0f : 0.125f);
    EXPECT_TRUE(std::isfinite(first[i]));
    EXPECT_LE(std::abs(static_cast<double>(first[i]) - plain[i]), 1.0e-7);
    EXPECT_LE(std::abs(static_cast<double>(other[i]) - plain[i]), 1.0e-7);
    if (plain[i] == 0.0f) {
      EXPECT_EQ(first[i], 0.0f);
      EXPECT_EQ(other[i], 0.0f);
    }
    if (i < kFrames && first[i] != first[kFrames + i]) {
      channels_differ = true;
    }
  }
  EXPECT_TRUE(channels_differ);
  // A subsequent document/context without a token cannot inherit the last key.
  EXPECT_EQ(render(std::nullopt), plain);
}
// METABROWSER_PRIVACY_AUDIO_TEST_END
'''

PROBE = r'''<!doctype html><meta charset="utf-8">
<title>Offline audio privacy readback / worker probe</title><pre id="result"></pre>
<script>
// Serve on an origin whose gateway supplies a stable CanvasNoiseToken.
// Run on a second site/profile and compare recorded digests; JS never sets keys.
// Silence-only output alone cannot prove the transport is installed.
(async () => {
  const check = (v, message) => { if (!v) throw Error(message); };
  const same = (a, b) => a.length === b.length && a.every((x,i) => Object.is(x,b[i]));
  async function render(silent = false) {
    const ctx = new OfflineAudioContext(2, 512, 44100);
    const input = ctx.createBuffer(2, 512, 44100);
    for (let ch = 0; ch < 2; ch++)
      input.getChannelData(ch).set(Float32Array.from({length:512},
        (_, i) => silent || i % 8 === 0 ? 0 : 0.125));
    const source = ctx.createBufferSource(); source.buffer = input;
    source.connect(ctx.destination); source.start();
    let eventBuffer, eventSamples;
    ctx.oncomplete = e => {
      eventBuffer = e.renderedBuffer;
      eventSamples = Array.from({length:2}, (_,ch) => e.renderedBuffer.getChannelData(ch).slice());
    };
    const buffer = await ctx.startRendering();
    check(buffer === eventBuffer, 'event/promise buffer identity');
    const direct = [], copied = [];
    for (let ch = 0; ch < 2; ch++) {
      const data = buffer.getChannelData(ch).slice();
      const copy = new Float32Array(buffer.length); buffer.copyFromChannel(copy, ch);
      check(same(data, eventSamples[ch]), 'event/promise contents');
      check(same(data, copy), 'getChannelData/copyFromChannel');
      check(same(data, buffer.getChannelData(ch)), 'repeat getter');
      direct.push(data); copied.push(copy);
    }
    return {direct, copied};
  }
  const first = await render(), repeat = await render(), silence = await render(true);
  const workerURL = URL.createObjectURL(new Blob([`onmessage = async ({data}) => {
    try {
      const {first,repeat,silence} = data;
      const check = (v,m) => {if(!v) throw Error(m)};
      let changes=0, channelDifferences=0, maxDelta=0;
      for(let ch=0;ch<2;ch++) for(let i=0;i<512;i++) {
        const x=first.direct[ch][i], baseline=i%8===0?0:0.125;
        check(Number.isFinite(x), 'finite');
        check(Object.is(x,first.copied[ch][i]), 'worker parity');
        check(Object.is(x,repeat.direct[ch][i]), 'repeat render');
        check(silence.direct[ch][i]===0, 'silence');
        if(baseline===0) check(x===0, 'zero samples');
        const delta=Math.abs(x-baseline); maxDelta=Math.max(maxDelta,delta);
        check(delta<=1e-7, 'noise bound');
        if(x!==baseline) changes++;
        if(ch===0 && x!==first.direct[1][i]) channelDifferences++;
      }
      check(changes>0, 'no measurable noise: verify token transport');
      check(channelDifferences>0, 'channel separation');
      const bytes=new Uint8Array(4096);
      bytes.set(new Uint8Array(first.direct[0].buffer),0);
      bytes.set(new Uint8Array(first.direct[1].buffer),2048);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),
                             x=>x.toString(16).padStart(2,'0')).join('');
      postMessage({ok:true,changes,channelDifferences,maxDelta,digest});
    } catch(e) {postMessage({ok:false,error:String(e)})}
  }`], {type:'text/javascript'}));
  const worker = new Worker(workerURL);
  try {
    const result = await new Promise((resolve,reject) => {
      const timer=setTimeout(()=>reject(Error('worker probe timeout')),10000);
      worker.onmessage=e=>{clearTimeout(timer);resolve(e.data)};
      worker.onerror=e=>{clearTimeout(timer);reject(Error(e.message))};
      worker.postMessage({first,repeat,silence});
    });
    document.querySelector('#result').textContent=JSON.stringify(result,null,2);
  } finally {worker.terminate();URL.revokeObjectURL(workerURL)}
})().catch(e => document.querySelector('#result').textContent=String(e));
</script>
'''


def replace_once(text, before, after, label):
    if after in text:
        if text.count(after) != 1:
            raise ValueError(f"Duplicate patched region: {label}")
        return text
    if text.count(before) != 1:
        raise ValueError(f"Changed or partial staging anchor: {label}")
    return text.replace(before, after, 1)


def transform(text, test=False):
    original_include = '#include "third_party/blink/renderer/modules/webaudio/offline_audio_context.h"'
    added = ["<cmath>", "<cstdint>"]
    if test:
        added += ["<optional>", "<vector>",
                  '"third_party/blink/renderer/bindings/core/v8/script_promise_tester.h"',
                  '"third_party/blink/renderer/core/execution_context/execution_context.h"',
                  '"third_party/blink/renderer/modules/webaudio/audio_buffer.h"',
                  '"third_party/blink/renderer/modules/webaudio/audio_buffer_source_node.h"',
                  '"third_party/blink/renderer/modules/webaudio/offline_audio_destination_node.h"']
    else:
        added = ["<algorithm>", "<cmath>", "<cstdint>", "<limits>",
                 '"third_party/blink/renderer/modules/webaudio/audio_buffer.h"']
    includes = (original_include + "\n\n// METABROWSER_PRIVACY_AUDIO_INCLUDES_BEGIN\n" +
                "\n".join("#include " + inc for inc in added) +
                "\n// METABROWSER_PRIVACY_AUDIO_INCLUDES_END")
    text = replace_once(text, original_include, includes, "includes")
    if test:
        text = replace_once(text, "\n}  // namespace blink\n",
                            TESTS + "\n}  // namespace blink\n", "tests")
    else:
        text = replace_once(text, "namespace {\n\nOfflineAudioContext* CreateOfflineAudioContext(",
                            "namespace {\n\n" + HELPER +
                            "\nOfflineAudioContext* CreateOfflineAudioContext(", "helpers")
        before = "void OfflineAudioContext::FireCompletionEvent() {\n  DCHECK(IsMainThread());\n"
        text = replace_once(text, before, before + r'''
  // METABROWSER_PRIVACY_AUDIO_COMPLETION_GUARD
  // Closed before notifying JS: duplicate/reentrant completion is a no-op.
  if (ContextState() == V8AudioContextState::Enum::kClosed) {
    return;
  }
''', "completion guard")
        before = "    // Call the offline rendering completion event listener and resolve the\n"
        text = replace_once(text, before, r'''    // METABROWSER_PRIVACY_AUDIO_APPLY
    // Rendering has joined; mutate once before either public readout path.
    ApplyOfflineAudioPrivacy(rendered_buffer, GetExecutionContext());

''' + before, "completion processing")
    # Fail closed on partial/foreign modifications inside our marked regions.
    expected = ["INCLUDES_BEGIN", "INCLUDES_END"]
    expected += ["TEST_BEGIN", "TEST_END"] if test else [
        "SCALAR_BEGIN", "SCALAR_END", "BUFFER_BEGIN", "BUFFER_END",
        "COMPLETION_GUARD", "APPLY"]
    for suffix in expected:
        if text.count("METABROWSER_PRIVACY_AUDIO_" + suffix) != 1:
            raise ValueError(f"Invalid marker: {suffix}")
    return text


def self_test():
    """Compile exact scalar code, not a Python reimplementation of its math."""
    compiler = shutil.which("clang++") or shutil.which("c++")
    if not compiler:
        raise ValueError("--self-test requires clang++ or c++")
    harness = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <cassert>
#include <iostream>
''' + SCALAR + r'''
int main() {
  unsigned changes = 0, tokens = 0, channels = 0;
  for (uint64_t token : {0ULL, 1ULL, 0xffffffffffffffffULL}) {
    for (unsigned channel = 0; channel < 3; ++channel) {
      auto key = OfflineAudioPrivacyChannelKey(token, channel);
      for (uint64_t i = 0; i < 10000; ++i) {
        const float samples[] = {0.0f, -0.0f, 0.125f, -0.125f, 1.0f, -1.0f,
          16.0f, -16.0f, std::numeric_limits<float>::max(),
          -std::numeric_limits<float>::max(),
          std::numeric_limits<float>::denorm_min()};
        for (float x : samples) {
          float y = OfflineAudioPrivacySample(x, key, i);
          assert(std::isfinite(y));
          assert(std::abs(static_cast<double>(y) - x) <= 1e-7);
          assert(y == OfflineAudioPrivacySample(x, key, i));
          if (x == 0) assert(y == 0 && std::signbit(x) == std::signbit(y));
          changes += y != x;
        }
        float a = OfflineAudioPrivacySample(0.125f, key, i);
        tokens += a != OfflineAudioPrivacySample(0.125f,
                    OfflineAudioPrivacyChannelKey(token ^ 1, channel), i);
        channels += a != OfflineAudioPrivacySample(0.125f,
                    OfflineAudioPrivacyChannelKey(token, channel + 1), i);
      }
    }
  }
  auto key = OfflineAudioPrivacyChannelKey(0, 0);
  assert(std::isnan(OfflineAudioPrivacySample(
      std::numeric_limits<float>::quiet_NaN(), key, 0)));
  assert(std::isinf(OfflineAudioPrivacySample(
      std::numeric_limits<float>::infinity(), key, 0)));
  assert(changes && tokens && channels);
  std::cout << "scalar checks passed: changed=" << changes
            << " token_differences=" << tokens
            << " channel_differences=" << channels << '\n';
}
'''
    with tempfile.TemporaryDirectory(prefix="privacy-audio-selftest-") as tmp:
        cpp, executable = Path(tmp) / "test.cc", Path(tmp) / "test"
        cpp.write_text(harness)
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=undefined", "-fno-sanitize-recover=all",
                        str(cpp), "-o", str(executable)], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true", help="preview; no writes")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--print-probe", action="store_true", help="emit HTML to stdout")
    args = parser.parse_args()
    if args.print_probe:
        if args.source or args.self_test or args.check:
            parser.error("--print-probe must be used alone")
        print(PROBE, end="")
        return
    if args.self_test:
        self_test()
    if not args.source:
        if args.self_test:
            return
        parser.error("source root is required")
    root = args.source.resolve(strict=True)
    if (root / "chrome/VERSION").read_text().strip() != VERSION:
        raise ValueError("Unexpected Chromium version; expected 154.0.8037.97")
    planned = []
    # Validate ALL anchors before writing either file.
    for name, test in [("offline_audio_context.cc", False),
                       ("offline_audio_context_test.cc", True)]:
        path = root / DIRECTORY / name
        before = path.read_text()
        after = transform(before, test)
        if transform(after, test) != after:
            raise ValueError("Non-idempotent transformation: " + name)
        planned.append((path, before, after))
    for path, before, after in planned:
        if before == after:
            print("unchanged:", path)
            continue
        print("would patch:" if args.check else "patch:", path)
        if not args.check:
            # Preserve permissions and use a sibling atomic replacement.
            fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
            try:
                with os.fdopen(fd, "w") as output:
                    output.write(after)
                os.chmod(temp, path.stat().st_mode & 0o777)
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error))
