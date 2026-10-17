const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const core = b.addModule("metabrowser-core", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .name = "metabrowser-native-contract", .root_module = core });
    const catalog_check = b.addSystemCommand(&.{ "python3", "scripts/generate-browser-catalog.py", "--check" });
    tests.step.dependOn(&catalog_check.step);
    b.default_step.dependOn(&tests.step);
    const run = b.addRunArtifact(tests);
    b.step("test", "Verify native action binding and consent lifecycle").dependOn(&run.step);
    if (b.option([]const u8, "agentcore-sdk", "Complete validated AgentCore SDK directory")) |sdk| {
        if (target.result.os.tag != .macos or target.result.cpu.arch != .aarch64)
            @panic("AgentCore integration probe currently requires macOS ARM64");
        const types = b.createModule(.{ .root_source_file = .{ .cwd_relative = b.pathJoin(&.{ sdk, "bindings/zig/src/types.zig" }) }, .target = target, .optimize = optimize });
        const protocol = b.createModule(.{ .root_source_file = .{ .cwd_relative = b.pathJoin(&.{ sdk, "bindings/zig/src/protocol.zig" }) }, .target = target, .optimize = optimize });
        const mc = b.createModule(.{ .root_source_file = .{ .cwd_relative = b.pathJoin(&.{ sdk, "bindings/zig/src/root.zig" }) }, .target = target, .optimize = optimize });
        mc.addImport("metask_agentcore_types", types);
        mc.addImport("metask_agentcore_protocol", protocol);
        const plugin_mod = b.createModule(.{ .root_source_file = b.path("src/metacodes_plugin.zig"), .target = target, .optimize = optimize, .link_libc = true });
        plugin_mod.addImport("metask_agentcore", mc);
        plugin_mod.addIncludePath(.{ .cwd_relative = b.pathJoin(&.{ sdk, "include" }) });
        const mac_sdk = b.option([]const u8, "mac-sdk", "Apple macOS SDK path") orelse std.mem.trim(u8, b.run(&.{ "xcrun", "--sdk", "macosx", "--show-sdk-path" }), "\r\n");
        plugin_mod.addSystemIncludePath(.{ .cwd_relative = b.pathJoin(&.{ mac_sdk, "usr/include" }) });
        plugin_mod.addLibraryPath(.{ .cwd_relative = b.pathJoin(&.{ mac_sdk, "usr/lib" }) });
        plugin_mod.addFrameworkPath(.{ .cwd_relative = b.pathJoin(&.{ mac_sdk, "System/Library/Frameworks" }) });
        plugin_mod.addCSourceFile(.{ .file = b.path("src/mcp_transport.c"), .flags = &.{"-std=c11"} });
        plugin_mod.addCSourceFile(.{ .file = b.path("src/account_native.m"), .flags = &.{ "-fobjc-arc", "-fblocks" } });
        plugin_mod.linkFramework("Foundation", .{});
        plugin_mod.linkFramework("Security", .{});
        plugin_mod.linkSystemLibrary("curl", .{ .use_pkg_config = .no });
        plugin_mod.addLibraryPath(.{ .cwd_relative = b.pathJoin(&.{ sdk, "lib" }) });
        plugin_mod.addRPathSpecial("@loader_path/../Resources/agentcore/lib");
        plugin_mod.addRPath(.{ .cwd_relative = b.pathJoin(&.{ sdk, "lib" }) });
        plugin_mod.linkSystemLibrary("metask_agentcore", .{ .use_pkg_config = .no });
        const plugin = b.addLibrary(.{ .name = "metabrowser_metacodes", .linkage = .dynamic, .root_module = plugin_mod });
        const install_plugin = b.addInstallArtifact(plugin, .{});
        const validate_plugin = b.addSystemCommand(&.{ "python3", "scripts/check-agentcore-bundle.py", sdk });
        plugin.step.dependOn(&validate_plugin.step);
        plugin.step.dependOn(&catalog_check.step);
        b.step("agentcore:plugin", "Build the native MetaCodes sidebar adapter").dependOn(&install_plugin.step);
        const probe = b.createModule(.{ .root_source_file = b.path("src/agentcore_smoke.zig"), .target = target, .optimize = optimize, .link_libc = true });
        probe.addImport("metask_agentcore", mc);
        probe.addLibraryPath(.{ .cwd_relative = b.pathJoin(&.{ sdk, "lib" }) });
        probe.addRPath(.{ .cwd_relative = b.pathJoin(&.{ sdk, "lib" }) });
        probe.addLibraryPath(b.path("out/macos-arm64"));
        probe.addRPath(b.path("out/macos-arm64"));
        probe.linkSystemLibrary("metask_agentcore", .{ .use_pkg_config = .no });
        probe.linkSystemLibrary("metabrowser-runtime-host", .{ .use_pkg_config = .no });
        const exe = b.addExecutable(.{ .name = "metabrowser-agentcore-probe", .root_module = probe });
        const run_probe = b.addRunArtifact(exe);
        run_probe.has_side_effects = true;
        const check = b.addSystemCommand(&.{ "python3", "scripts/check-agentcore-bundle.py", sdk });
        exe.step.dependOn(&check.step);
        b.step("agentcore:probe", "Validate complete SDK and initialize native MetaCodes without network").dependOn(&run_probe.step);
    }
}
