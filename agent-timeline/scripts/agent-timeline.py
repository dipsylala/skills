#!/usr/bin/env python3
"""Show the subagents a Claude Code session spawned, as a timeline you can drill into.

Usage:
  agent-timeline.py [TARGET] [-o OUT.html] [--open]   write a snapshot page
  agent-timeline.py [TARGET] --serve [--port N]       serve a live page on 127.0.0.1

TARGET is one of:
  - a session transcript (.jsonl)
  - a session id, or a unique prefix of one
  - a project folder: its most recent session is used
With no TARGET, the session in CLAUDE_CODE_SESSION_ID is used (Claude Code sets it for
commands Claude runs), otherwise the current directory's most recent session.

Each agent is shown as Running (activity in the last 2 minutes), Quiet (no activity
for 2-10 minutes), Stalled (unfinished and silent for longer), or Done. Hook events
are marked on the rows: every Stop hook run, and any hook output on other events.

It only reads what Claude Code already records, so it works with any agent setup
and changes nothing about how agents run.

Reads ~/.claude/projects/<project>/<session>.jsonl and <session>/subagents/.
Set CLAUDE_CONFIG_DIR if your Claude config is not in ~/.claude.

The transcript format is not a documented Claude Code interface, so an update
to Claude Code can break this script.
"""

