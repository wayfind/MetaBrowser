const std = @import("std");
const mc = @import("metask_agentcore");
const t = mc.types;
const allocator = std.heap.c_allocator;
const c = @cImport({
    @cInclude("stdlib.h");
});
extern fn mb_mcp_definition(?[*]const ?[*:0]const u8, ?[*:0]const u8, ?[*:0]const u8) ?*anyopaque;
extern fn mb_mcp_definition_release(?*anyopaque) void;
extern fn mb_mcp_connector(?*anyopaque, *t.McpConnectorV1) void;
// Transport discards notifications, but never mistakes one for a request result.
pub export fn mb_mcp_matches(frame: [*]const u8, frame_len: usize, request: [*]const u8, request_len: usize) c_int {
    var reply = std.json.parseFromSlice(std.json.Value, allocator, frame[0..frame_len], .{}) catch return -1;
    defer reply.deinit();
    var query = std.json.parseFromSlice(std.json.Value, allocator, request[0..request_len], .{}) catch return -1;
    defer query.deinit();
    if (reply.value != .object or query.value != .object) return -1;
    const rid = reply.value.object.get("id") orelse return 0;
    const qid = query.value.object.get("id") orelse return 0;
    if (reply.value.object.get("result") == null and reply.value.object.get("error") == null) return 0;
    return if (switch (rid) {
        .integer => |v| qid == .integer and v == qid.integer,
        .string => |v| qid == .string and std.mem.eql(u8, v, qid.string),
        else => false,
    }) 1 else 0;
}
pub fn configure(api: mc.Api, runtime: ?*t.RuntimeHandle, session: ?*t.SessionHandle, input: []const u8, out: *?[*]u8, len: *u64) u32 {
    const Server = struct { name: []const u8, command: ?[]const u8 = null, args: []const []const u8 = &.{}, url: ?[]const u8 = null, token_env: ?[]const u8 = null, tools: []const []const u8 = &.{} };
    const Configuration = struct { revision: u64, servers: []const Server };
    var parsed = std.json.parseFromSlice(Configuration, allocator, input, .{}) catch return 1;
    defer parsed.deinit();
    if (parsed.value.servers.len > t.MAX_MCP_SERVERS_V1) return 1;
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const servers = a.alloc(t.McpServerV1, parsed.value.servers.len) catch return 2;
    var definitions: std.ArrayList(*anyopaque) = .empty;
    defer {
        for (definitions.items) |d| mb_mcp_definition_release(d);
        definitions.deinit(allocator);
    }
    var selectors: std.ArrayList(t.McpSelectorV1) = .empty;
    defer selectors.deinit(allocator);
    for (parsed.value.servers, 0..) |server, i| {
        if ((server.command == null) == (server.url == null)) return 1;
        var argv: ?[*]const ?[*:0]const u8 = null;
        if (server.command) |command| {
            const values = a.alloc(?[*:0]const u8, server.args.len + 2) catch return 2;
            values[0] = a.dupeZ(u8, command) catch return 2;
            for (server.args, 0..) |arg, j| values[j + 1] = a.dupeZ(u8, arg) catch return 2;
            values[values.len - 1] = null;
            argv = values.ptr;
        }
        var url: ?[:0]const u8 = null;
        var authorization: ?[:0]const u8 = null;
        if (server.url) |u| {
            if (!std.mem.startsWith(u8, u, "https://") and !std.mem.startsWith(u8, u, "http://127.0.0.1:")) return 1;
            url = a.dupeZ(u8, u) catch return 2;
        }
        if (server.token_env) |env| {
            const key = a.dupeZ(u8, env) catch return 2;
            const value = c.getenv(key) orelse return 1;
            const secret = std.mem.span(value);
            if (std.mem.indexOfAny(u8, secret, "\r\n") != null) return 1;
            authorization = std.fmt.allocPrintSentinel(a, "Authorization: Bearer {s}", .{secret}, 0) catch return 2;
        }
        const definition = mb_mcp_definition(argv, if (url) |u| u.ptr else null, if (authorization) |v| v.ptr else null) orelse return 2;
        definitions.append(allocator, definition) catch {
            mb_mcp_definition_release(definition);
            return 2;
        };
        servers[i] = std.mem.zeroes(t.McpServerV1);
        const s = &servers[i];
        s.struct_size = @sizeOf(t.McpServerV1);
        s.transport_code = if (url != null) t.MCP_TRANSPORT_STREAMABLE_HTTP else t.MCP_TRANSPORT_STDIO;
        s.negotiation_policy_code = t.MCP_NEGOTIATION_AUTO;
        std.crypto.hash.sha2.Sha256.hash(server.name, &s.server_binding_identity, .{});
        const public = std.json.Stringify.valueAlloc(a, server, .{}) catch return 2;
        std.crypto.hash.sha2.Sha256.hash(public, &s.configuration_fingerprint, .{});
        s.namespace = mc.bytesView(server.name);
        s.client_name = mc.bytesView("metabrowser");
        s.client_version = mc.bytesView("0.1");
        s.timeout_ms = 15000;
        mb_mcp_connector(definition, &s.connector);
        for (server.tools) |name| {
            var selector = std.mem.zeroes(t.McpSelectorV1);
            selector.struct_size = @sizeOf(t.McpSelectorV1);
            selector.server_binding_identity = s.server_binding_identity;
            selector.tool_name = mc.bytesView(name);
            selectors.append(allocator, selector) catch return 2;
        }
    }
    var diag = std.mem.zeroes(t.OwnedBytesV1);
    defer if (diag.ptr) |bytes| {
        if (out.* == null) {
            const memory = c.malloc(@intCast(diag.len));
            if (memory) |m| {
                const p: [*]u8 = @ptrCast(m);
                @memcpy(p[0..@intCast(diag.len)], bytes[0..@intCast(diag.len)]);
                out.* = p;
                len.* = diag.len;
            }
        }
    };
    var configuration = std.mem.zeroes(t.McpConfigurationV1);
    configuration.struct_size = @sizeOf(t.McpConfigurationV1);
    configuration.desired_revision = parsed.value.revision;
    configuration.servers = servers.ptr;
    configuration.server_count = servers.len;
    var report = std.mem.zeroes(t.McpApplyReportV1);
    report.struct_size = @sizeOf(t.McpApplyReportV1);
    var status = api.mcp().applyConfiguration()(runtime, &configuration, &report, &diag);
    if (status != 0) return status;
    var generation: u64 = 0;
    status = api.mcp().refresh()(runtime, &generation, &diag);
    if (status != 0) return status;
    var selection = std.mem.zeroes(t.McpSelectionV1);
    selection.struct_size = @sizeOf(t.McpSelectionV1);
    selection.selectors = selectors.items.ptr;
    selection.selector_count = selectors.items.len;
    status = api.mcp().updateSelection()(session, &selection, &diag);
    if (status != 0) return status;
    var catalog = std.mem.zeroes(t.OwnedBytesV1);
    defer api.bufferRelease()(&catalog);
    status = api.mcp().describe()(runtime, &catalog, &diag);
    if (status != 0) return status;
    const memory = c.malloc(@max(catalog.len, 1)) orelse return 2;
    const p: [*]u8 = @ptrCast(memory);
    if (catalog.ptr) |source| @memcpy(p[0..@intCast(catalog.len)], source[0..@intCast(catalog.len)]);
    out.* = p;
    len.* = catalog.len;
    return 0;
}
