//! ABI for the in-process MetaCodes host. All calls use the browser UI sequence.
//! Registration does not grant page access or skip native approval checks.
pub const abi_version: u32 = 1;
pub const EventFn = *const fn (?*anyopaque, u64, ?[*]const u8, u64) callconv(.c) void;
pub const RuntimeHost = extern struct {
    struct_size: u32 = @sizeOf(RuntimeHost),
    abi: u32 = abi_version,
    context: ?*anyopaque,
    begin: *const fn (?*anyopaque, u64, ?[*]const u8, u64, EventFn, ?*anyopaque) callconv(.c) void,
    cancel: *const fn (?*anyopaque, u64) callconv(.c) void,
    release: *const fn (?*anyopaque) callconv(.c) void,
};
pub extern fn mb_register_runtime(host: *const RuntimeHost) c_int;
pub extern fn mb_begin_runtime(run_id: u64, bytes: ?[*]const u8, length: u64, callback: EventFn, callback_context: ?*anyopaque) c_int;
pub extern fn mb_cancel_runtime(run_id: u64) void;
pub extern fn mb_shutdown_runtime() void;

test "host ABI has expected 64-bit layout" {
    const std = @import("std");
    if (@sizeOf(usize) != 8) return error.SkipZigTest;
    try std.testing.expectEqual(@as(usize, 40), @sizeOf(RuntimeHost));
    try std.testing.expectEqual(@as(usize, 8), @offsetOf(RuntimeHost, "context"));
}
