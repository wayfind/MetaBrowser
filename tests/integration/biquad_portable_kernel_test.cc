// Compile with -I chromium/privacy. Exercises the actual staged process body.
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <span>
#include <vector>

bool MetaBrowserPortableBiquadProcess() { return true; }
struct Kernel {
  std::vector<double> b0_, b1_, b2_, a1_, a2_;
  double x1_ = 0, x2_ = 0, y1_ = 0, y2_ = 0;
  bool varying = false;
  bool HasSampleAccurateValues() { return varying; }
  void Process(std::span<const float> source, std::span<float> dest) {
    const size_t frames_to_process = source.size();
#include "metabrowser_biquad_process.inc"
    assert(false);
  }
};

int main() {
  size_t cases = 0;
  for (int filter = 0; filter < 4; ++filter)
    for (int automation = 0; automation < 3; ++automation) {
      constexpr size_t frames = 8192;
      std::vector<float> input(frames), whole(frames), divided(frames), alias;
      for (size_t i = 0; i < frames; ++i)
        input[i] = float((int((i * 17) % 257) - 128) / 640.0);
      Kernel original;
      original.varying = automation != 0;
      for (size_t i = 0; i < frames; ++i) {
        // Exactly representable stable poles; automation changes at non-quantum
        // boundaries. The identity case also detects destructive alias reads.
        double t = automation == 1 ? double(i % 17) / 1024 :
                   automation == 2 && i >= 2053 ? 0.0625 : 0;
        original.b0_.push_back(filter == 0 ? 1 : 0.5 + t);
        original.b1_.push_back(filter == 0 ? 0 : -0.125);
        original.b2_.push_back(filter < 2 ? 0 : 0.0625);
        original.a1_.push_back(filter == 0 ? 0 : -0.25 + t);
        original.a2_.push_back(filter < 3 ? 0 : 0.125);
      }
      Kernel full = original;
      full.Process(input, whole);
      // Independent extended precision recurrence; compare every output.
      long double x1 = 0, x2 = 0, y1 = 0, y2 = 0;
      for (size_t i = 0; i < frames; ++i) {
        size_t c = original.varying ? i : 0;
        long double x = input[i];
        long double y = original.b0_[c]*x + original.b1_[c]*x1 +
            original.b2_[c]*x2 - original.a1_[c]*y1 - original.a2_[c]*y2;
        assert(std::abs(whole[i] - y) < 3e-8L);
        x2=x1; x1=x; y2=y1; y1=y;
      }
      for (size_t block : {size_t(1), size_t(127), size_t(128), size_t(1024)}) {
        for (bool inplace : {false, true}) {
          Kernel k = original;
          alias = input;
          for (size_t start = 0; start < frames; start += block) {
            size_t count = std::min(block, frames - start);
            // Once coefficients have settled, transition back to the fixed
            // branch without resetting recursive history.
            if (automation == 2 && start >= 4096) k.varying = false;
            if (original.varying) {
              auto slice = [start](const std::vector<double>& v) {
                return std::vector<double>(v.begin() + start, v.end());
              };
              k.b0_=slice(original.b0_); k.b1_=slice(original.b1_);
              k.b2_=slice(original.b2_); k.a1_=slice(original.a1_);
              k.a2_=slice(original.a2_);
            }
            k.Process(std::span<const float>(inplace ? alias : input).subspan(start,count),
                      std::span<float>(inplace ? alias : divided).subspan(start,count));
          }
          const auto& actual = inplace ? alias : divided;
          assert(std::memcmp(actual.data(),whole.data(),frames*sizeof(float))==0);
          ++cases;
        }
      }
      assert(std::fwrite(whole.data(),sizeof(float),whole.size(),stdout)==whole.size());
    }
  std::fprintf(stderr,"portable production recurrence: %zu partition/alias cases passed\n",cases);
}
