const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    if (target.result.os.tag != .macos and target.result.os.tag != .linux)
        @panic("CDP pipe proof currently supports macOS/Linux; Windows handle transport is a separate milestone");
    const mod = b.createModule(.{ .root_source_file = b.path("src/main.zig"), .target = target, .optimize = optimize, .link_libc = true });
    const exe = b.addExecutable(.{ .name = "metabrowser-cdp-proof", .root_module = mod });
    b.installArtifact(exe);
    const run = b.addRunArtifact(exe);
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Prove Zig can own Chromium CDP without Python/Node").dependOn(&run.step);
    const tests = b.addTest(.{ .root_module = mod });
    b.step("test", "Test the bounded null-delimited transport").dependOn(&b.addRunArtifact(tests).step);
}
