// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_CANVAS_NOISE_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_CANVAS_NOISE_H_

#include <cstdint>

#include "base/compiler_specific.h"
#include "base/hash/hash.h"
#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_noise_mix.h"
#include "third_party/blink/renderer/core/execution_context/execution_context.h"
#include "third_party/blink/renderer/platform/graphics/static_bitmap_image.h"
#include "third_party/blink/renderer/platform/graphics/unaccelerated_static_bitmap_image.h"
#include "third_party/skia/include/core/SkBitmap.h"
#include "third_party/skia/include/core/SkImage.h"
#include "third_party/skia/include/core/SkPixmap.h"

namespace blink {
// Copy only at the web-exposed export boundary. Never mutate a compositor image
// or a buffer later reused by drawImage/transferToImageBitmap. Always perturb
// the complete bitmap BEFORE cropping, so tiled reads cannot average different
// region noise. This is bounded, best-effort entropy perturbation, NOT resistance
// to chosen-content averaging attacks.
inline scoped_refptr<StaticBitmapImage> MetaBrowserProtectCanvasExport(
    scoped_refptr<StaticBitmapImage> image, ExecutionContext* context) {
  if (!image || !context || !context->CanvasNoiseToken()) return image;
  const auto paint = image->PaintImageForCurrentFrame();
  auto info = paint.GetSkImageInfo().makeAlphaType(kUnpremul_SkAlphaType);
  const bool half_float = info.colorType() == kRGBA_F16_SkColorType ||
      info.colorType() == kRGBA_F16Norm_SkColorType;
  if (!half_float && info.colorType() != kRGBA_8888_SkColorType &&
      info.colorType() != kBGRA_8888_SkColorType) return nullptr;
  // Every protected read copies the complete image. Bound both scratch memory
  // and work, including tiny getImageData reads from enormous source canvases.
  constexpr int kMaxPixels = 4 * 1024 * 1024;
  constexpr int kMaxDimension = 16384;
  if (info.width() <= 0 || info.height() <= 0 ||
      info.width() > kMaxDimension || info.height() > kMaxDimension ||
      info.width() > kMaxPixels / info.height()) return nullptr;
  if (!half_float) info = info.makeColorType(kRGBA_8888_SkColorType);
  SkBitmap copy;
  if (!copy.tryAllocPixels(info) ||
      !paint.readPixels(info, copy.getPixels(), copy.rowBytes(), 0, 0))
    return nullptr;
  SkPixmap pixels;
  if (!copy.peekPixels(&pixels)) return nullptr;
  if (half_float) {
    // Keep the real HDR/color space and float16 representation. Work on the
    // entire copy before any crop/format conversion, just like the 8-bit path.
    // Finite RGB values change by at most one representable half-float step;
    // signed zero, infinities, NaNs and alpha are preserved verbatim.
    const auto bytes = info.computeByteSize(copy.rowBytes());
    const auto data = UNSAFE_BUFFERS(base::span(
        static_cast<const uint8_t*>(copy.getPixels()), bytes));
    const uint64_t seed = MetaBrowserNoiseMix64(
        context->CanvasNoiseToken()->Value() ^ UINT64_C(0x4d42484452463032) ^
        (static_cast<uint64_t>(pixels.width()) << 32) ^
        static_cast<uint64_t>(pixels.height()) ^
        static_cast<uint64_t>(base::PersistentHash(data)));
    for (int y = 0; y < pixels.height(); ++y) {
      auto row = UNSAFE_BUFFERS(base::span(
          static_cast<uint16_t*>(pixels.writable_addr(0, y)),
          static_cast<size_t>(pixels.width()) * 4));
      for (int x = 0; x < pixels.width(); ++x) {
        auto pixel = row.subspan(static_cast<size_t>(x) * 4, size_t{4});
        const uint8_t mask = MetaBrowserHalfFloatMask(
            seed, static_cast<uint64_t>(y) * pixels.width() + x);
        for (int channel = 0; channel < 3; ++channel) {
          const uint16_t magnitude = pixel[channel] & 0x7fff;
          if (magnitude && magnitude < 0x7c00 && (mask & (1u << channel)))
            pixel[channel] ^= 1;
        }
      }
    }
    copy.setImmutable();
    return UnacceleratedStaticBitmapImage::Create(SkImages::RasterFromBitmap(copy));
  }
  // Stable across processes, including DCHECK builds. FastHash intentionally
  // includes a per-process address salt in those builds and cannot be used.
  // This checksum is not a cryptographic privacy primitive.
  const auto bytes = info.computeByteSize(copy.rowBytes());
  const auto data = UNSAFE_BUFFERS(base::span(
      static_cast<const uint8_t*>(copy.getPixels()), bytes));
  const uint32_t seed = static_cast<uint32_t>(MetaBrowserNoiseMix64(
      context->CanvasNoiseToken()->Value() ^ UINT64_C(0x4d4243414e563033) ^
      (static_cast<uint64_t>(pixels.width()) << 32) ^
      static_cast<uint64_t>(pixels.height()) ^
      static_cast<uint64_t>(base::PersistentHash(data))));
  // Keep uniform regions uniform, preserve alpha and fully transparent pixels,
  // and bound each RGB channel's change to three 8-bit levels. No row vectors,
  // alpha scratch bitmap, random cross-image reads or per-pixel out-of-line
  // PRNG calls: the same protection can run at canvas-to-media boundaries.
  for (int y = 0; y < pixels.height(); ++y) {
    for (int x = 0; x < pixels.width(); ++x) {
      auto* pixel = pixels.writable_addr32(x, y);
      if ((*pixel >> 24) == 0) continue;
      uint32_t value = *pixel ^ seed;
      value ^= value >> 16;
      value *= 0x7feb352dU;
      value ^= value >> 15;
      value *= 0x846ca68bU;
      value ^= value >> 16;
      *pixel ^= (value & 3U) | ((value & 12U) << 6) |
                ((value & 48U) << 12);
    }
  }
  copy.setImmutable();
  return UnacceleratedStaticBitmapImage::Create(SkImages::RasterFromBitmap(copy));
}
}  // namespace blink
#endif
