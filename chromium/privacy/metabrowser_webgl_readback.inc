// Native WebGL normalized-color readback. This method is inserted in the
// WebGLRenderingContextBase translation unit, inside namespace blink.
bool WebGLRenderingContextBase::MetaBrowserReadPixels(
    GLint x, GLint y, GLsizei width, GLsizei height, GLenum format, GLenum type,
    base::span<uint8_t> destination, GLuint pixel_pack_buffer,
    GLintptr pixel_pack_offset) {
  auto* context = GetExecutionContext();
  if (!MetaBrowserSurfaceProtected(context)) return false;
  // Integer/depth/stencil readbacks carry application data, not normalized
  // colors. Preserve their exact arithmetic and upstream validation semantics.
  const size_t channels = format == GL_RGBA || format == GL_BGRA_EXT ? 4 :
      format == GL_RGB ? 3 : format == GL_RG || format == GL_LUMINANCE_ALPHA ? 2 :
      format == GL_RED || format == GL_LUMINANCE || format == GL_ALPHA ? 1 : 0;
  const bool packed16 = type == GL_UNSIGNED_SHORT_5_6_5 ||
      type == GL_UNSIGNED_SHORT_4_4_4_4 || type == GL_UNSIGNED_SHORT_5_5_5_1;
  const bool packed32 = type == GL_UNSIGNED_INT_2_10_10_10_REV ||
      type == GL_UNSIGNED_INT_10F_11F_11F_REV || type == GL_UNSIGNED_INT_5_9_9_9_REV;
  const bool half_float = type == GL_HALF_FLOAT || type == GL_HALF_FLOAT_OES;
  const bool signed_normalized = type == GL_BYTE || type == GL_SHORT || type == GL_INT;
  const size_t scalar_bytes = type == GL_UNSIGNED_BYTE || type == GL_BYTE ? 1 :
      type == GL_FLOAT || type == GL_UNSIGNED_INT || type == GL_INT || packed32 ? 4 :
      half_float || type == GL_UNSIGNED_SHORT || type == GL_SHORT || packed16 ? 2 : 0;
  if (!channels || !scalar_bytes || width == 0 || height == 0) return false;
  constexpr size_t kMaxPixels = 4 * 1024 * 1024;
  constexpr size_t kMaxScratch = 80 * 1024 * 1024;
  if (width < 0 || height < 0 || static_cast<size_t>(width) > kMaxPixels ||
      static_cast<size_t>(height) > kMaxPixels / static_cast<size_t>(width)) {
    SynthesizeGLError(GL_OUT_OF_MEMORY, "readPixels", "Privacy readback budget exceeded.");
    return true;
  }
  const auto pack = GetPackPixelStoreParams();
  unsigned required = 0, skip = 0;
  const auto error = WebGLImageConversion::ComputeImageSizeInBytes(
      format, type, width, height, 1, pack, &required, nullptr, &skip);
  const size_t total = static_cast<size_t>(required) + skip;
  if (error != GL_NO_ERROR || total > kMaxScratch ||
      (!pixel_pack_buffer && destination.size() < total)) {
    SynthesizeGLError(error != GL_NO_ERROR ? error : GL_OUT_OF_MEMORY,
        "readPixels", "Privacy readback packing exceeds the protection budget.");
    return true;
  }
  if (pixel_pack_buffer && pixel_pack_offset % scalar_bytes) {
    SynthesizeGLError(GL_INVALID_OPERATION, "readPixels", "Unaligned pixel-pack offset.");
    return true;
  }
  const size_t pixel_bytes = packed16 || packed32 ? scalar_bytes : channels * scalar_bytes;
  const size_t row_pixels = pack.row_length > 0 ? static_cast<size_t>(pack.row_length) : width;
  const size_t stride = (row_pixels * pixel_bytes + pack.alignment - 1) /
      pack.alignment * pack.alignment;
  const size_t row_bytes = static_cast<size_t>(width) * pixel_bytes;
  SkBitmap scratch;
  if (!scratch.tryAllocPixels(SkImageInfo::MakeA8(static_cast<int>(total), 1))) {
    SynthesizeGLError(GL_OUT_OF_MEMORY, "readPixels", "Privacy readback allocation failed.");
    return true;
  }
  scratch.eraseColor(0);
  auto bytes = UNSAFE_BUFFERS(base::span(static_cast<uint8_t*>(scratch.getPixels()), total));
  auto relay_errors = [&]() {
    bool failed = false;
    // GLES maintains a finite set of error flags. Bound a broken/lost backend.
    for (unsigned i = 0; i < 16; ++i) {
      const GLenum gl_error = ContextGL()->GetError();
      if (gl_error == GL_NO_ERROR) return failed;
      SynthesizeGLError(gl_error, "readPixels", "Native readback error.");
      failed = true;
    }
    ForceLostContext(kSyntheticLostContext, kManual);
    return true;
  };
  // Prior errors cannot be used to trick protection into returning raw pixels.
  // Preserve their flags, then check this read's actual result separately.
  relay_errors();
  if (isContextLost()) return true;
  if (pixel_pack_buffer) ContextGL()->BindBuffer(GL_PIXEL_PACK_BUFFER, 0);
  // Never write raw GPU pixels to JS memory, including SharedArrayBuffer, or
  // to a script-visible PBO. The only raw copy is private native scratch.
  ContextGL()->ReadPixels(x, y, width, height, format, type, bytes.data());
  const bool failed = relay_errors();
  if (pixel_pack_buffer && !isContextLost())
    ContextGL()->BindBuffer(GL_PIXEL_PACK_BUFFER, pixel_pack_buffer);
  if (failed || isContextLost()) return true;

  const uint64_t token = context->CanvasNoiseToken()->Value();
  const uint64_t domain = MetaBrowserSurfaceMix(token ^ UINT64_C(0x4d4257474c303031));
  for (size_t row = 0; row < static_cast<size_t>(height); ++row) {
    const size_t begin = skip + row * stride;
    auto data = bytes.subspan(begin, row_bytes);
    for (size_t column = 0; column < static_cast<size_t>(width); ++column) {
      const auto absolute_x = static_cast<uint64_t>(static_cast<int64_t>(x) + static_cast<int64_t>(column));
      const auto absolute_y = static_cast<uint64_t>(static_cast<int64_t>(y) + static_cast<int64_t>(row));
      uint64_t key = MetaBrowserSurfaceMix(domain ^ absolute_x);
      key = MetaBrowserSurfaceMix(key ^ absolute_y ^ (static_cast<uint64_t>(format) << 32) ^ type);
      const size_t first = column * pixel_bytes;
      for (size_t index = 0; index < pixel_bytes; ++index)
        key = MetaBrowserSurfaceMix(key ^ data[first + index]);
      const bool has_alpha = channels == 4 || format == GL_LUMINANCE_ALPHA || format == GL_ALPHA;
      const size_t colors = has_alpha ? channels - 1 : channels;
      if (packed16 || packed32) {
        uint32_t encoded = 0;
        for (size_t index = 0; index < pixel_bytes; ++index)
          encoded |= static_cast<uint32_t>(data[first + index]) << (8 * index);
        std::array<unsigned, 3> shifts;
        std::array<unsigned, 3> widths;
        switch (type) {
          case GL_UNSIGNED_SHORT_5_6_5: shifts = {11, 5, 0}; widths = {5, 6, 5}; break;
          case GL_UNSIGNED_SHORT_4_4_4_4: shifts = {12, 8, 4}; widths = {4, 4, 4}; break;
          case GL_UNSIGNED_SHORT_5_5_5_1: shifts = {11, 6, 1}; widths = {5, 5, 5}; break;
          case GL_UNSIGNED_INT_2_10_10_10_REV: shifts = {0, 10, 20}; widths = {10, 10, 10}; break;
          case GL_UNSIGNED_INT_10F_11F_11F_REV: shifts = {0, 11, 22}; widths = {11, 11, 10}; break;
          default: shifts = {0, 9, 18}; widths = {9, 9, 9}; break;
        }
        for (size_t channel = 0; channel < 3; ++channel) {
          const uint32_t mask = (1u << widths[channel]) - 1;
          const auto value = (encoded >> shifts[channel]) & mask;
          // Preserve endpoints, alpha/shared exponents, and packed NaN/Inf.
          const bool exceptional = type == GL_UNSIGNED_INT_10F_11F_11F_REV &&
              (value >> (widths[channel] - 5)) == 31;
          if (value && value != mask && !exceptional &&
              (MetaBrowserSurfaceMix(key ^ channel) & 1))
            encoded ^= 1u << shifts[channel];
        }
        for (size_t index = 0; index < pixel_bytes; ++index)
          data[first + index] = static_cast<uint8_t>(encoded >> (8 * index));
      } else {
      for (size_t channel = 0; channel < colors; ++channel) {
        const auto noise = MetaBrowserSurfaceMix(key ^ channel);
        const size_t index = first + channel * scalar_bytes;
        if (scalar_bytes == 1) {
          // Preserve exact endpoints and alpha; perturb at most one color LSB.
          const bool endpoint = signed_normalized
              ? data[index] == 0x7f || data[index] == 0x80 || data[index] == 0x81
              : data[index] == 255;
          if (data[index] && !endpoint && (noise & 1)) data[index] ^= 1;
        } else if (scalar_bytes == 2) {
          const uint16_t bits = static_cast<uint16_t>(data[index]) |
              (static_cast<uint16_t>(data[index + 1]) << 8);
          const auto magnitude = bits & 0x7fff;
          const bool changeable = half_float ? magnitude && magnitude < 0x7c00 :
              bits && (signed_normalized ? bits != 0x7fff && bits != 0x8000 && bits != 0x8001 : bits != 0xffff);
          if (changeable && (noise & 1)) data[index] ^= 1;
        } else if (type == GL_FLOAT) {
          std::array<uint8_t, 4> encoded;
          base::span(encoded).copy_from(data.subspan(index, size_t{4}));
          const float sample = std::bit_cast<float>(encoded);
          // Exact integer payloads and exceptional values are not perturbed.
          if (std::isfinite(sample) && std::trunc(sample) != sample) {
            // Absolute 5e-8 noise rounds to zero for HDR values such as
            // 1.5 or 128.5. Select at most one representable float32 step.
            if (noise & 1) {
              const float value = std::nextafter(sample,
                  (noise & 2) ? INFINITY : -INFINITY);
              if (std::isfinite(value) && value != 0.f &&
                  std::signbit(value) == std::signbit(sample)) {
                const auto encoded_value = std::bit_cast<std::array<uint8_t, 4>>(value);
                data.subspan(index, size_t{4}).copy_from(base::span(encoded_value));
              }
            }
          }
        } else {
          uint32_t bits = 0;
          for (size_t byte = 0; byte < 4; ++byte)
            bits |= static_cast<uint32_t>(data[index + byte]) << (8 * byte);
          const bool endpoint = signed_normalized
              ? bits == 0x7fffffff || bits == 0x80000000 || bits == 0x80000001
              : bits == 0xffffffff;
          if (bits && !endpoint && (noise & 1)) data[index] ^= 1;
        }
      }
      }
    }
    if (pixel_pack_buffer) {
      ContextGL()->BufferSubData(GL_PIXEL_PACK_BUFFER,
          pixel_pack_offset + static_cast<GLintptr>(begin), row_bytes, data.data());
    } else {
      destination.subspan(begin, row_bytes).copy_from(data);
    }
  }
  return true;
}