import argparse
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
SPAWN_TOOLS = {"Agent", "Task"}
HANDBACK_TOOL = "SubagentHandback"
IDLE_GAP = 600        # seconds without a transcript entry that split activity into separate bars
RUNNING_WINDOW = 120  # seconds since the last entry for an unfinished agent to count as running
STALL_AFTER = 600     # seconds of silence after which an unfinished agent counts as stalled
RESULT_LINE = re.compile(r"^\s*(STATUS|VERDICT):", re.M)
STAGE = re.compile(r"^\s*(?:S|Stage\s*)(\d+)\b", re.I)
HOOK_KINDS = ["ran", "context", "message", "cancelled", "error", "blocked"]  # least to most severe
BRIEF_KEYS = ("command", "file_path", "path", "pattern", "url", "description", "query", "title", "message", "prompt")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def epoch(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return ""


def brief(tool_input):
    """One line saying what a tool call did, e.g. the command or the file it touched."""
    for key in BRIEF_KEYS:
        value = (tool_input or {}).get(key)
        if isinstance(value, str) and value.strip():
            line = value.strip().splitlines()[0]
            return re.sub(r"^cd\s+\S+\s*&&\s*", "", line)[:160]
    return ""


def hook_record(entry, t):
    """(key, record) for a transcript entry about a hook, or None.

    Claude Code logs a summary for every Stop hook run, and an attachment whenever a hook
    on any event produced output. Hooks that print nothing on other events leave no trace.
    """
    if entry.get("type") == "system" and entry.get("subtype") == "stop_hook_summary":
        commands = [h for h in entry.get("hookInfos") or [] if h.get("command") != "callback"]
        if not commands:
            return None  # only Claude Code's internal callbacks ran
        errors = [str(e) for e in entry.get("hookErrors") or []]
        kind = "blocked" if entry.get("preventedContinuation") else "error" if errors else "ran"
        texts = errors + ([entry["stopReason"]] if entry.get("stopReason") else [])
        return (entry.get("toolUseID") or entry.get("uuid"), "Stop"), {
            "t": t, "event": "Stop", "kind": kind, "texts": texts,
            "hook": ", ".join(h["command"] for h in commands),
            "ms": max((h.get("durationMs") or 0 for h in commands), default=0)}
    attachment = entry.get("attachment") or {}
    kind = str(attachment.get("type", ""))
    if not kind.startswith("hook_"):
        return None
    kind = kind.removeprefix("hook_")
    text = ""
    if kind == "blocking_error":
        kind, error = "blocked", attachment.get("blockingError")
        text = error.get("blockingError", "") if isinstance(error, dict) else str(error or "")
    elif kind == "additional_context":
        content = attachment.get("content")
        kind, text = "context", "\n\n".join(content) if isinstance(content, list) else str(content or "")
    elif kind == "system_message":
        kind, text = "message", str(attachment.get("content") or "")
    elif kind == "success":
        kind, text = "ran", str(attachment.get("stdout") or attachment.get("content") or "")
        try:
            message = json.loads(text).get("systemMessage")
            kind, text = ("message", message) if message else (kind, text)
        except (ValueError, AttributeError):
            pass
    elif kind == "cancelled":
        text = "timed out" if attachment.get("timedOut") else ""
    elif "error" in kind:
        kind, text = "error", str(attachment.get("content") or attachment.get("stderr") or "")
    event = attachment.get("hookEvent") or attachment.get("hookName") or "?"
    return (attachment.get("toolUseID") or entry.get("uuid"), event), {
        "t": t, "event": event, "kind": kind if kind in HOOK_KINDS else "ran",
        "texts": [text] if text else [], "hook": attachment.get("command") or "",
        "ms": attachment.get("durationMs") or 0}


def merge_hook(hooks, key, record):
    """One record per hook firing: keep the most severe outcome and every message."""
    current = hooks.get(key)
    if not current:
        hooks[key] = record
        return
    if HOOK_KINDS.index(record["kind"]) > HOOK_KINDS.index(current["kind"]):
        current["kind"] = record["kind"]
    current["texts"] += [x for x in record["texts"] if x not in current["texts"]]
    current["hook"] = current["hook"] or record["hook"]
    current["ms"] = max(current["ms"], record["ms"])
    current["t"] = min(current["t"], record["t"])


def resolve(target):
    current = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not target and re.fullmatch(r"[0-9a-fA-F-]+", current):
        hits = list(PROJECTS.glob(f"*/{current}.jsonl"))
        if len(hits) == 1:
            return hits[0]
    path = Path(target) if target else Path.cwd()
    if path.is_file() and path.suffix == ".jsonl":
        return path
    if path.is_dir():
        project = PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))
        sessions = sorted(project.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        if not sessions:
            sys.exit(f"agent-timeline: no sessions in {project}")
        return sessions[-1]
    hits = sorted(PROJECTS.glob(f"*/{target}*.jsonl"))
    if len(hits) != 1:
        sys.exit(f"agent-timeline: {len(hits)} sessions match {target!r}")
    return hits[0]


def summarise_uncached(path):
    """Active periods, models, token use, tool calls, recent activity and final reply of one transcript."""
    times = []
    models, tools, usage = set(), {}, {}
    prompt = final = ""
    ended = False
    activity = deque(maxlen=30)
    chapters, spawns, launched, hooks = [], {}, {}, {}
    for entry in read_jsonl(path):
        stamp = entry.get("timestamp")
        t = epoch(stamp) if stamp else None
        if t is not None:
            times.append(t)
            hook = hook_record(entry, t)
            if hook:
                merge_hook(hooks, *hook)
        message = entry.get("message") or {}
        content = message.get("content")
        if entry.get("type") == "user" and not prompt:
            prompt = text_of(content)
        launch = entry.get("toolUseResult")
        if isinstance(launch, dict) and launch.get("agentId") and isinstance(content, list):
            tool_use_id = next((b.get("tool_use_id") for b in content if b.get("type") == "tool_result"), None)
            launched.setdefault(launch["agentId"], {"tool_use_id": tool_use_id,
                                                    "description": launch.get("description"),
                                                    "model": launch.get("resolvedModel")})
        if entry.get("type") != "assistant":
            continue
        model = message.get("model") or ""
        if model and not model.startswith("<"):
            models.add(model)
        # Streaming writes one entry per content block, repeating the message's usage.
        if message.get("usage"):
            usage[message.get("id") or id(entry)] = message["usage"]
        ended = message.get("stop_reason") == "end_turn"
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "text" and block["text"].strip():
                final = block["text"].strip()
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                tool_input = block.get("input") or {}
                tools[name] = tools.get(name, 0) + 1
                if t is not None:
                    activity.append([t, name, brief(tool_input)])
                if name == HANDBACK_TOOL:
                    final, ended = str(tool_input.get("message", "")).strip(), True
                elif name.endswith("mark_chapter") and t is not None:
                    chapters.append({"t": t, "title": tool_input.get("title", "")})
                elif name in SPAWN_TOOLS:
                    spawns[block.get("id")] = {"t": t, "input": tool_input}
    segments = []
    for t in sorted(times):
        if segments and t - segments[-1][1] <= IDLE_GAP:
            segments[-1][1] = t
        else:
            segments.append([t, t])
    match = RESULT_LINE.search(final)
    result = final[match.start():].splitlines()[0].strip() if match else final.splitlines()[0][:160] if final else ""
    return {
        "start": segments[0][0] if segments else None, "end": segments[-1][1] if segments else None,
        "segments": segments, "active": sum(b - a for a, b in segments),
        "models": sorted(models), "tools": tools,
        "tokens_in": sum(u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0) for u in usage.values()),
        "tokens_out": sum(u.get("output_tokens", 0) for u in usage.values()),
        "prompt": prompt[:3000], "final": final[:4000], "result": result, "ended": ended,
        "activity": list(activity), "chapters": chapters, "spawns": spawns, "launched": launched,
        "hooks": [{**h, "texts": [x[:3000] for x in h["texts"]]} for h in sorted(hooks.values(), key=lambda h: h["t"])][-300:],
    }


