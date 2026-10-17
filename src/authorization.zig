const std = @import("std");

pub const SessionId = enum(u64) { _ };
pub const RunId = enum(u64) { _ };
pub const TabId = enum(u64) { _ };
pub const FrameId = enum(u64) { _ };
pub const RequestId = enum(u64) { _ };
pub const DocumentGeneration = enum(u64) { _ };
pub const SnapshotGeneration = enum(u64) { _ };

pub const ObservationBinding = struct {
    tab: TabId,
    frame: FrameId,
    document: DocumentGeneration,
    snapshot: SnapshotGeneration,

    fn same(a: ObservationBinding, b: ObservationBinding) bool {
        return a.tab == b.tab and a.frame == b.frame and a.document == b.document and a.snapshot == b.snapshot;
    }
};

pub const Command = union(enum) {
    click: u64, // Native snapshot-scoped element reference, not a renderer pointer.
    type_text: struct { element: u64, text: []const u8 },
    select_option: struct { element: u64, value: []const u8 },
    scroll: struct { x: i32, y: i32 },
};

pub const Action = struct {
    request: RequestId,
    session: SessionId,
    run: RunId,
    binding: ObservationBinding,
    command: Command,
};

/// Risk is supplied by native browser inspection, never by the agent Action.
pub const NativeRisk = enum { input, submit, irreversible, forbidden };
pub const NativeInspection = struct {
    binding: ObservationBinding,
    risk: NativeRisk,
};

pub const Reject = enum {
    stale_observation,
    wrong_session,
    wrong_run,
    forbidden,
    busy,
    stopped,
    no_pending_approval,
    mismatched_approval,
    denied,
};

/// Permit is admission evidence only. An executor still rechecks the native
/// document on its own sequence before applying an action.
pub const Permit = struct { action: Action, binding: ObservationBinding };
pub const Decision = union(enum) {
    permitted: Permit,
    consent_required: RequestId,
    rejected: Reject,
};

/// One sequential Run action lane. Different Runs/frames use distinct owners;
/// the eventual Chromium adapter owns synchronization and callback lifetimes.
pub const Gate = struct {
    session: SessionId,
    run: RunId,
    current: ObservationBinding,
    state: union(enum) { ready, awaiting_consent: Action, stopped } = .ready,

    pub fn prepare(self: *Gate, action: Action, inspection: NativeInspection) Decision {
        switch (self.state) {
            .stopped => return .{ .rejected = .stopped },
            .awaiting_consent => return .{ .rejected = .busy },
            .ready => {},
        }
        if (action.session != self.session) return .{ .rejected = .wrong_session };
        if (action.run != self.run) return .{ .rejected = .wrong_run };
        if (!self.current.same(action.binding) or !self.current.same(inspection.binding))
            return .{ .rejected = .stale_observation };
        switch (inspection.risk) {
            .forbidden => return .{ .rejected = .forbidden },
            .input => return .{ .permitted = .{ .action = action, .binding = self.current } },
            .submit, .irreversible => {
                self.state = .{ .awaiting_consent = action };
                return .{ .consent_required = action.request };
            },
        }
    }

    /// Called only from browser-owned consent UI. The request/run/binding must
    /// match, and consuming the approval clears it before returning a permit.
    pub fn answer(self: *Gate, request: RequestId, run: RunId, allow: bool) Decision {
        const action = switch (self.state) {
            .stopped => return .{ .rejected = .stopped },
            .ready => return .{ .rejected = .no_pending_approval },
            .awaiting_consent => |action| action,
        };
        if (request != action.request or run != action.run) return .{ .rejected = .mismatched_approval };
        self.state = .ready;
        if (!action.binding.same(self.current)) return .{ .rejected = .stale_observation };
        if (!allow) return .{ .rejected = .denied };
        return .{ .permitted = .{ .action = action, .binding = self.current } };
    }

    pub fn observe(self: *Gate, binding: ObservationBinding) void {
        // Keep a pending action so that a delayed UI response returns stale,
        // rather than silently granting the new document an old approval.
        self.current = binding;
    }

    pub fn stop(self: *Gate) void {
        self.state = .stopped;
    }

    pub fn validAtExecution(self: *const Gate, permit: Permit, actual: ObservationBinding) bool {
        return self.state != .stopped and permit.action.session == self.session and
            permit.action.run == self.run and self.current.same(permit.binding) and actual.same(permit.binding);
    }
};

