// MetaBrowser side panel (Chromium native side-panel container).
// Multi-session chat with the embedded metacodes agent, approvals, browser activity feed.
// Talks only to the local daemon; config.json (port + token) is baked in by `metabrowser serve`.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { cfg: null, sessions: [], current: null, logs: {}, lastText: {}, seen: {}, busy: {} };

async function config() {
  if (!state.cfg) state.cfg = await (await fetch(chrome.runtime.getURL("config.json"))).json();
  return state.cfg;
}
async function api(path, body, method) {
  const { port, token } = await config();
  const res = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${path}: ${res.status}`);
  return data;
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

// ---- sessions ---------------------------------------------------------------------------
function renderTabs() {
  const nav = $("sessions");
  nav.replaceChildren();
  for (const s of state.sessions) {
    const b = el("button", "", s.label);
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(s.id === state.current));
    if (state.busy[s.id]) b.append(el("span", "dot"));
    b.onclick = () => select(s.id);
    nav.append(b);
  }
}
const logFor = (sid) => (state.logs[sid] ||= el("div"));
function upsertSession(id, label) {
  // Live SSE events can announce a session before the create call returns: never add it twice.
  const found = state.sessions.find((s) => s.id === id);
  if (found) { if (label) found.label = label; return found; }
  const s = { id, label: label || id };
  state.sessions.push(s);
  return s;
}
function select(sid) {
  state.current = sid;
  $("log").replaceChildren(logFor(sid));
  renderTabs();
  $("log").scrollTop = $("log").scrollHeight;
}
function append(sid, node) {
  logFor(sid).append(node);
  if (sid === state.current) $("log").scrollTop = $("log").scrollHeight;
}
async function loadHistory(sid) {
  const items = await api(`/api/agent/sessions/${sid}/history?since=${state.seen[sid] || 0}`);
  for (const { seq, event } of items) onAgentEvent(sid, seq, event);
}
async function newSession() {
  const s = await api("/api/agent/sessions", {});
  upsertSession(s.id, s.label);
  select(s.id);
  $("input").focus();
}

function onAgentEvent(sid, seq, ev) {
  if (seq <= (state.seen[sid] || 0)) return; // de-duplicate history vs live stream
  state.seen[sid] = seq;
  upsertSession(sid, (ev.session_created || {}).label);
  if ("user_message" in ev) {
    state.lastText[sid] = null; state.busy[sid] = true;
    append(sid, el("div", "msg user", ev.user_message));
  } else if ("run_done" in ev) {
    state.lastText[sid] = null; state.busy[sid] = false;
    const d = ev.run_done;
    append(sid, el("div", "msg done", `— ${d.stop_reason} · ${d.turns} turns · ${d.tool_calls} tools · ${(d.elapsed_ms / 1000).toFixed(1)}s${d.diagnostic ? " · " + d.diagnostic : ""}`));
  } else if ("core_event" in ev) {
    const c = ev.core_event;
    if (typeof c.text_chunk === "string") {
      if (!state.lastText[sid]) { state.lastText[sid] = el("div", "msg"); append(sid, state.lastText[sid]); }
      state.lastText[sid].textContent += c.text_chunk;
    } else if (c.tool_start) {
      state.lastText[sid] = null;
      append(sid, el("div", "tool", `▸ ${c.tool_start.name} ${String(c.tool_start.input).slice(0, 160)}`));
    } else if (c.tool_result && c.tool_result.is_error) {
      append(sid, el("div", "tool error", `✗ ${c.tool_result.name}: ${String(c.tool_result.content).slice(0, 240)}`));
    }
  }
  renderTabs();
}

// ---- approvals: AgentCore permission / questions, and browser risk gate -------------------------
function card(cls, title, detail) {
  const box = el("div", `approval ${cls || ""}`);
  box.append(el("div", "risk", title));
  if (detail) box.append(el("pre", "", detail));
  return box;
}
function onAgentRequest(msg) {
  const r = msg.request;
  const label = (state.sessions.find((s) => s.id === msg.session) || { label: msg.session }).label;
  const row = el("div", "row");
  let box;
  if (r.type === "permission") {
    box = card("", `${label} · ${r.tool.name}`, String(r.arguments_json).slice(0, 1200));
    // Revision 17: the candidate scope says what a session answer covers.
    const cand = r.candidate || {};
    const base = cand.target ? cand.target.split("/").pop() : "";
    const reach = cand.scope === "file_target" ? ` (any ${r.tool.name} of ${base})` : " (this exact call)";
    if (cand.scope === "file_target") box.append(el("div", "", `Session answer covers every ${r.tool.name} to ${cand.target}`));
    const names = { allow_once: "Allow once", allow_session: "Allow for session" + reach, deny_once: "Deny", deny_session: "Deny for session" + reach };
    for (const c of r.responses || ["allow_once", "deny_once"]) {
      const b = el("button", "", names[c] || c);
      b.onclick = () => api(`/api/agent/requests/${msg.id}`, { choice: c }).finally(() => box.remove());
      row.append(b);
    }
  } else {
    const questions = r.ask_question || [];
    box = card("", `${label} · question`);
    const answers = questions.map(() => []);
    questions.forEach((q, i) => {
      box.append(el("div", "", q.question));
      for (const o of q.options || []) {
        const b = el("button", "", o.label);
        b.onclick = () => { answers[i] = [o.label]; if (!q.multi) b.parentElement.querySelectorAll("button").forEach((x) => x.disabled = x !== b); };
        box.append(b);
      }
    });
    const send = el("button", "", "Answer");
    send.onclick = () => api(`/api/agent/requests/${msg.id}`, { answers: answers.map((v) => ({ values: v })) }).finally(() => box.remove());
    row.append(send);
  }
  box.dataset.request = msg.id;
  box.append(row);
  $("approvals").prepend(box);
}
function onBrowserApproval(msg) {
  const r = msg.request;
  const box = card(r.risk, `${r.risk} · ${r.tool} · ${r.session}`, `${r.reason || ""}\n${r.url || ""}\n${JSON.stringify(r.args)}`);
  box.dataset.approval = msg.id;
  const row = el("div", "row");
  const choices = [["allow_once", "Allow once"], ["deny", "Deny"]];
  if (r.risk !== "irreversible") choices.splice(1, 0, ["allow_session", "Allow for session"]);
  for (const [c, t] of choices) {
    const b = el("button", "", t);
    b.onclick = () => api(`/api/approvals/${msg.id}`, { answer: c }).finally(() => box.remove());
    row.append(b);
  }
  box.append(row);
  $("approvals").prepend(box);
}

function onDaemonEvent(msg) {
  switch (msg.kind) {
    case "agent_event": return onAgentEvent(msg.session, msg.seq, msg.event);
    case "agent_request": return onAgentRequest(msg);
    case "agent_request_done": return document.querySelector(`[data-request="${msg.id}"]`)?.remove();
    case "approval": return onBrowserApproval(msg);
    case "approval_done": return document.querySelector(`[data-approval="${msg.id}"]`)?.remove();
    case "trace": {
      const e = msg.event;
      if (e.type !== "tool_call") return;
      const li = el("li", e.ok ? "" : "fail", `${e.session} ${e.tool} [${e.risk}] ${e.ok ? "" : (e.error || {}).code || ""} ${e.duration_ms}ms`);
      $("activity-list").prepend(li);
      while ($("activity-list").children.length > 200) $("activity-list").lastChild.remove();
      $("activity-count").textContent = String(Number($("activity-count").textContent) + 1);
    }
  }
}

// ---- composer -----------------------------------------------------------------------------
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text) return;
  try {
    if (!state.current) await newSession();
    $("input").value = "";
    await api(`/api/agent/sessions/${state.current}/message`, { text });
  } catch (err) { append(state.current || "_", el("div", "tool error", String(err))); }
});
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
});
$("stop").onclick = () => state.current && api(`/api/agent/sessions/${state.current}/interrupt`, {});
$("new-session").onclick = () => newSession().catch((err) => showBanner(String(err)));

function showBanner(text) { $("banner").hidden = !text; $("banner").textContent = text || ""; }

// ---- boot ---------------------------------------------------------------------------------
(async function boot() {
  try {
    const { port, token } = await config();
    const es = new EventSource(`http://127.0.0.1:${port}/api/events?token=${encodeURIComponent(token)}`);
    es.onmessage = (e) => { try { onDaemonEvent(JSON.parse(e.data)); } catch (_) { /* keepalive */ } };
    es.onopen = () => { $("status").textContent = "connected"; };
    es.onerror = () => { $("status").textContent = "reconnecting…"; };
    const status = await api("/api/agent/status");
    if (!status.enabled || status.error) showBanner(`Agent: ${status.error}`);
    if (status.enabled) {
      for (const s of await api("/api/agent/sessions")) upsertSession(s.id, s.label);
      for (const s of state.sessions) await loadHistory(s.id);
      if (!state.sessions.length) await newSession();
      else select(state.sessions[0].id);
    }
  } catch (err) {
    $("status").textContent = "daemon unreachable";
    showBanner(String(err));
  }
})();
