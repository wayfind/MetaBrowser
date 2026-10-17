//! Native, offline integration readiness probe; never calls a model provider.
const std = @import("std");
const mc = @import("metask_agentcore");
const browser = @import("runtime_abi.zig");
pub fn main() !void {
    const api = try mc.Api.discover(); // Checks revision, all mandatory tables and slots.
    var runtime: ?*mc.types.RuntimeHandle = null;
    var config = std.mem.zeroes(mc.types.RuntimeConfigV1);
    config.struct_size = @sizeOf(mc.types.RuntimeConfigV1);
    if (api.runtime().create()(&config, null, &runtime, null) != 0 or runtime == null)
        return error.AgentCoreInitializationFailed;
    defer {
        if (api.runtime().destroy()(runtime, null) != 0)
            @panic("AgentCore runtime did not release");
    }
    var invalid: browser.RuntimeHost = undefined;
    invalid.struct_size = 0;
    invalid.abi = 0;
    if (browser.mb_register_runtime(&invalid) != 0)
        return error.BrowserAcceptedInvalidHost;
    std.debug.print("MetaCodes ABI 21 native runtime + browser bridge: PASS\n", .{});
}