_cache = {}


def summarise(path):
    """summarise_uncached, re-read only when the file has changed (the live page polls)."""
    stat = path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(path)
    if not cached or cached[0] != key:
        info = summarise_uncached(path)
        info["mtime"] = stat.st_mtime
        _cache[path] = cached = (key, info)
    return cached[1]


def status_of(info, meta, meta_mtime, now):
    finished = meta.get("finished") is True if "finished" in meta else info["ended"]
    if finished and meta_mtime and info["mtime"] > meta_mtime + 5:
        finished = False  # resumed after it last finished
    age = now - info["end"]
    if finished:
        return "done"
    return "running" if age <= RUNNING_WINDOW else "quiet" if age <= STALL_AFTER else "stalled"


def group_of(description, start, chapters):
    stage = STAGE.match(description)
    if stage:
        return f"Stage {int(stage.group(1))}"
    titles = [c["title"] for c in chapters if c["t"] <= start]
    return titles[-1] if titles else "Agents"


def collect(session):
    now = time.time()
    main = summarise(session)
    agents = []
    for transcript in sorted((session.parent / session.stem / "subagents").glob("agent-*.jsonl")):
        info = summarise(transcript)
        if info["start"] is None:
            continue
        meta_path = transcript.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        agent_id = transcript.stem.removeprefix("agent-")
        launch = main["launched"].get(agent_id, {})
        spawn_input = main["spawns"].get(meta.get("toolUseId") or launch.get("tool_use_id"), {}).get("input", {})
        description = (meta.get("description") or launch.get("description")
                       or spawn_input.get("description") or transcript.stem)
        agents.append({
            "id": agent_id,
            "description": description,
            "group": group_of(description, info["start"], main["chapters"]),
            "status": status_of(info, meta, meta_path.stat().st_mtime if meta else None, now),
            "type": meta.get("agentType") or spawn_input.get("subagent_type") or "",
            "model": ", ".join(info["models"]) or meta.get("pickedEffortModel") or launch.get("model") or "",
            "background": meta.get("requestShape") == "background" or bool(spawn_input.get("run_in_background")),
            "depth": meta.get("spawnDepth", 1),
            "transcript": str(transcript),
            **{k: info[k] for k in ("start", "end", "segments", "active", "tools", "tokens_in",
                                    "tokens_out", "prompt", "final", "result", "activity", "hooks")},
        })
    agents.sort(key=lambda a: a["start"])
    return {
        "now": now,
        "session": session.stem,
        "project": session.parent.name,
        "main": {"running": now - main["end"] <= RUNNING_WINDOW, "transcript": str(session),
                 **{k: main[k] for k in ("start", "end", "segments", "active", "models", "tokens_in", "tokens_out",
                                         "tools", "prompt", "final", "activity", "hooks")}},
        "chapters": main["chapters"],
        "agents": agents,
    }


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent timeline</title>
<style>
:root { --bg:#fbfaf8; --fg:#1d1d1b; --muted:#6b6a66; --line:#e6e4df; --card:#ffffff; --hover:#f3f1ec;
  --main:#a3a19b; --run:#2563eb; --quiet:#7c3aed; --stall:#d97706; --done:#15803d; --chapter:#b91c1c; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#181816; --fg:#ecebe7;
  --muted:#a09e98; --line:#34332f; --card:#211f1d; --hover:#2a2826; --main:#6f6d68; --run:#6ea1f2;
  --quiet:#b294f7; --stall:#f0b85a; --done:#4ccf7f; --chapter:#f87171; } }
:root[data-theme="dark"] { --bg:#181816; --fg:#ecebe7; --muted:#a09e98; --line:#34332f; --card:#211f1d;
  --hover:#2a2826; --main:#6f6d68; --run:#6ea1f2; --quiet:#b294f7; --stall:#f0b85a; --done:#4ccf7f; --chapter:#f87171; }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--fg);
  font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1280px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 2px; }
.sub { color:var(--muted); margin:0 0 12px; word-break:break-all; font-size:12px; }
.stats { display:flex; flex-wrap:wrap; gap:6px 22px; margin:0 0 14px; }
.stats b { font-variant-numeric:tabular-nums; }
.live { font-size:12px; color:var(--muted); }
.live .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--run); margin-right:6px; animation:pulse 1.6s infinite; }
.live.off .dot { background:var(--stall); animation:none; }
@keyframes pulse { 50% { opacity:.3; } }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 10px; }
.chip { border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:999px; padding:3px 10px; font:inherit; font-size:13px; cursor:pointer; }
.chip[aria-pressed="false"] { opacity:.45; }
.chip .n { font-variant-numeric:tabular-nums; color:var(--muted); margin-left:4px; }
input[type=search], select { font:inherit; font-size:13px; padding:4px 8px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); }
input[type=search] { flex:1 1 180px; max-width:280px; }
.list { background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.row { display:grid; grid-template-columns:22px minmax(140px, 26%) 1fr 84px; gap:8px; align-items:center; padding:0 10px; min-height:30px; }
.axis { position:sticky; top:0; z-index:2; background:var(--card); border-bottom:1px solid var(--line); height:26px; }
.group { font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; padding:10px 10px 4px; border-top:1px solid var(--line); }
.group:first-of-type { border-top:0; }
.agent { cursor:pointer; border-top:1px solid transparent; }
.agent:hover, .agent:focus-visible, .agent.hl { background:var(--hover); outline:none; }
.agent[aria-expanded="true"] { background:var(--hover); }
.badge { font-size:13px; text-align:center; }
.name { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:13px; }
.name small { color:var(--muted); margin-left:6px; }
.track { position:relative; height:30px; }
.tick { position:absolute; top:0; bottom:0; border-left:1px dashed var(--line); }
.axis .tick { border-left:0; font-size:11px; color:var(--muted); padding-top:6px; white-space:nowrap; transform:translateX(-50%); }
.nowline { position:absolute; top:0; bottom:0; border-left:2px solid var(--run); opacity:.5; }
.chapter { position:absolute; top:0; bottom:0; border-left:2px solid var(--chapter); opacity:.5; }
.bar { position:absolute; top:9px; height:12px; border-radius:3px; min-width:3px; }
.bar.running { background-image:repeating-linear-gradient(45deg, transparent 0 5px, rgba(255,255,255,.35) 5px 10px); background-size:14px 14px; animation:slide 1s linear infinite; }
@keyframes slide { to { background-position:14px 0; } }
.num { text-align:right; font-variant-numeric:tabular-nums; font-size:12px; color:var(--muted); white-space:nowrap; }
.s-running { color:var(--run); } .s-quiet { color:var(--quiet); } .s-stalled { color:var(--stall); } .s-done { color:var(--done); }
.b-running { background-color:var(--run); } .b-quiet { background-color:var(--quiet); } .b-stalled { background-color:var(--stall); } .b-done { background-color:var(--done); } .b-main { background-color:var(--main); }
.hook { position:absolute; top:2px; width:7px; height:7px; margin-left:-3px; transform:rotate(45deg); border-radius:1px; z-index:1; }
.k-blocked, .k-error { background:var(--chapter); } .k-message, .k-context { background:var(--stall); }
.k-cancelled { background:var(--muted); } .k-ran { background:var(--muted); opacity:.45; }
.tk-blocked, .tk-error { color:var(--chapter); } .tk-message, .tk-context { color:var(--stall); } .tk-cancelled, .tk-ran { color:var(--muted); }
.hooks { list-style:none; margin:0; padding:0; font-size:12px; max-height:280px; overflow:auto; }
.hooks li { padding:3px 0; border-bottom:1px dotted var(--line); }
.hooks .head { display:grid; grid-template-columns:62px 130px 80px 1fr auto; gap:8px; }
.hooks .head span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hooks details { margin:2px 0 0 70px; }
.hookbox { margin-top:14px; }
.detail { padding:10px 14px 16px 40px; border-bottom:1px solid var(--line); background:var(--hover); }
.cols { display:grid; grid-template-columns:minmax(0, 1.1fr) minmax(0, 1fr); gap:20px; }
@media (max-width:760px) { .cols { grid-template-columns:1fr; } .row { grid-template-columns:22px minmax(110px, 38%) 1fr 64px; } .detail { padding-left:14px; } }
.detail h3 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 6px; }
.feed { list-style:none; margin:0; padding:0; font-size:12px; max-height:320px; overflow:auto; }
.feed li { display:grid; grid-template-columns:62px 110px 1fr; gap:8px; padding:2px 0; border-bottom:1px dotted var(--line); }
.feed .t { color:var(--muted); font-variant-numeric:tabular-nums; }
.feed .tool { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.feed .what { font-family:ui-monospace, Consolas, monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
pre { white-space:pre-wrap; word-break:break-word; font-size:12px; margin:0 0 10px; max-height:260px; overflow:auto; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:8px; }
dl { display:grid; grid-template-columns:auto 1fr; gap:2px 12px; font-size:12px; margin:0 0 10px; }
dt { color:var(--muted); } dd { margin:0; word-break:break-all; }
details summary { cursor:pointer; color:var(--muted); font-size:12px; margin-bottom:6px; }
.empty { padding:16px; color:var(--muted); }
</style>
</head>
<body>
<main>
<h1>Agent timeline</h1>
<p class="sub" id="sub"></p>
<div class="stats" id="stats"></div>
<div class="controls">
  <span id="chips"></span>
  <input type="search" id="q" placeholder="Filter agents" aria-label="Filter agents">
  <select id="range" aria-label="Time range">
    <option value="fit">Fit to agents</option>
    <option value="session">Whole session</option>
    <option value="recent">Last 30 minutes</option>
  </select>
  <span class="live" id="live"></span>
</div>
<div class="list" id="list"></div>
</main>
<script>
const LIVE = __LIVE__;
let DATA = __DATA__;
const STATUS = {running: ["Running", "●"], quiet: ["Quiet", "◐"], stalled: ["Stalled", "⚠"], done: ["Done", "✓"]};
const state = {open: new Set(), details: new Set(), hide: new Set(), hooks: true, q: "", range: "fit"};
const statusOf = a => STATUS[a.status] || ["Idle", "·"];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const dur = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`; };
const kt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
const clock = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});

function segmentsOf(a) {
  // A running agent is still working: draw its last bar up to now.
  return a.status === "running" ? a.segments.map((s, i, all) => i === all.length - 1 ? [s[0], Math.max(s[1], DATA.now)] : s) : a.segments;
}

function range() {
  const agents = DATA.agents, m = DATA.main;
  const liveEnd = m.running ? Math.max(m.end, DATA.now) : m.end;
  let lo, hi;
  if (state.range === "recent") { hi = Math.max(liveEnd, DATA.now); lo = hi - 1800; }
  else if (state.range === "session" || !agents.length) { lo = m.start; hi = liveEnd; }
  else { lo = Math.min(...agents.map(a => a.start)); hi = Math.max(...agents.map(a => segmentsOf(a).at(-1)[1])); }
  const pad = Math.max((hi - lo) * 0.02, 5);
  return [lo - pad, hi + pad];
}

function render() {
  const [lo, hi] = range();
  const x = t => Math.min(100, Math.max(0, (t - lo) / (hi - lo) * 100));
  const bar = (s, e, cls) => e < lo || s > hi ? "" :
    `<div class="bar ${cls}" style="left:${x(s)}%;width:${Math.max(0, x(e) - x(s))}%"></div>`;
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400, 172800, 604800];
  const step = steps.find(s => (hi - lo) / s <= 7) || 1209600;
  const label = t => step >= 86400 ? new Date(t * 1000).toLocaleDateString([], {month: "short", day: "numeric"})
    : hi - lo > 86400 ? new Date(t * 1000).toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"})
    : new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", ...(step < 60 ? {second: "2-digit"} : {})});
  const tickTimes = [];
  for (let t = Math.ceil(lo / step) * step; t < hi; t += step) tickTimes.push(t);
  const grid = tickTimes.map(t => `<div class="tick" style="left:${x(t)}%"></div>`).join("")
    + DATA.chapters.filter(c => c.t > lo && c.t < hi).map(c => `<div class="chapter" style="left:${x(c.t)}%" title="${esc(c.title)}"></div>`).join("")
    + (LIVE && DATA.now < hi ? `<div class="nowline" style="left:${x(DATA.now)}%" title="now"></div>` : "");

  const counts = {running: 0, quiet: 0, stalled: 0, done: 0};
  DATA.agents.forEach(a => counts[a.status]++);
  const allHooks = [DATA.main, ...DATA.agents].flatMap(a => a.hooks);
  $("chips").innerHTML = Object.entries(STATUS).map(([k, [name, icon]]) =>
    `<button class="chip" data-status="${k}" aria-pressed="${!state.hide.has(k)}"><span class="s-${k}">${icon}</span> ${name}<span class="n">${counts[k]}</span></button>`).join(" ")
    + ` <button class="chip" data-hooks aria-pressed="${state.hooks}" title="Show hook events on the timeline"><span class="tk-message">◆</span> Hooks<span class="n">${allHooks.length}</span></button>`;
  const markers = a => !state.hooks ? "" : a.hooks.filter(h => h.t >= lo && h.t <= hi).map(h =>
    `<div class="hook k-${h.kind}" style="left:${x(h.t)}%" title="${esc(`${clock(h.t)} · ${h.event} · ${h.kind}${h.hook ? " · " + h.hook : ""}${h.texts[0] ? "\n" + h.texts[0].slice(0, 240) : ""}`)}"></div>`).join("");

  const q = state.q.toLowerCase();
  const shown = DATA.agents.filter(a => !state.hide.has(a.status) &&
    (!q || [a.description, a.type, a.model, a.result, a.group].join(" ").toLowerCase().includes(q)));
  const groups = [];
  shown.forEach(a => { let g = groups.find(g => g.name === a.group); if (!g) groups.push(g = {name: a.group, agents: []}); g.agents.push(a); });

  const m = DATA.main;
  const mainRow = {...m, id: "main", description: "Main session", status: m.running ? "running" : "idle",
    type: "main session", model: m.models.join(", "), depth: 1, background: false};
  const mainOpen = state.open.has("main");
  let html = `<div class="row axis"><span></span><span class="name" style="color:var(--muted);font-size:12px">${shown.length} of ${DATA.agents.length} agents</span>
      <div class="track">${tickTimes.map(t => `<div class="tick" style="left:${x(t)}%">${label(t)}</div>`).join("")}</div><span class="num">active</span></div>
    <div class="row agent" data-id="main" tabindex="0" role="button" aria-expanded="${mainOpen}">
      <span class="badge s-${mainRow.status}" title="${m.running ? "Main session active" : "Main session idle"}">${statusOf(mainRow)[1]}</span>
      <span class="name">Main session<small>${esc(mainRow.model.replace(/^claude-/, ""))}</small></span>
      <div class="track">${grid}${segmentsOf(mainRow).map(([s, e]) => bar(s, e, "b-main")).join("")}${markers(m)}</div>
      <span class="num">${dur(m.active)}</span></div>${mainOpen ? detail(mainRow) : ""}`;
  if (!DATA.agents.length) html += `<div class="empty">No subagents in this session yet.</div>`;
  else if (!shown.length) html += `<div class="empty">No agents match the filters.</div>`;
  for (const g of groups) {
    html += `<div class="group">${esc(g.name)}</div>`;
    for (const a of g.agents) {
      const open = state.open.has(a.id);
      html += `<div class="row agent" data-id="${a.id}" tabindex="0" role="button" aria-expanded="${open}">
        <span class="badge s-${a.status}" title="${STATUS[a.status][0]}">${STATUS[a.status][1]}</span>
        <span class="name" title="${esc(a.description)}">${"&nbsp;&nbsp;".repeat(Math.max(0, a.depth - 1))}${esc(a.description)}<small>${esc(a.model.replace(/^claude-/, ""))}</small></span>
        <div class="track">${grid}${segmentsOf(a).map(([s, e]) => bar(s, e, `b-${a.status}${a.status === "running" ? " running" : ""}`)).join("")}${markers(a)}</div>
        <span class="num">${dur(a.active)}</span></div>`;
      if (open) html += detail(a);
    }
  }
  const scrolls = new Map([...$("list").querySelectorAll("[data-scroll]")].map(el => [el.dataset.scroll, el.scrollTop]));
  $("list").innerHTML = html;
  for (const d of $("list").querySelectorAll("details[data-key]")) d.open = state.details.has(d.dataset.key);
  balance();
  for (const el of $("list").querySelectorAll("[data-scroll]")) el.scrollTop = scrolls.get(el.dataset.scroll) || 0;

  const agentSecs = DATA.agents.reduce((s, a) => s + a.active, 0);
  $("sub").textContent = `${DATA.project} / ${DATA.session}`;
  $("stats").innerHTML = [
    ["Session", `${dur(m.active)} active over ${dur((m.running ? DATA.now : m.end) - m.start)}`],
    ["Agents", DATA.agents.length],
    ["Agent time", dur(agentSecs)],
    ["Agent output tokens", kt(DATA.agents.reduce((s, a) => s + a.tokens_out, 0))],
    ["Main output tokens", kt(m.tokens_out)],
    ["Hooks", `${allHooks.length} · ${allHooks.filter(h => h.kind === "blocked").length} blocked`],
  ].map(([k, v]) => `<span>${k}: <b>${v}</b></span>`).join("");
}

// The two detail columns share a grid row, so both are as tall as the taller one.
// Give each column's scroll box (activity feed, reply) the slack, so neither leaves empty space.
function balance() {
  const pairs = [...$("list").querySelectorAll(".cols")].flatMap(cols => [...cols.children].map(section =>
    [section, section.querySelector(":scope > .feed, :scope > pre")]).filter(([, box]) => box));
  for (const [, box] of pairs) { box.style.height = ""; box.style.maxHeight = ""; }
  for (const [section, box] of pairs) {
    const used = [...section.children].reduce((h, el) => { const s = getComputedStyle(el);
      return h + el.offsetHeight + parseFloat(s.marginTop) + parseFloat(s.marginBottom); }, 0);
    const slack = section.clientHeight - used;
    if (slack > 1) { const height = box.offsetHeight + slack; box.style.maxHeight = "none"; box.style.height = `${height}px`; }
  }
}
window.addEventListener("resize", balance);

function detail(a) {
  const feed = a.activity.slice().reverse().map(([t, tool, what]) =>
    `<li><span class="t">${clock(t)}</span><span class="tool" title="${esc(tool)}">${esc(tool.replace(/^mcp__.*?__/, ""))}</span><span class="what" title="${esc(what)}">${esc(what)}</span></li>`).join("");
  const tools = Object.entries(a.tools).sort((p, q) => q[1] - p[1]).map(([k, v]) => `${k} ${v}`).join(", ");
  const hooks = a.hooks.slice().reverse().map((h, i) => `<li><div class="head"><span class="t">${clock(h.t)}</span>
      <span title="${esc(h.event)}">${esc(h.event)}</span><span class="tk-${h.kind}">${esc(h.kind)}</span>
      <span title="${esc(h.hook)}">${esc(h.hook)}</span><span class="t">${h.ms ? dur(h.ms / 1000) : ""}</span></div>
      ${h.texts.length ? `<details data-key="hook-${a.id}-${h.t}-${i}"><summary>${esc(h.texts[0].split("\n")[0].slice(0, 120))}</summary><pre>${esc(h.texts.join("\n\n"))}</pre></details>` : ""}</li>`).join("");
  return `<div class="detail"><div class="cols">
    <section><h3>Latest activity</h3>${feed ? `<ol class="feed" data-scroll="feed-${a.id}">${feed}</ol>` : `<p class="empty">No tool calls yet.</p>`}</section>
    <section><h3>${a.status === "done" ? "Result" : "Latest reply"}</h3>${a.final ? `<pre data-scroll="final-${a.id}">${esc(a.final)}</pre>` : `<p class="empty">Nothing yet.</p>`}
      <dl><dt>Status</dt><dd class="s-${a.status}">${statusOf(a)[0]} · last activity ${clock(a.end)}</dd>
        <dt>Agent</dt><dd>${esc(a.type)}${a.background ? " · background" : ""} · ${esc(a.model)}</dd>
        <dt>Started</dt><dd>${clock(a.start)} · ${dur(a.active)} active${a.segments.length > 1 ? ` in ${a.segments.length} parts` : ""}</dd>
        <dt title="Input includes cached context re-read on each turn">Tokens</dt><dd>${kt(a.tokens_in)} in / ${kt(a.tokens_out)} out</dd>
        <dt>Tools</dt><dd>${esc(tools)}</dd>
        <dt>Transcript</dt><dd>${esc(a.transcript)}</dd></dl>
      <details data-key="prompt-${a.id}"><summary>${a.id === "main" ? "First prompt" : "Prompt"}</summary><pre data-scroll="prompt-${a.id}">${esc(a.prompt)}</pre></details></section>
  </div>
  <section class="hookbox"><h3>Hooks (${a.hooks.length})</h3>${hooks ? `<ol class="hooks" data-scroll="hooks-${a.id}">${hooks}</ol>` : `<p class="empty">No hook events recorded.</p>`}</section></div>`;
}

function toggle(row) {
  const id = row.dataset.id;
  state.open.has(id) ? state.open.delete(id) : state.open.add(id);
  render();
}
$("list").addEventListener("click", e => { const row = e.target.closest(".agent"); if (row) toggle(row); });
$("list").addEventListener("keydown", e => {
  const row = e.target.closest(".agent");
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(row); row.blur(); document.querySelector(`.agent[data-id="${row.dataset.id}"]`)?.focus(); }
});
$("list").addEventListener("toggle", e => {
  const d = e.target; if (!d.dataset?.key) return;
  d.open ? state.details.add(d.dataset.key) : state.details.delete(d.dataset.key);
  balance();
}, true);
$("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip"); if (!chip) return;
  if ("hooks" in chip.dataset) state.hooks = !state.hooks;
  else { const k = chip.dataset.status; state.hide.has(k) ? state.hide.delete(k) : state.hide.add(k); }
  render();
});
$("q").addEventListener("input", e => { state.q = e.target.value; render(); });
$("range").addEventListener("change", e => { state.range = e.target.value; render(); });

function setLive(ok) {
  $("live").className = "live" + (ok ? "" : " off");
  $("live").innerHTML = LIVE ? `<span class="dot"></span>${ok ? "Live" : "Disconnected"} · updated ${clock(DATA.now)}`
    : `Snapshot taken ${clock(DATA.now)}`;
}
// The live server hands out data only with the per-run token from the URL fragment, which never leaves the browser.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || "";
async function poll() {
  try {
    const res = await fetch("data.json", {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}});
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json(); render(); setLive(true);
  } catch {
    if (DATA) setLive(false);
    else $("live").textContent = "Can't load data: open the exact URL the script printed.";
  }
}
if (DATA) { render(); setLive(true); }
if (LIVE) { poll(); setInterval(poll, 5000); }
</script>
</body>
</html>
"""


def page(data, live):
    payload = json.dumps(data).replace("</", "<\\/")
    return PAGE.replace("__LIVE__", "true" if live else "false").replace("__DATA__", payload)


def serve(session, port, open_browser):
    """Serve the live page. Transcript data needs the per-run token, and only same-host requests are answered,
    so other local users and DNS-rebinding web pages can't read it."""
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (origin is not None and origin not in {f"http://{h}" for h in hosts}):
                self.send_error(403)
                return
            route = self.path.split("?", 1)[0]
            if route == "/data.json":
                if not hmac.compare_digest(self.headers.get("X-Timeline-Token", ""), token):
                    self.send_error(403)
                    return
                body, ctype = json.dumps(collect(session)).encode(), "application/json"
            elif route in ("/", "/index.html"):
                body, ctype = page(None, live=True).encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/#t={token}"
    print(f"Serving {session} at {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", help="session .jsonl, session id, or project folder")
    parser.add_argument("-o", "--output", help="HTML file to write (default: system temp folder)")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    parser.add_argument("--serve", action="store_true", help="serve a live page that refreshes every 5 seconds")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (default: a random free port)")
    args = parser.parse_args(argv)

    session = resolve(args.target)
    if args.serve:
        serve(session, args.port, args.open)
        return
    data = collect(session)
    out = Path(args.output) if args.output else Path(tempfile.gettempdir()) / f"agent-timeline-{session.stem[:8]}.html"
    out.write_text(page(data, live=False), encoding="utf-8")
    print(f"{len(data['agents'])} agents from {session}")
    print(f"Wrote {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main(sys.argv[1:])
