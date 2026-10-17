//! Feasibility proof, NOT the replacement daemon: own Chromium with a private
//! CDP pipe, create/attach a target and read its AX tree. No Python or Node.
const std = @import("std");
const c = @cImport({
    @cInclude("unistd.h");
    @cInclude("fcntl.h");
    @cInclude("spawn.h");
    @cInclude("poll.h");
    @cInclude("signal.h");
    @cInclude("sys/wait.h");
    @cInclude("time.h");
});
const Allocator = std.mem.Allocator;
const max_message = 8 * 1024 * 1024;

const Frames = struct {
    allocator: Allocator,
    bytes: std.ArrayList(u8) = .empty,

    fn deinit(self: *Frames) void {
        self.bytes.deinit(self.allocator);
    }
    fn append(self: *Frames, bytes: []const u8) !void {
        if (self.bytes.items.len + bytes.len > max_message) return error.MessageTooLarge;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
    fn take(self: *Frames) !?[]u8 {
        const end = std.mem.indexOfScalar(u8, self.bytes.items, 0) orelse return null;
        const owned = try self.allocator.dupe(u8, self.bytes.items[0..end]);
        const rest = self.bytes.items[end + 1 ..];
        std.mem.copyForwards(u8, self.bytes.items, rest);
        self.bytes.items.len = rest.len;
        return owned;
    }
};

fn milliseconds() !i64 {
    var ts: c.struct_timespec = undefined;
    if (c.clock_gettime(c.CLOCK_MONOTONIC, &ts) != 0) return error.ClockFailed;
    return @as(i64, @intCast(ts.tv_sec)) * 1000 + @divTrunc(@as(i64, @intCast(ts.tv_nsec)), 1000000);
}
fn ready(fd: c_int, events: c_short, deadline: i64) !void {
    const left = deadline - try milliseconds();
    if (left <= 0) return error.Timeout;
    var pollfd = c.struct_pollfd{ .fd = fd, .events = events, .revents = 0 };
    const result = c.poll(&pollfd, 1, @intCast(@min(left, std.math.maxInt(c_int))));
    if (result == 0) return error.Timeout;
    if (result < 0) return error.PollFailed;
    if (pollfd.revents & events == 0) return error.PipeClosed;
}

const Pipe = struct {
    allocator: Allocator,
    pid: c.pid_t,
    input: c_int,
    output: c_int,
    frames: Frames,
    next_id: u32 = 1,

    fn spawn(allocator: Allocator, args: []const []const u8) !Pipe {
        var original: [4]c_int = undefined;
        if (c.pipe(original[0..2].ptr) != 0) return error.PipeFailed;
        defer for (original[0..2]) |fd| {
            _ = c.close(fd);
        };
        if (c.pipe(original[2..4].ptr) != 0) return error.PipeFailed;
        defer for (original[2..4]) |fd| {
            _ = c.close(fd);
        };
        // Keep originals above fd 4, so dup2 cannot clobber another pipe end.
        var fds: [4]c_int = .{ -1, -1, -1, -1 };
        var transferred = false;
        defer for (fds, 0..) |fd, i| {
            if (fd >= 0 and (!transferred or i == 0 or i == 3)) _ = c.close(fd);
        };
        for (original, 0..) |fd, i| {
            fds[i] = c.fcntl(fd, c.F_DUPFD_CLOEXEC, @as(c_int, 10));
            if (fds[i] < 0) return error.PipeFailed;
        }
        var actions: c.posix_spawn_file_actions_t = undefined;
        if (c.posix_spawn_file_actions_init(&actions) != 0) return error.SpawnFailed;
        defer _ = c.posix_spawn_file_actions_destroy(&actions);
        if (c.posix_spawn_file_actions_adddup2(&actions, fds[0], 3) != 0 or
            c.posix_spawn_file_actions_adddup2(&actions, fds[3], 4) != 0) return error.SpawnFailed;
        for (fds) |fd| if (c.posix_spawn_file_actions_addclose(&actions, fd) != 0) return error.SpawnFailed;
        for (original) |fd| {
            if (fd != 3 and fd != 4 and c.posix_spawn_file_actions_addclose(&actions, fd) != 0) return error.SpawnFailed;
        }
        if (c.posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", c.O_WRONLY, 0) != 0 or
            c.posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", c.O_WRONLY, 0) != 0) return error.SpawnFailed;
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();
        const scratch = arena.allocator();
        const argv = try scratch.allocSentinel(?[*:0]u8, args.len, null);
        for (args, 0..) |arg, i| argv[i] = (try scratch.dupeZ(u8, arg)).ptr;
        var pid: c.pid_t = undefined;
        if (c.posix_spawn(&pid, argv[0].?, &actions, null, @ptrCast(argv.ptr), @ptrCast(std.c.environ)) != 0) return error.SpawnFailed;
        transferred = true;
        return .{ .allocator = allocator, .pid = pid, .input = fds[1], .output = fds[2], .frames = .{ .allocator = allocator } };
    }

    fn deinit(self: *Pipe) void {
        _ = c.close(self.input);
        _ = c.close(self.output);
        self.frames.deinit();
        // Browser.close is attempted by the caller. Always reap the owned child,
        // escalating only after a bounded grace period, never touching other browsers.
        var status: c_int = 0;
        var n: usize = 0;
        while (n < 40) : (n += 1) {
            if (c.waitpid(self.pid, &status, c.WNOHANG) != 0) return;
            _ = c.usleep(50000);
        }
        _ = c.kill(self.pid, c.SIGKILL);
        _ = c.waitpid(self.pid, &status, 0);
    }

    fn call(self: *Pipe, method: []const u8, params: anytype, session: ?[]const u8) !std.json.Parsed(std.json.Value) {
        const id = self.next_id;
        self.next_id += 1;
        const message = try std.json.Stringify.valueAlloc(self.allocator, .{
            .id = id,
            .method = method,
            .params = params,
            .sessionId = session,
        }, .{ .emit_null_optional_fields = false });
        defer self.allocator.free(message);
        const framed = try std.mem.concat(self.allocator, u8, &.{ message, "\x00" });
        defer self.allocator.free(framed);
        const deadline = (try milliseconds()) + 15000;
        var written: usize = 0;
        while (written < framed.len) {
            try ready(self.input, c.POLLOUT, deadline);
            const n = c.write(self.input, framed.ptr + written, framed.len - written);
            if (n <= 0) return error.PipeClosed;
            written += @intCast(n);
        }
        while (true) {
            while (try self.frames.take()) |frame| {
                defer self.allocator.free(frame);
                const parsed = try std.json.parseFromSlice(std.json.Value, self.allocator, frame, .{ .allocate = .alloc_always });
                const response_id = if (parsed.value == .object) parsed.value.object.get("id") else null;
                if (response_id != null and response_id.? == .integer and response_id.?.integer == id) {
                    if (parsed.value.object.contains("error")) {
                        std.debug.print("CDP {s} failed: {s}\n", .{ method, frame });
                        parsed.deinit();
                        return error.CdpRejected;
                    }
                    return parsed;
                }
                parsed.deinit(); // Proof issues sequential calls; production must queue events.
            }
            try ready(self.output, c.POLLIN, deadline);
            var buf: [16384]u8 = undefined;
            const n = c.read(self.output, &buf, buf.len);
            if (n <= 0) return error.PipeClosed;
            try self.frames.append(buf[0..@intCast(n)]);
        }
    }
};

fn ignoreSignal(_: c_int) callconv(.c) void {}

pub fn main(init: std.process.Init) !void {
    const arena = init.arena.allocator();
    const argv = try init.minimal.args.toSlice(arena);
    if (argv.len != 3) {
        std.debug.print("usage: metabrowser-cdp-proof /absolute/path/to/chromium /temporary/profile\n", .{});
        return error.InvalidArguments;
    }
    if (!std.fs.path.isAbsolute(argv[1]) or !std.fs.path.isAbsolute(argv[2])) return error.AbsolutePathsRequired;
    try std.Io.Dir.cwd().createDirPath(init.io, argv[2]);
    const profile_arg = try std.fmt.allocPrint(arena, "--user-data-dir={s}", .{argv[2]});
    // A real callback avoids platform-specific SIG_IGN function-pointer macros.
    _ = c.signal(c.SIGPIPE, ignoreSignal);
    var pipe = try Pipe.spawn(init.gpa, &.{ argv[1], profile_arg, "--remote-debugging-pipe", "--headless=new", "--no-first-run", "--no-default-browser-check", "--site-per-process", "about:blank" });
    defer pipe.deinit();
    const version = try pipe.call("Browser.getVersion", struct {}{}, null);
    defer version.deinit();
    const result = version.value.object.get("result").?;
    std.debug.print("browser: {s}\n", .{result.object.get("product").?.string});
    const target = try pipe.call("Target.createTarget", .{ .url = "data:text/html,<title>Zig CDP proof</title><h1>MetaBrowser Zig CDP</h1><button>Continue</button>" }, null);
    defer target.deinit();
    const target_id = target.value.object.get("result").?.object.get("targetId").?.string;
    const attached = try pipe.call("Target.attachToTarget", .{ .targetId = target_id, .flatten = true }, null);
    defer attached.deinit();
    const session = attached.value.object.get("result").?.object.get("sessionId").?.string;
    var found = false;
    var attempt: usize = 0;
    while (!found and attempt < 30) : (attempt += 1) {
        const tree = try pipe.call("Accessibility.getFullAXTree", struct {}{}, session);
        defer tree.deinit();
        for (tree.value.object.get("result").?.object.get("nodes").?.array.items) |node| {
            const name = node.object.get("name") orelse continue;
            const value = name.object.get("value") orelse continue;
            if (value == .string and std.mem.eql(u8, value.string, "MetaBrowser Zig CDP")) {
                found = true;
                break;
            }
        }
        if (!found) _ = c.usleep(100000);
    }
    if (!found) return error.AccessibilityProofFailed;
    std.debug.print("PASS: Zig -> CDP pipe -> target session -> real accessibility tree; no Python/Node\n", .{});
    if (pipe.call("Browser.close", struct {}{}, null)) |closed| closed.deinit() else |_| {}
}

test "partial and multiple null-delimited CDP messages" {
    var frames = Frames{ .allocator = std.testing.allocator };
    defer frames.deinit();
    try frames.append("{\"id\":");
    try std.testing.expectEqual(null, try frames.take());
    try frames.append("1}\x00{\"id\":2}\x00rest");
    const a = (try frames.take()).?;
    defer std.testing.allocator.free(a);
    const b = (try frames.take()).?;
    defer std.testing.allocator.free(b);
    try std.testing.expectEqualStrings("{\"id\":1}", a);
    try std.testing.expectEqualStrings("{\"id\":2}", b);
    try std.testing.expectEqual(null, try frames.take());
    try std.testing.expectEqualStrings("rest", frames.bytes.items);
}

test "oversized peer message is rejected" {
    var frames = Frames{ .allocator = std.testing.allocator };
    defer frames.deinit();
    const big = try std.testing.allocator.alloc(u8, max_message + 1);
    defer std.testing.allocator.free(big);
    try std.testing.expectError(error.MessageTooLarge, frames.append(big));
}