fn fixture() struct { gate: Gate, action: Action } {
    const binding = ObservationBinding{ .tab = @enumFromInt(1), .frame = @enumFromInt(2), .document = @enumFromInt(3), .snapshot = @enumFromInt(4) };
    const action = Action{ .request = @enumFromInt(10), .session = @enumFromInt(20), .run = @enumFromInt(30), .binding = binding, .command = .{ .click = 40 } };
    return .{ .gate = .{ .session = action.session, .run = action.run, .current = binding }, .action = action };
}

test "native inspection decides risk; irreversible action waits for exact consent" {
    var f = fixture();
    const decision = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .irreversible });
    try std.testing.expect(decision == .consent_required);
    try std.testing.expectEqual(f.action.request, decision.consent_required);
    try std.testing.expectEqual(Reject.mismatched_approval, f.gate.answer(@enumFromInt(99), f.action.run, true).rejected);
    const permitted = f.gate.answer(f.action.request, f.action.run, true).permitted;
    try std.testing.expect(f.gate.validAtExecution(permitted, f.action.binding));
    try std.testing.expectEqual(Reject.no_pending_approval, f.gate.answer(f.action.request, f.action.run, true).rejected);
}

test "navigation makes old target references and late consent stale" {
    var f = fixture();
    _ = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .submit });
    var next = f.action.binding;
    next.document = @enumFromInt(5);
    f.gate.observe(next);
    try std.testing.expectEqual(Reject.stale_observation, f.gate.answer(f.action.request, f.action.run, true).rejected);
    try std.testing.expectEqual(Reject.stale_observation, f.gate.prepare(f.action, .{ .binding = next, .risk = .input }).rejected);
}

test "stop revokes late approvals and preflight permits" {
    var f = fixture();
    const permit = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .input }).permitted;
    _ = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .irreversible });
    f.gate.stop();
    try std.testing.expectEqual(Reject.stopped, f.gate.answer(f.action.request, f.action.run, true).rejected);
    try std.testing.expect(!f.gate.validAtExecution(permit, f.action.binding));
}

test "native execution rechecks frame and snapshot after preflight" {
    var f = fixture();
    const permit = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .input }).permitted;
    var actual = f.action.binding;
    actual.frame = @enumFromInt(99);
    try std.testing.expect(!f.gate.validAtExecution(permit, actual));
    actual = f.action.binding;
    actual.snapshot = @enumFromInt(99);
    try std.testing.expect(!f.gate.validAtExecution(permit, actual));
}

test "session/run ownership, denial and unsupported risk do not produce a permit" {
    var f = fixture();
    var action = f.action;
    action.session = @enumFromInt(99);
    try std.testing.expectEqual(Reject.wrong_session, f.gate.prepare(action, .{ .binding = action.binding, .risk = .input }).rejected);
    action = f.action;
    action.run = @enumFromInt(99);
    try std.testing.expectEqual(Reject.wrong_run, f.gate.prepare(action, .{ .binding = action.binding, .risk = .input }).rejected);
    try std.testing.expectEqual(Reject.forbidden, f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .forbidden }).rejected);
    _ = f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .submit });
    try std.testing.expectEqual(Reject.busy, f.gate.prepare(f.action, .{ .binding = f.action.binding, .risk = .input }).rejected);
    try std.testing.expectEqual(Reject.denied, f.gate.answer(f.action.request, f.action.run, false).rejected);
}
