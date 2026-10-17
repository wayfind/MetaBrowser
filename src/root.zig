//! Native browser admission contract. This module has no browser executor,
//! model provider, CDP client or browser process launcher.
pub const authorization = @import("authorization.zig");

pub const runtime_abi = @import("runtime_abi.zig");

test {
    _ = authorization;
    _ = runtime_abi;
}
