const abi = @import("runtime_abi.zig");
var cancelled: bool = false;
var released: bool = false;
fn begin(_: ?*anyopaque, _: u64, _: ?[*]const u8, _: u64, _: abi.EventFn, _: ?*anyopaque) callconv(.c) void {}
fn cancel(_: ?*anyopaque, run: u64) callconv(.c) void {
    if (run == 42) cancelled = true;
}
fn release(_: ?*anyopaque) callconv(.c) void {
    released = true;
}
pub fn main() !void {
    const host: abi.RuntimeHost = .{ .context = null, .begin = begin, .cancel = cancel, .release = release };
    if (abi.mb_register_runtime(&host) != 1) return error.RegistrationFailed;
    defer abi.mb_shutdown_runtime();
    abi.mb_cancel_runtime(42);
    if (!cancelled) return error.CancelCallbackMissing;
    abi.mb_shutdown_runtime();
    if (!released) return error.ReleaseCallbackMissing;
}
