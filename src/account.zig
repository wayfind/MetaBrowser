//! Native desktop OAuth; account bearers never enter the SDK or transcript.
const Event = *const fn (?*anyopaque, u32, ?[*]const u8, u64) callconv(.c) void;
extern fn mb_account_operation([*:0]const u8, u32, Event, ?*anyopaque) u32;
extern fn mb_account_cancel() void;
pub export fn mb_mc_login_available() u32 {
    return 1;
}
pub export fn mb_mc_login_cancel() void {
    mb_account_cancel();
}
pub export fn mb_mc_login(root: [*:0]const u8, event: Event, context: ?*anyopaque) u32 {
    return mb_account_operation(root, 0, event, context);
}
/// 0 PKCE login; 1 restore; 2 logout; 3 explicit device fallback.
pub export fn mb_mc_account(root: [*:0]const u8, operation: u32, event: Event, context: ?*anyopaque) u32 {
    return mb_account_operation(root, operation, event, context);
}
