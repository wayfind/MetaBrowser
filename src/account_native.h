#include <stdint.h>
typedef void (*MBAccountEvent)(void*, uint32_t, const uint8_t*, uint64_t);
uint32_t mb_account_operation(const char*, uint32_t, MBAccountEvent, void*);
void mb_account_cancel(void);
