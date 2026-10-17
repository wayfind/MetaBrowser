// Executed only for the immutable scalar persona. Keep the native platform
// implementation below unchanged. Double history is shared across coefficient
// automation transitions, rather than Accelerate's private history layout.
if (MetaBrowserPortableBiquadProcess()) {
#pragma clang fp contract(off)
#pragma clang fp reassociate(off)
  double x1 = x1_, x2 = x2_, y1 = y1_, y2 = y2_;
  const bool varying = HasSampleAccurateValues();
  for (size_t k = 0; k < frames_to_process; ++k) {
    const size_t coefficient = varying ? k : 0;
    const double x = source[k];
    const double y = b0_[coefficient] * x + b1_[coefficient] * x1 +
                     b2_[coefficient] * x2 - a1_[coefficient] * y1 -
                     a2_[coefficient] * y2;
    dest[k] = static_cast<float>(y);
    x2 = x1;
    x1 = x;
    y2 = y1;
    y1 = y;
  }
  // The native helper takes float: using it here would silently round the
  // recursive double history at every render-quantum boundary.
  const auto flush = [](double value) {
    return std::abs(value) < std::numeric_limits<double>::min()
               ? std::copysign(0.0, value) : value;
  };
  x1_ = flush(x1);
  x2_ = flush(x2);
  y1_ = flush(y1);
  y2_ = flush(y2);
  return;
}
