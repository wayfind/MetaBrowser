// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
// Finite HRTF complex analysis must not fall back to host transcendental math.
// Native expressions retain their original complex<double> overloads.
double MetaBrowserFftMagnitude(const std::complex<double>& value) {
#if defined(__clang__)
#pragma clang fp contract(off)
#pragma clang fp reassociate(off)
#endif
  if (!MetaBrowserPortableFft()) return std::abs(value);
  const double a = std::abs(value.real());
  const double b = std::abs(value.imag());
  // Match hypot's classification: infinity wins over NaN. Scale before
  // squaring to avoid overflowing or underflowing otherwise valid norms.
  if (std::isinf(a) || std::isinf(b))
    return std::numeric_limits<double>::infinity();
  if (std::isnan(a) || std::isnan(b))
    return std::numeric_limits<double>::quiet_NaN();
  const double high = std::max(a, b);
  const double low = std::min(a, b);
  if (high == 0) return 0;
  const double ratio = low / high;
  // IEEE double square root is correctly rounded on the supported targets;
  // the separate products/addition above may not be contracted or reassociated.
  return high * std::sqrt(1.0 + ratio * ratio);
}

double MetaBrowserFftPhase(const std::complex<double>& value) {
  return MetaBrowserPortableFft() ? fdlibm::atan2(value.imag(), value.real())
                                : std::arg(value);
}

std::complex<double> MetaBrowserFftPolar(double magnitude, double phase) {
  // Preserve upstream exceptional-domain semantics. HRTF resource spectra and
  // ordinary finite kernel interpolation take the explicit fdlibm path.
  if (!MetaBrowserPortableFft() || !std::isfinite(magnitude) ||
      !std::isfinite(phase) || std::signbit(magnitude))
    return std::polar(magnitude, phase);
  return {magnitude * fdlibm::cos(phase), magnitude * fdlibm::sin(phase)};
}
