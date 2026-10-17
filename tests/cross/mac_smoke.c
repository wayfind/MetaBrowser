#include <stdio.h>
#include <CoreFoundation/CoreFoundation.h>
int main(void) {
  CFStringRef text = CFSTR("MetaBrowser macOS ARM64 cross-toolchain");
  char buffer[128];
  if (!CFStringGetCString(text, buffer, sizeof(buffer), kCFStringEncodingUTF8)) return 1;
  puts(buffer);
  return 0;
}
