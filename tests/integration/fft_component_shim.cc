#include "third_party/blink/renderer/platform/audio/metabrowser_fft_math.h"
extern "C" double mb_fft_sin(double x) {return blink::rust_fft::metabrowser_fft_sin(x);}
extern "C" double mb_fft_cos(double x) {return blink::rust_fft::metabrowser_fft_cos(x);}
