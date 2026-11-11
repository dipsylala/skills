#!/usr/bin/env python3
"""Show the subagents a Claude Code session spawned, as a timeline you can drill into.

Usage:
  agent-timeline.py [TARGET] [-o OUT.html] [--open]   write a snapshot page
  agent-timeline.py [TARGET] --serve [--port N] [--idle-exit MINUTES]
                                                      serve a live page on 127.0.0.1

--serve reuses the server another run already started, printing a URL for this
session, so one server covers every session you watch. It stops itself 10 minutes
after the last page closes. Pass --port to run a separate server instead.

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
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
STATE = PROJECTS.parent / "agent-timeline" / "server.json"  # the shared server's port, token and pid
VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]  # an updated script starts a fresh server
SESSION_ID = re.compile(r"[0-9a-fA-F-]{8,64}")
SPAWN_TOOLS = {"Agent", "Task"}
HANDBACK_TOOL = "SubagentHandback"
IDLE_GAP = 600        # seconds without a transcript entry that split activity into separate bars
RUNNING_WINDOW = 120  # seconds since the last entry for an unfinished agent to count as running
STALL_AFTER = 600     # seconds of silence after which an unfinished agent counts as stalled
RESULT_LINE = re.compile(r"^\s*(STATUS|VERDICT):", re.M)
HOOK_KINDS = ["ran", "context", "message", "cancelled", "error", "blocked"]  # least to most severe
FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = {"Bash", "PowerShell"}
COMMIT_OUT = re.compile(r"^\[([^\]\s]+)(?: \(root-commit\))? ([0-9a-f]{7,40})\] (.+)$", re.M)
# The message from -m "...", a shell heredoc (-F - <<'EOF'), or a PowerShell here-string (-F - @'); -F <file> can't be read.
COMMIT_MSG = re.compile(r"""git\s+commit\b[^\n]*?\s-m\s+(["'])([\s\S]+?)\1|git\s+commit\b[^\n]*<<-?\s*['"]?(\w+)['"]?\n(.*)"""
                        r"""|git\s+commit\b[^\n]*@['"]\r?\n(.*)""")
GIT_COMMIT = re.compile(r"(?:^|[;&|(]|\n)\s*git\s+(?:-C\s+\S+\s+)?commit\b")  # run, not merely mentioned
GH_PR_CREATE = re.compile(r"(?:^|[;&|(]|\n)\s*gh\s+pr\s+create\b")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
BRIEF_KEYS = ("command", "file_path", "path", "pattern", "url", "description", "query", "title", "message", "prompt")


def read_jsonl(path):
    """Each entry with its byte offset, so a later lookup can jump straight back to it."""
    with open(path, "rb") as f:
        while True:
            offset, line = f.tell(), f.readline()
            if not line:
                return
            try:
                yield offset, json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue


def entry_at(path, offset):
    with open(path, "rb") as f:
        f.seek(offset)
        return json.loads(f.readline())


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
    files, commits, prs, shell = {}, [], [], {}  # outputs; shell: git commands awaiting their result
    cwd = None
    for offset, entry in read_jsonl(path):
        cwd = cwd or entry.get("cwd")
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
        if entry.get("type") == "user" and isinstance(content, list):
            for block in content:
                command = shell.pop(block.get("tool_use_id"), None) if block.get("type") == "tool_result" else None
                if command is None or block.get("is_error"):
                    continue
                output = text_of(block.get("content"))
                if GH_PR_CREATE.search(command):
                    prs += [{"t": t, "url": url} for url in dict.fromkeys(PR_URL.findall(output))]
                if GIT_COMMIT.search(command):
                    message = COMMIT_MSG.search(command)
                    out = COMMIT_OUT.search(output)
                    text = (message.group(2) or message.group(4) or message.group(5) or "") if message else out.group(3) if out else ""
                    commits.append({"t": t, "message": text.replace("\\n", "\n").strip().split("\n")[0],
                                    "branch": out.group(1) if out else "", "hash": out.group(2) if out else ""})
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
                if name in FILE_TOOLS and t is not None and tool_input.get(FILE_TOOLS[name]):
                    f = files.setdefault(tool_input[FILE_TOOLS[name]], {"t0": t, "t1": t, "writes": 0, "edits": 0, "at": {}})
                    if block.get("id") in f["at"]:
                        continue  # the same call written twice while streaming
                    f["at"][block.get("id")] = offset  # where the full change can be read back
                    f["t1"] = t
                    f["writes" if name == "Write" else "edits"] += 1
                elif name in SHELL_TOOLS and (GIT_COMMIT.search(tool_input.get("command") or "")
                                              or GH_PR_CREATE.search(tool_input.get("command") or "")):
                    shell[block.get("id")] = tool_input["command"]
                if name == HANDBACK_TOOL:
                    final, ended = str(tool_input.get("message", "")).strip(), True
                elif name.endswith("mark_chapter") and t is not None:
                    chapters.append({"t": t, "title": tool_input.get("title", "")})
                elif name in SPAWN_TOOLS:
                    spawns[block.get("id")] = {"t": t, "input": tool_input, "message": message.get("id")}
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
        "files": files, "commits": commits, "prs": prs, "cwd": cwd,
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
    if "finished" in meta:  # newer Claude Code rewrites the meta file when the agent finishes
        finished = meta["finished"] is True
        if finished and meta_mtime and info["mtime"] > meta_mtime + 5:
            finished = False  # resumed after it last finished
    else:  # older versions write it once at the start, so only the transcript can tell
        finished = info["ended"]
    age = now - info["end"]
    if finished:
        return "done"
    return "running" if age <= RUNNING_WINDOW else "quiet" if age <= STALL_AFTER else "stalled"


def batch_label(descriptions):
    """The words every description starts with (stopping after a "Name:" word), else the first one.

    When the descriptions differ by a number right after those words ("Ticket 28 ...", "Ticket 29 ..."),
    the shared words alone say nothing, so the first description is used instead.
    """
    if len(descriptions) == 1:
        return descriptions[0]
    words = [d.split() for d in descriptions]
    common = []
    for column in zip(*words):
        if len({w.lower() for w in column}) > 1:
            break
        common.append(column[0])
        if column[0].endswith(":"):
            break
    numbered = all(len(w) > len(common) and w[len(common)][:1].isdigit() for w in words)
    label = "" if numbered else " ".join(common).rstrip(":-– ")
    return label or f"{descriptions[0]} + {len(descriptions) - 1} more"


CLIP_CHARS, CLIP_BYTES = 200_000, 500_000  # limits on what the file viewer is sent


def relative_to(path, roots):
    """path relative to the first root it sits under (so worktree copies of a file match), else None."""
    p = path.replace("\\", "/")
    for root in roots:
        r = root.replace("\\", "/").rstrip("/") + "/" if root else None
        if r and p.lower().startswith(r.lower()):
            return p[len(r):]
    return None


def outputs(info, roots):
    """Files changed, commits and PRs, as sent to the page (without the transcript offsets)."""
    files = [{"path": relative_to(p, roots) or p.replace("\\", "/"), "abs": p, "inside": relative_to(p, roots) is not None,
              **{k: v for k, v in f.items() if k != "at"}}
             for p, f in sorted(info["files"].items(), key=lambda kv: kv[1]["t0"])]
    return {"files": files, "commits": info["commits"], "prs": info["prs"]}


def clip(text):
    text = text if isinstance(text, str) else ""
    return text if len(text) <= CLIP_CHARS else text[:CLIP_CHARS] + f"\n... (cut at {CLIP_CHARS:,} characters)"


def file_detail(session, rel):
    """What each agent did to one file, read back from the transcripts, and the file as it is now on disk.

    Only files that this session's transcripts changed can be asked for, so the server never reads anything else.
    """
    main = summarise(session)
    sources = [("main", session, main, [main["cwd"]])]
    for transcript in sorted((session.parent / session.stem / "subagents").glob("agent-*.jsonl")):
        meta_path = transcript.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        info = summarise(transcript)
        sources.append((transcript.stem.removeprefix("agent-"), transcript, info,
                        [meta.get("worktreePath"), info["cwd"], main["cwd"]]))
    changes, paths, inside = [], set(), False
    for agent_id, transcript, info, roots in sources:
        for path, f in info["files"].items():
            relative = relative_to(path, roots)
            if (relative or path.replace("\\", "/")).lower() != rel.lower():
                continue
            paths.add(path)
            inside = inside or relative is not None
            for block_id, offset in f["at"].items():
                entry = entry_at(transcript, offset)
                block = next((b for b in entry["message"]["content"] if b.get("id") == block_id), None)
                if not block:
                    continue
                tool_input, name = block.get("input") or {}, block.get("name")
                change = {"t": epoch(entry["timestamp"]), "agent": agent_id, "tool": name}
                if name == "Edit":
                    change["edits"] = [{"old": clip(tool_input.get("old_string")), "new": clip(tool_input.get("new_string"))}]
                elif name == "MultiEdit":
                    change["edits"] = [{"old": clip(e.get("old_string")), "new": clip(e.get("new_string"))}
                                       for e in tool_input.get("edits") or []]
                else:  # Write, or NotebookEdit's new cell source
                    change["content"] = clip(tool_input.get("content") if name == "Write" else tool_input.get("new_source"))
                changes.append(change)
    if not paths:
        return None
    # The current copy: the project's own file first (worktrees are often gone once merged), then worktree copies.
    root = (main["cwd"] or "").replace("\\", "/").lower().rstrip("/") + "/"
    own = lambda p: p.replace("\\", "/").lower().startswith(root) and "/.claude/worktrees/" not in p.replace("\\", "/").lower()
    candidates = sorted(paths, key=lambda p: not own(p))
    if inside and main["cwd"] and ".." not in rel.split("/"):
        candidates.insert(0, str(Path(main["cwd"]) / rel))
    current = {"missing": True}
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read(CLIP_BYTES + 1)
            binary = b"\0" in data[:8192]
            current = {"path": path, "binary": binary, "truncated": len(data) > CLIP_BYTES,
                       "text": "" if binary else data[:CLIP_BYTES].decode("utf-8", "replace")}
            break
    return {"changes": sorted(changes, key=lambda c: c["t"]), "current": current}


def collect(session):
    now = time.time()
    main = summarise(session)
    agents, spawned_in = [], {}
    for transcript in sorted((session.parent / session.stem / "subagents").glob("agent-*.jsonl")):
        info = summarise(transcript)
        spawned_in.update({k: s.get("message") for k, s in info["spawns"].items()})  # agents started by this agent
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
            "spawn_id": meta.get("toolUseId") or launch.get("tool_use_id"),
            "status": status_of(info, meta, meta_path.stat().st_mtime if meta else None, now),
            "type": meta.get("agentType") or spawn_input.get("subagent_type") or "",
            "model": ", ".join(info["models"]) or meta.get("pickedEffortModel") or launch.get("model") or "",
            "background": meta.get("requestShape") == "background" or bool(spawn_input.get("run_in_background")),
            "depth": meta.get("spawnDepth", 1),
            "transcript": str(transcript),
            "branch": meta.get("worktreeBranch") or "",
            **outputs(info, [meta.get("worktreePath"), info["cwd"], main["cwd"]]),
            **{k: info[k] for k in ("start", "end", "segments", "active", "tools", "tokens_in",
                                    "tokens_out", "prompt", "final", "result", "activity", "hooks")},
        })
    agents.sort(key=lambda a: a["start"])
    # Agents started from the same message (launched together) form one group; others stand alone.
    spawned_in.update({k: s.get("message") for k, s in main["spawns"].items()})
    batches = {}
    for a in agents:
        batches.setdefault(spawned_in.get(a.pop("spawn_id")) or a["id"], []).append(a)
    for key, members in batches.items():
        label = batch_label([a["description"] for a in members])
        for a in members:
            a["group"], a["group_label"] = key, label
    return {
        "now": now,
        "session": session.stem,
        "project": session.parent.name,
        "main": {"running": now - main["end"] <= RUNNING_WINDOW, "transcript": str(session), "branch": "",
                 **outputs(main, [main["cwd"]]),
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
main.wide { max-width:none; }
[hidden] { display:none !important; }
h1 { font-size:20px; margin:0 0 2px; }
.sub { color:var(--muted); margin:0 0 12px; word-break:break-all; font-size:12px; }
.stats { display:flex; flex-wrap:wrap; gap:6px 22px; margin:0 0 14px; }
.stats b { font-variant-numeric:tabular-nums; }
.stats [title] { text-decoration:underline dotted var(--muted); text-underline-offset:3px; cursor:help; }
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
.grouprow { cursor:pointer; border-top:1px solid var(--line); }
.grouprow .name { font-weight:600; }
.grouprow .name small { font-weight:400; }
.grouprow .chev { color:var(--muted); }
.agent { cursor:pointer; border-top:1px solid transparent; }
.agent:hover, .agent:focus-visible, .agent.hl, .grouprow:hover, .grouprow:focus-visible { background:var(--hover); outline:none; }
.attention { margin:0 0 12px; padding:6px 10px; border:1px solid var(--stall); border-radius:6px; font-size:13px; }
.attention small { color:var(--muted); }
.goto { font:inherit; color:inherit; background:none; border:0; padding:0; text-decoration:underline; cursor:pointer; }
.statusline { font-size:12px; color:var(--muted); margin:0 0 10px; }
.more { margin-top:12px; }
.more > summary { margin-bottom:8px; }
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
.bar::after { content:""; position:absolute; inset:-6px 0; }  /* taller hover area for the tooltip */
.bar.running { background-image:repeating-linear-gradient(45deg, transparent 0 5px, rgba(255,255,255,.35) 5px 10px); background-size:14px 14px; animation:slide 1s linear infinite; }
@keyframes slide { to { background-position:14px 0; } }
.num { text-align:right; font-variant-numeric:tabular-nums; font-size:12px; color:var(--muted); white-space:nowrap; }
.s-running { color:var(--run); } .s-quiet { color:var(--quiet); } .s-stalled { color:var(--stall); } .s-done { color:var(--done); }
.b-running { background-color:var(--run); } .b-quiet { background-color:var(--quiet); } .b-stalled { background-color:var(--stall); } .b-done { background-color:var(--done); } .b-main { background-color:var(--main); }
/* The marker is a 16px-wide hit area; the small diamond is drawn inside it. */
.hook { position:absolute; top:0; width:16px; height:16px; margin-left:-8px; z-index:1; }
.hook::before { content:""; position:absolute; left:4px; top:3px; width:8px; height:8px; transform:rotate(45deg); border-radius:1px; background:var(--k); }
.hook.multi::before { box-shadow:0 0 0 2px var(--card); }
.hook:hover::before { transform:rotate(45deg) scale(1.4); }
.k-blocked, .k-error { --k:var(--chapter); } .k-message, .k-context { --k:var(--stall); }
.k-cancelled { --k:var(--muted); } .k-ran { --k:var(--muted); } .k-ran::before { opacity:.45; }
.tip { position:fixed; z-index:10; max-width:420px; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--card);
  box-shadow:0 4px 14px rgba(0,0,0,.18); font-size:12px; white-space:pre-line; pointer-events:none; }
.tip b { font-weight:600; }
.tabs { display:flex; gap:4px; margin:0 0 10px; border-bottom:1px solid var(--line); }
.tab { font:inherit; font-size:13px; background:none; border:0; border-bottom:2px solid transparent; margin-bottom:-1px;
  padding:6px 10px; color:var(--muted); cursor:pointer; }
.tab[aria-selected="true"] { color:var(--fg); border-bottom-color:var(--run); font-weight:600; }
main.view-outputs #chips, main.view-outputs #range, main.view-outputs #list { display:none; }
main:not(.view-outputs) #outputs { display:none; }
.outputs section { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 14px; margin:0 0 12px; }
.outputs h2 { font-size:13px; margin:0 0 8px; }
.otable { width:100%; border-collapse:collapse; font-size:12px; }
.otable td { padding:3px 10px 3px 0; border-bottom:1px dotted var(--line); vertical-align:top; }
.otable .p { font-family:ui-monospace, Consolas, monospace; word-break:break-all; }
.otable .t { color:var(--muted); white-space:nowrap; font-variant-numeric:tabular-nums; width:1%; }
.otable small { color:var(--muted); }
.clash { color:var(--stall); font-weight:600; cursor:help; }
.outputs a, .detail a { color:var(--run); }
.shared { color:var(--muted); }
.ofiles { display:grid; grid-template-columns:minmax(220px, 30%) minmax(0, 1fr); background:var(--card); border:1px solid var(--line);
  border-radius:8px; margin:0 0 12px; height:min(72vh, 820px); overflow:hidden; }
.otree { overflow:auto; border-right:1px solid var(--line); padding:6px 0; font-size:13px; }
.tnode { padding:2px 8px 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:pointer; }
.tnode:hover { background:var(--hover); }
.tnode.sel { background:var(--hover); box-shadow:inset 3px 0 0 var(--run); font-weight:600; }
.tnode .chev { display:inline-block; width:14px; color:var(--muted); }
.tnode small { color:var(--muted); font-weight:400; }
.oviewer { overflow:auto; padding:0 14px 14px; }
.vhead { position:sticky; top:0; z-index:1; background:var(--card); padding:10px 0 8px; border-bottom:1px solid var(--line); margin-bottom:10px; }
.vhead .p { font-family:ui-monospace, Consolas, monospace; font-size:13px; font-weight:600; word-break:break-all; margin-bottom:4px; }
.vmeta { font-size:12px; margin-bottom:6px; } .vmeta small { color:var(--muted); }
.change { margin:0 0 14px; }
.chead { font-size:12px; color:var(--muted); margin-bottom:4px; }
.oviewer pre { max-height:none; }
pre.diff .del, pre.diff .add { display:block; }
pre.diff .del { color:var(--chapter); background:color-mix(in srgb, var(--chapter) 10%, transparent); }
pre.diff .add { color:var(--done); background:color-mix(in srgb, var(--done) 10%, transparent); }
.hl-c { color:var(--muted); font-style:italic; } .hl-s { color:var(--done); } .hl-n { color:var(--stall); }
.hl-k { color:var(--quiet); font-weight:600; } .hl-t { color:var(--run); }
.md { font-size:14px; line-height:1.6; max-width:860px; }
.md h1, .md h2, .md h3, .md h4, .md h5, .md h6 { line-height:1.3; margin:1.2em 0 .5em; }
.md h1 { font-size:1.6em; border-bottom:1px solid var(--line); padding-bottom:.25em; }
.md h2 { font-size:1.3em; border-bottom:1px solid var(--line); padding-bottom:.2em; } .md h3 { font-size:1.1em; }
.md h4, .md h5, .md h6 { font-size:1em; } .md > :first-child { margin-top:0; }
.md p, .md ul, .md ol, .md blockquote, .md table, .md pre { margin:0 0 .9em; }
.md ul, .md ol { padding-left:1.6em; } .md li { margin:.15em 0; } .md li > ul, .md li > ol { margin:.15em 0; }
.md code { font-family:ui-monospace, Consolas, monospace; font-size:.9em; background:var(--hover); border-radius:4px; padding:.1em .35em; }
.md pre code { background:none; padding:0; }
.md blockquote { border-left:3px solid var(--line); margin-left:0; padding:0 0 0 12px; color:var(--muted); }
.md hr { border:0; border-top:1px solid var(--line); margin:1.2em 0; }
.md a { color:var(--run); } .md .mdlink { text-decoration:underline dotted; cursor:help; } .md .mdimg { color:var(--muted); font-style:italic; }
.mdtable { border-collapse:collapse; font-size:13px; display:block; overflow-x:auto; }
.mdtable th, .mdtable td { border:1px solid var(--line); padding:4px 10px; text-align:left; vertical-align:top; }
.mdtable th { background:var(--hover); }
pre.code .ln { display:inline-block; min-width:3em; margin-right:12px; text-align:right; color:var(--muted); user-select:none; }
@media (max-width:760px) { .ofiles { grid-template-columns:1fr; height:auto; }
  .otree { max-height:40vh; border-right:0; border-bottom:1px solid var(--line); } .oviewer { max-height:70vh; } }
.tip .entry + .entry { border-top:1px solid var(--muted); margin-top:7px; padding-top:7px; }
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
.feed { list-style:none; margin:0; padding:0; font-size:12px; max-height:180px; overflow:auto; }
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
<div class="attention" id="attention" hidden></div>
<div class="tabs" role="tablist">
  <button class="tab" role="tab" data-view="timeline" aria-selected="true">Timeline</button>
  <button class="tab" role="tab" data-view="outputs" aria-selected="false">Outputs</button>
</div>
<div class="controls">
  <span id="chips"></span>
  <input type="search" id="q" placeholder="Filter agents" aria-label="Filter agents">
  <select id="range" aria-label="Time range">
    <option value="fit">Fit to agents</option>
    <option value="session">Whole session</option>
    <option value="recent">Last 30 minutes</option>
  </select>
  <button class="chip" id="wide" aria-pressed="false" title="Use the full window width">⇔ Full width</button>
  <span class="live" id="live"></span>
</div>
<div class="list" id="list"></div>
<div class="outputs" id="outputs">
  <p class="sub" id="osum"></p>
  <div class="ofiles"><div class="otree" id="otree" role="tree" aria-label="Changed files"></div><div class="oviewer" id="oviewer"></div></div>
  <div id="oextra"></div>
</div>
</main>
<div class="tip" id="tip" role="tooltip" hidden></div>
<script>
const LIVE = __LIVE__;
let DATA = __DATA__;
const STATUS = {running: ["Running", "●"], quiet: ["Quiet", "◐"], stalled: ["Stalled", "⚠"], done: ["Done", "✓"]};
// Hook markers: "notable" hides routine runs that printed nothing; the Hooks chip cycles through the modes.
const NOTABLE = new Set(["blocked", "error", "message", "context"]);
const HOOK_MODES = {notable: ["Notable hooks", "all"], all: ["All hooks", "off"], off: ["Hooks off", "notable"]};
const state = {open: new Set(), details: new Set(), hide: new Set(), groups: new Map(), folders: new Map(),
  view: "timeline", file: "", fileMode: "changes", hooks: "notable", q: "", range: "fit"};
const SEVERITY = ["ran", "context", "message", "cancelled", "error", "blocked"];  // least to most, as in HOOK_KINDS
const KEEP = 8, EARLIER = "earlier";  // groups or rows kept outside the Earlier fold; its state key
let foldedIds = new Set();
const groupStatus = agents => ["running", "stalled", "quiet"].find(s => agents.some(a => a.status === s)) || "done";
const tally = agents => Object.keys(STATUS).map(k => [k, agents.filter(a => a.status === k).length]).filter(([, n]) => n)
  .map(([k, n]) => `${n} ${STATUS[k][0].toLowerCase()}`).join(" · ");
const statusOf = a => STATUS[a.status] || ["Idle", "·"];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const dur = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`; };
const kt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
const clock = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});

function segmentsOf(a) {
  // A running agent is still working: draw its last bar up to now.
  return a.status === "running" ? a.segments.map((s, i, all) => i === all.length - 1 ? [s[0], Math.max(s[1], DATA.now)] : s) : a.segments;
}

// Times on other days than the data's "now" carry their date.
const when = t => new Date(t * 1000).toDateString() === new Date(DATA.now * 1000).toDateString() ? clock(t)
  : new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});

// Tooltip for one bar: who and how it ended, when, and what it used.
function barTip(a) {
  const tools = Object.entries(a.tools).sort((p, q) => q[1] - p[1]);
  const calls = tools.reduce((sum, [, v]) => sum + v, 0);
  const top = tools.slice(0, 3).map(([k, v]) => `${k.replace(/^mcp__.*?__/, "")} ${v}`).join(", ");
  const [name] = statusOf(a);
  const finish = a.status === "running" ? "still running" : a.status === "done" ? `finished ${when(a.end)}` : `${name.toLowerCase()} since ${when(a.end)}`;
  return `<div class="entry"><b>${esc(a.description)}</b> · <span class="s-${a.status}">${name}</span>${a.result ? "\n" + esc(a.result.slice(0, 200)) : ""}</div>`
    + `<div class="entry">Started ${when(a.start)} · ${finish}\n${dur(a.active)} active</div>`
    + `<div class="entry">${kt(a.tokens_out)} output tokens · ${kt(a.tokens_in)} input (including cached context)\n`
    + `${esc(a.model)}${a.type ? " · " + esc(a.type) : ""}\n${calls} tool call${calls === 1 ? "" : "s"}${top ? ": " + esc(top) : ""}</div>`;
}

// The Outputs tab: a folder tree of changed files with a viewer beside it, then files that several agents
// changed, and commits and pull requests.
const OUTSIDE = "(outside the project)";  // scratch files, temp PR bodies and the like
const fileCache = new Map();  // viewer data by file and its latest change, so polling doesn't refetch it
let viewerKey = "";
const who = a => `<button class="goto" data-goto="${esc(a.id)}">${esc(a.description)}</button>`;
const did = f => [f.writes && `wrote${f.writes > 1 ? ` ×${f.writes}` : ""}`, f.edits && `${f.edits} edit${f.edits > 1 ? "s" : ""}`].filter(Boolean).join(", ");
const flag = x => x.clash ? `<span class="clash" title="Changed by agents that were running at the same time">⚠</span> `
  : x.shared ? `<span class="shared" title="Changed by more than one agent">◆</span> ` : "";
const nameOf = id => id === "main" ? "Main session" : DATA.agents.find(a => a.id === id)?.description || id;

function outputsModel() {
  const m = DATA.main;
  const people = [{...m, id: "main", description: "Main session", status: m.running ? "running" : "idle"}, ...DATA.agents];
  const files = new Map();
  for (const a of people) for (const f of a.files) {
    const key = f.path.toLowerCase();
    if (!files.has(key)) files.set(key, {key, path: f.path, inside: f.inside, by: []});
    files.get(key).by.push({a, f});
  }
  // The main session integrating agents' work is expected; two subagents on one file is worth a look,
  // more so when they ran at the same time (a likely merge conflict or overwrite).
  const together = (a, b) => a.start < b.end && b.start < a.end;
  for (const x of files.values()) {
    const subs = x.by.filter(b => b.a.id !== "main");
    x.shared = x.inside && subs.length > 1;
    x.clash = x.shared && subs.some((b, i) => subs.slice(i + 1).some(c => together(b.a, c.a)));
    x.last = Math.max(...x.by.map(b => b.f.t1));
  }
  return {people, files};
}

function renderOutputs() {
  const {people, files} = outputsModel();
  const q = state.q.toLowerCase(), match = (...parts) => !q || parts.join(" ").toLowerCase().includes(q);
  const all = [...files.values()].filter(x => match(x.path, ...x.by.map(b => b.a.description)));

  // Folder tree; a folder holding only one folder is joined with it ("src/app/admin"), as in most editors.
  const root = {path: "", dirs: new Map(), files: []};
  for (const x of all) {
    const parts = x.inside ? x.path.split("/") : [OUTSIDE, x.path];
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node.dirs.has(part)) node.dirs.set(part, {name: part, path: node.path ? `${node.path}/${part}` : part, dirs: new Map(), files: []});
      node = node.dirs.get(part);
    }
    node.files.push({x, name: parts.at(-1)});
  }
  const count = n => n.files.length + [...n.dirs.values()].reduce((s, d) => s + count(d), 0);
  const many = all.length > 40 && !q;  // big trees start with only the top level open
  const tree = (node, depth) => {
    let html = "";
    const dirs = [...node.dirs.values()].sort((a, b) => (a.name === OUTSIDE) - (b.name === OUTSIDE) || a.name.localeCompare(b.name));
    for (let d of dirs) {
      let label = d.name;
      while (d.name !== OUTSIDE && !d.files.length && d.dirs.size === 1) { d = [...d.dirs.values()][0]; label += `/${d.name}`; }
      const open = state.folders.has(d.path) ? state.folders.get(d.path) : d.name !== OUTSIDE && (!many || depth === 0);
      html += `<div class="tnode dir" data-dir="${esc(d.path)}" data-open="${open}" style="padding-left:${6 + depth * 14}px" title="${esc(label)}">`
        + `<span class="chev">${open ? "▾" : "▸"}</span>${esc(label)} <small>${count(d)}</small></div>`;
      if (open) html += tree(d, depth + 1);
    }
    for (const {x, name} of node.files.sort((a, b) => a.name.localeCompare(b.name)))
      html += `<div class="tnode file${state.file === x.key ? " sel" : ""}" data-file="${esc(x.key)}" style="padding-left:${20 + depth * 14}px" title="${esc(x.path)}">`
        + `${flag(x)}${esc(name)}${x.by.length > 1 ? ` <small>${x.by.length} agents</small>` : ""}</div>`;
    return html;
  };

  const events = [
    ...people.flatMap(a => a.prs.map(p => ({...p, a, pr: true}))).filter(p => match(p.url, p.a.description)),
    ...people.flatMap(a => a.commits.map(c => ({...c, a}))).filter(c => match(c.message, c.a.description)),
  ].sort((x, y) => x.t - y.t);
  const commitCount = events.filter(e => !e.pr).length;
  const changers = new Set(all.flatMap(x => x.by.map(b => b.a.id))).size;
  $("osum").textContent = `${all.length} files changed by ${changers} agent${changers === 1 ? "" : "s"} · ${commitCount} commits · `
    + `${events.length - commitCount} pull requests. Files come from Write and Edit calls; changes made through shell commands are not counted.`;
  const scroll = $("otree").scrollTop;
  $("otree").innerHTML = tree(root, 0) || `<p class="empty">No file changes recorded.</p>`;
  $("otree").scrollTop = scroll;
  renderViewer(files.get(state.file));

  let extra = "";
  if (events.length) extra += `<section><h2>Commits and pull requests</h2><table class="otable">${events.map(e => e.pr
    ? `<tr><td class="t">${when(e.t)}</td><td>${who(e.a)}</td><td colspan="2">Pull request <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url.replace("https://github.com/", ""))}</a></td></tr>`
    : `<tr><td class="t">${when(e.t)}</td><td>${who(e.a)}</td><td>${esc(e.message) || "<small>(message not in the command)</small>"}</td>
      <td class="p">${esc([e.branch || e.a.branch, e.hash].filter(Boolean).join(" "))}</td></tr>`).join("")}</table></section>`;
  $("oextra").innerHTML = extra;
}

// The viewer re-renders only when the selected file, its latest change, or the mode changes, so polling
// doesn't reset its scroll position or refetch.
function renderViewer(x) {
  // Preview exists only for markdown; on other files that choice shows the current file instead.
  const mode = x && state.fileMode === "preview" && !isMarkdown(x.path) ? "current" : state.fileMode;
  const key = x ? `${x.key}|${x.last}|${mode}` : "";
  if (key === viewerKey) return;
  viewerKey = key;
  const v = $("oviewer");
  if (!x) { v.innerHTML = `<p class="empty">Select a file to see what each agent changed.</p>`; return; }
  const modes = [["changes", "Changes"], ["current", "Current file"], ...(isMarkdown(x.path) ? [["preview", "Preview"]] : [])]
    .map(([m, label]) => `<button class="chip" data-mode="${m}" aria-pressed="${mode === m}">${label}</button>`).join(" ");
  v.innerHTML = `<div class="vhead"><div class="p">${flag(x)}${esc(x.path)}</div>
    <div class="vmeta">${x.by.map(b => `${who(b.a)} <small>${did(b.f)} · ${when(b.f.t1)}</small>`).join(" · ")}</div><div>${modes}</div></div>
    <div id="vbody"><p class="empty">${LIVE ? "Loading…" : "File contents need the live view: run the script with --serve."}</p></div>`;
  v.scrollTop = 0;
  if (!LIVE) return;
  const show = d => { if (viewerKey === key) $("vbody").innerHTML = mode === "changes" ? changesHtml(d) : mode === "preview" ? previewHtml(d) : currentHtml(d, x.path); };
  const cacheKey = `${x.key}|${x.last}`;
  if (fileCache.has(cacheKey)) return show(fileCache.get(cacheKey));
  fetch(`file.json${location.search}${location.search ? "&" : "?"}path=${encodeURIComponent(x.path)}`,
        {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => { fileCache.set(cacheKey, d); show(d); })
    .catch(() => { if (viewerKey === key) $("vbody").innerHTML = `<p class="empty">Couldn't load this file.</p>`; });
}

const diffLines = (text, cls, sign) => text ? esc(text).split("\n").map(l => `<span class="${cls}">${sign} ${l}</span>`).join("") : "";
function changesHtml(d) {
  if (!d.changes.length) return `<p class="empty">No recorded changes.</p>`;
  return d.changes.slice().reverse().map((c, i) => `<div class="change">
    <div class="chead">${when(c.t)} · <button class="goto" data-goto="${esc(c.agent)}">${esc(nameOf(c.agent))}</button> · `
    + `${c.edits ? `edit${c.edits.length > 1 ? ` in ${c.edits.length} places` : ""}` : c.tool === "Write" ? "wrote the whole file" : "notebook cell"}</div>`
    + (c.edits ? c.edits.map(e => `<pre class="diff">${diffLines(e.old, "del", "-")}${diffLines(e.new, "add", "+")}</pre>`).join("")
      : `<details${i === 0 ? " open" : ""}><summary>${c.content.split("\n").length} lines</summary><pre>${esc(c.content)}</pre></details>`)
    + `</div>`).join("");
}
const numbered = html => html.split("\n").map((l, i) => `<span class="ln">${i + 1}</span>${l}`).join("\n");
function currentHtml(d, path) {
  const c = d.current;
  if (c.missing) {
    const known = lastKnown(d.changes);
    return `<p class="empty">This file isn't in the project or its worktrees now. It was probably deleted, renamed, or merged into
      another file by a shell command, or left in a worktree that has since been removed; the transcripts can't follow that.</p>`
      + (known === null ? "" : `<p class="sub">Last version an agent wrote, rebuilt from the transcript (its last full write plus later edits):</p>
      <pre class="code">${numbered(highlight(known, path))}</pre>`);
  }
  if (c.binary) return `<p class="empty">Binary file: ${esc(c.path)}</p>`;
  return `<p class="sub">${esc(c.path)}${c.truncated ? " (first 500 KB)" : ""}</p><pre class="code">${numbered(highlight(c.text, c.path))}</pre>`;
}
const isMarkdown = path => /\.(md|markdown|mdx)$/i.test(path);
function previewHtml(d) {
  const c = d.current, text = c.missing ? lastKnown(d.changes) : c.binary ? null : c.text;
  if (text === null) return `<p class="empty">Nothing to preview.</p>`;
  return (c.missing ? `<p class="sub">Rebuilt from the transcript: this file isn't in the project now.</p>` : "")
    + `<div class="md">${markdown(text)}</div>`;
}

// A small built-in markdown renderer. Everything is escaped first; only http(s) and mailto links are clickable,
// and images are shown as placeholders, so the page never loads anything from elsewhere.
// No step ever runs over markup another step produced: one pass over the raw text swaps code spans, images, links
// and bare URLs for placeholders, each built from its own escaped parts; the rest is escaped, and emphasis is a
// single pass over that escaped text, which holds no tags yet.
const MD_HELD = /`([^`]+)`|!\[([^\]]*)\]\([^)]*\)|\[([^\]]+)\]\(([^)\s]+)[^)]*\)|(https?:\/\/[^\s<>"'`)]+)/g;
const MD_EMPHASIS = /\*\*(?=\S)([^*]*?\S)\*\*|__(?=\S)([^_]*?\S)__|~~(?=\S)([^~]*?\S)~~|(^|[^*\w])\*(?=\S)([^*]*?\S)\*(?!\w)|(^|[^\w])_(?=\S)([^_]*?\S)_(?!\w)/g;
function mdInline(raw) {
  const held = [], hold = html => `\u0000${held.push(html) - 1}\u0000`;
  const link = (url, text) => /^(https?:|mailto:)/i.test(url)
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`
    : `<span class="mdlink" title="${esc(url)}">${esc(text)}</span>`;
  const text = raw.replace(/\u0000/g, "").replace(MD_HELD, (_, code, alt, label, url, bare) => hold(
    code !== undefined ? `<code>${esc(code)}</code>`
    : alt !== undefined ? `<span class="mdimg">[image${alt ? ": " + esc(alt) : ""}]</span>`
    : label !== undefined ? link(url, label) : link(bare, bare)));
  return esc(text)
    .replace(MD_EMPHASIS, (_, strong, strong2, del, pre, em, pre2, em2) =>
      strong || strong2 ? `<strong>${strong || strong2}</strong>` : del ? `<del>${del}</del>` : em ? `${pre}<em>${em}</em>` : `${pre2}<em>${em2}</em>`)
    .replace(/\u0000(\d+)\u0000/g, (_, i) => held[i]);
}
const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
function mdList(lines, i) {
  const indent = lines[i].match(/^\s*/)[0].length, ordered = /^\s*\d/.test(lines[i]);
  let html = "";
  while (i < lines.length) {
    const m = lines[i].match(LIST_ITEM);
    if (!m || m[1].length < indent) break;
    if (m[1].length > indent) { const [inner, next] = mdList(lines, i); html = html.replace(/<\/li>$/, inner + "</li>"); i = next; continue; }
    let text = m[3]; i++;
    while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !LIST_ITEM.test(lines[i])) text += " " + lines[i++].trim();
    const task = text.match(/^\[([ xX])\]\s+(.*)$/);
    html += `<li>${task ? `<input type="checkbox" disabled${task[1] === " " ? "" : " checked"}> ${mdInline(task[2])}` : mdInline(text)}</li>`;
  }
  return [ordered ? `<ol>${html}</ol>` : `<ul>${html}</ul>`, i];
}
function markdown(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n"), para = [];
  let html = "", i = 0, m;
  const flush = () => { if (para.length) html += `<p>${mdInline(para.splice(0).join(" "))}</p>`; };
  const cells = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
  while (i < lines.length) {
    const line = lines[i];
    if ((m = line.match(/^\s*(`{3,}|~{3,})\s*([\w+#.-]*)/))) {
      flush(); const body = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith(m[1])) body.push(lines[i++]);
      i++; html += `<pre class="code">${highlight(body.join("\n"), `x.${m[2] || "txt"}`)}</pre>`;
    } else if (!line.trim()) { flush(); i++; }
    else if ((m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) { flush(); html += `<h${m[1].length}>${mdInline(m[2])}</h${m[1].length}>`; i++; }
    else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); html += "<hr>"; i++; }
    else if (/^\s*>/.test(line)) {
      flush(); const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      html += `<blockquote>${markdown(body.join("\n"))}</blockquote>`;
    } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      flush(); const head = cells(line), rows = []; i += 2;
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      html += `<table class="mdtable"><thead><tr>${head.map(c => `<th>${mdInline(c)}</th>`).join("")}</tr></thead>`
        + `<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${mdInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    } else if (LIST_ITEM.test(line)) { flush(); const [list, next] = mdList(lines, i); html += list; i = next; }
    else { para.push(line.trim()); i++; }
  }
  flush();
  return html;
}

// The file as the agents left it: the last whole-file write, with the edits made after it applied in order.
function lastKnown(changes) {
  const start = changes.map(c => c.tool === "Write").lastIndexOf(true);
  if (start < 0) return null;
  let text = changes[start].content;
  for (const c of changes.slice(start + 1)) for (const e of c.edits || []) text = text.replace(e.old, () => e.new);
  return text;
}

// A small built-in highlighter (no third-party code on a page that holds transcripts and a token): comments,
// strings, numbers, keywords and capitalised type names, with comment styles picked by file extension.
const KEYWORDS = new Set(("abstract as async await base bool break case catch char class const continue def default del delete do "
  + "double elif else enum except export extends false final finally float fn for foreach from func function get if impl "
  + "implements import in int interface internal is lambda let long match mod mut namespace new nil none not null object of "
  + "or out override package pass private protected pub public raise readonly ref return sealed self set static string struct "
  + "super switch this throw throws trait true try type typeof uint unsafe use using val var virtual void when where while with yield").split(" "));
function highlight(text, path) {
  const ext = (path.match(/\.([^./\\]+)$/) || [])[1]?.toLowerCase() || "";
  if (/^(md|markdown|txt|log|csv|tsv|rst)$/.test(ext)) return esc(text);
  const hash = /^(py|rb|sh|bash|zsh|ps1|psm1|yml|yaml|toml|r|pl|conf|ini|cfg|env|mk|dockerfile|gitignore)$/.test(ext);
  const markup = /^(html?|xml|xaml|svg|csproj|props|targets|vue)$/.test(ext);
  const comment = markup ? String.raw`<!--[\s\S]*?-->` : hash ? String.raw`#[^\n]*` : ext === "sql" ? String.raw`--[^\n]*|/\*[\s\S]*?\*/`
    : String.raw`//[^\n]*|/\*[\s\S]*?\*/`;
  const strings = String.raw`"{3}[\s\S]*?"{3}|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'` + (/^(js|mjs|cjs|jsx|ts|tsx)$/.test(ext) ? String.raw`|` + "`(?:\\\\.|[^`\\\\])*`" : "");
  const token = new RegExp(`(${comment})|(${strings})|(\\b0x[0-9a-fA-F]+\\b|\\b\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)|([A-Za-z_$][\\w$]*)`, "g");
  let html = "", last = 0;
  for (const m of text.matchAll(token)) {
    html += esc(text.slice(last, m.index));
    const cls = m[1] ? "hl-c" : m[2] ? "hl-s" : m[3] ? "hl-n" : KEYWORDS.has(m[4]) ? "hl-k" : !markup && /^[A-Z][a-z]/.test(m[4]) ? "hl-t" : "";
    html += cls ? `<span class="${cls}">${esc(m[0])}</span>` : esc(m[0]);
    last = m.index + m[0].length;
  }
  return html + esc(text.slice(last));
}

function selectFile(key) {
  const x = outputsModel().files.get(key); if (!x) return;
  state.file = key;
  const parts = x.inside ? x.path.split("/").slice(0, -1) : [OUTSIDE];
  parts.forEach((_, i) => state.folders.set(parts.slice(0, i + 1).join("/"), true));
  renderOutputs();
  document.querySelector("#otree .file.sel")?.scrollIntoView({block: "nearest"});
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
  const bar = (s, e, cls, tip) => e < lo || s > hi ? "" :
    `<div class="bar ${cls}" style="left:${x(s)}%;width:${Math.max(0, x(e) - x(s))}%" data-tip="${esc(tip)}"></div>`;
  const bars = (a, cls) => { const tip = barTip(a); return segmentsOf(a).map(([s, e]) => bar(s, e, cls, tip)).join(""); };
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400, 172800, 604800];
  const maxTicks = Math.max(4, Math.floor($("list").clientWidth * 0.6 / 130));  // more labels on wide screens
  const step = steps.find(s => (hi - lo) / s <= maxTicks) || 1209600;
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
  const notableCount = allHooks.filter(h => NOTABLE.has(h.kind)).length;
  $("chips").innerHTML = Object.entries(STATUS).map(([k, [name, icon]]) =>
    `<button class="chip" data-status="${k}" aria-pressed="${!state.hide.has(k)}"><span class="s-${k}">${icon}</span> ${name}<span class="n">${counts[k]}</span></button>`).join(" ")
    + ` <button class="chip" data-hooks aria-pressed="${state.hooks !== "off"}" title="Hook markers: notable only, all, or none (click to cycle)"><span class="tk-message">◆</span> ${HOOK_MODES[state.hooks][0]}<span class="n">${state.hooks === "all" ? allHooks.length : notableCount}</span></button>`;
  // Hooks closer than a marker's width share one marker, coloured by the most severe; its tooltip lists them all.
  const near = 12 / Math.max(200, $("list").clientWidth * 0.65) * 100;  // 12px as a share of the track
  const markers = hooks => {
    if (state.hooks === "off") return "";
    const clusters = [];
    hooks.filter(h => h.t >= lo && h.t <= hi && (state.hooks === "all" || NOTABLE.has(h.kind)))
      .sort((a, b) => a.t - b.t).forEach(h => {
        const last = clusters.at(-1);
        if (last && x(h.t) - x(last.hooks[0].t) < near) last.hooks.push(h); else clusters.push({hooks: [h]});
      });
    return clusters.map(({hooks: hs}) => {
      const kind = hs.map(h => h.kind).reduce((a, b) => SEVERITY.indexOf(b) > SEVERITY.indexOf(a) ? b : a);
      const tip = hs.slice(0, 6).map(h => `<div class="entry"><b>${clock(h.t)} · ${esc(h.event)} · ${esc(h.kind)}</b>${h.hook ? " · " + esc(h.hook) : ""}`
        + (h.texts[0] ? "\n" + esc(h.texts[0].slice(0, 240)) : "") + "</div>").join("")
        + (hs.length > 6 ? `<div class="entry">+${hs.length - 6} more</div>` : "");
      return `<div class="hook k-${kind}${hs.length > 1 ? " multi" : ""}" style="left:${x(hs[0].t)}%" data-tip="${esc(tip)}"></div>`;
    }).join("");
  };

  const q = state.q.toLowerCase();
  const shown = DATA.agents.filter(a => !state.hide.has(a.status) &&
    (!q || [a.description, a.type, a.model, a.result, a.group_label].join(" ").toLowerCase().includes(q)));
  // Agents launched from the same message share a group; one launched alone is a plain row.
  const groups = [];
  shown.forEach(a => { let g = groups.find(g => g.name === a.group); if (!g) groups.push(g = {name: a.group, label: a.group_label, agents: []}); g.agents.push(a); });
  // Finished groups start collapsed in long runs; a search, or the user's own choice, overrides that.
  const groupOpen = g => q ? true : state.groups.has(g.name) ? state.groups.get(g.name)
    : shown.length <= 6 || groupStatus(g.agents) !== "done";

  const m = DATA.main;
  const mainRow = {...m, id: "main", description: "Main session", status: m.running ? "running" : "idle",
    type: "main session", model: m.models.join(", "), depth: 1, background: false};

  // Stalled agents and recent blocked or failed hooks; older ones only count in the stats.
  const urgent = h => (h.kind === "blocked" || h.kind === "error") && DATA.now - h.t < 900;
  const attention = [mainRow, ...DATA.agents].filter(a => a.status === "stalled" || a.hooks.some(urgent)).map(a =>
    `<button class="goto" data-goto="${esc(a.id)}">${esc(a.description)}</button> <small>(${a.status === "stalled" ? "stalled" : `hook ${a.hooks.filter(urgent).at(-1).kind}`})</small>`);
  $("attention").hidden = !attention.length;
  $("attention").innerHTML = attention.length ? `<b>Needs attention:</b> ${attention.join(", ")}` : "";
  const mainOpen = state.open.has("main");
  let html = `<div class="row axis"><span></span><span class="name" style="color:var(--muted);font-size:12px">${shown.length} of ${DATA.agents.length} agents</span>
      <div class="track">${tickTimes.map(t => `<div class="tick" style="left:${x(t)}%">${label(t)}</div>`).join("")}</div><span class="num">active</span></div>
    <div class="row agent" data-id="main" tabindex="0" role="button" aria-expanded="${mainOpen}">
      <span class="badge s-${mainRow.status}" title="${m.running ? "Main session active" : "Main session idle"}">${statusOf(mainRow)[1]}</span>
      <span class="name">Main session<small>${esc(mainRow.model.replace(/^claude-/, ""))}</small></span>
      <div class="track">${grid}${bars(mainRow, "b-main")}${markers(m.hooks)}</div>
      <span class="num">${dur(m.active)}</span></div>${mainOpen ? detail(mainRow) : ""}`;
  if (!DATA.agents.length) html += `<div class="empty">No subagents in this session yet.</div>`;
  else if (!shown.length) html += `<div class="empty">No agents match the filters.</div>`;
  // A collapsible header row; collapsed, it draws all its agents' bars and hooks on one line.
  const hhmm = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const header = (key, label, agents, open, note) => {
    const track = open ? "" : agents.map(a => bars(a, `b-${a.status}`)).join("")
      + markers(agents.flatMap(a => a.hooks));
    return `<div class="row grouprow" data-group="${esc(key)}" tabindex="0" role="button" aria-expanded="${open}">
      <span class="badge chev">${open ? "▾" : "▸"}</span>
      <span class="name" title="${esc(label)}">${esc(label)}<small>${agents.length} agents · ${groupStatus(agents) === "done" ? "all done" : tally(agents)} · ${note}</small></span>
      <div class="track">${grid}${track}</div>
      <span class="num">${dur(agents.reduce((s, a) => s + a.active, 0))}</span></div>`;
  };
  const agentRow = a => {
    const open = state.open.has(a.id);
    return `<div class="row agent" data-id="${a.id}" tabindex="0" role="button" aria-expanded="${open}">
      <span class="badge s-${a.status}" title="${STATUS[a.status][0]}">${STATUS[a.status][1]}</span>
      <span class="name" title="${esc(a.description)}">${"&nbsp;&nbsp;".repeat(Math.max(0, a.depth - 1))}${esc(a.description)}<small>${esc(a.model.replace(/^claude-/, ""))}</small></span>
      <div class="track">${grid}${bars(a, `b-${a.status}${a.status === "running" ? " running" : ""}`)}${markers(a.hooks)}</div>
      <span class="num">${dur(a.active)}</span></div>${open ? detail(a) : ""}`;
  };
  const unit = g => {
    if (g.agents.length === 1) return agentRow(g.agents[0]);
    const open = groupOpen(g);
    return header(g.name, g.label, g.agents, open, hhmm(g.agents[0].start)) + (open ? g.agents.map(agentRow).join("") : "");
  };
  // Long runs fold finished work before the latest KEEP groups or rows into one "Earlier" row.
  // Anything unfinished stays visible, and a search shows every match.
  const foldable = q ? [] : groups.slice(0, -KEEP).filter(g => groupStatus(g.agents) === "done");
  const folded = new Set(foldable.length >= 3 ? foldable : []);
  foldedIds = new Set([...folded].flatMap(g => g.agents.map(a => a.id)));
  if (folded.size) {
    const agents = [...folded].flatMap(g => g.agents), open = state.groups.get(EARLIER) === true;
    const last = Math.max(...agents.map(a => a.end));
    const day = t => new Date(t * 1000).toLocaleDateString([], {month: "short", day: "numeric"});
    const span = day(agents[0].start) === day(last) ? `${hhmm(agents[0].start)}–${hhmm(last)}`
      : `${day(agents[0].start)} ${hhmm(agents[0].start)} – ${day(last)} ${hhmm(last)}`;
    html += header(EARLIER, "Earlier", agents, open, span)
      + (open ? [...folded].map(unit).join("") : "");
  }
  html += groups.filter(g => !folded.has(g)).map(unit).join("");
  const scrolls = new Map([...$("list").querySelectorAll("[data-scroll]")].map(el => [el.dataset.scroll, el.scrollTop]));
  $("list").innerHTML = html;
  for (const d of $("list").querySelectorAll("details[data-key]")) d.open = state.details.has(d.dataset.key);
  balance();
  for (const el of $("list").querySelectorAll("[data-scroll]")) el.scrollTop = scrolls.get(el.dataset.scroll) || 0;

  const agentSecs = DATA.agents.reduce((s, a) => s + a.active, 0);
  $("sub").textContent = `${DATA.project} / ${DATA.session}`;
  const blocked = allHooks.filter(h => h.kind === "blocked").length;
  const totals = `Agent time ${dur(agentSecs)} · agent output tokens ${kt(DATA.agents.reduce((s, a) => s + a.tokens_out, 0))}`
    + ` · main output tokens ${kt(m.tokens_out)} · ${allHooks.length} hook events`;
  $("stats").innerHTML = [
    ["Session", `${dur(m.active)} active over ${dur((m.running ? DATA.now : m.end) - m.start)}`],
    ["Agents", tally(DATA.agents) || "none", totals],
    ...(blocked ? [["Blocked hooks", blocked]] : []),
  ].map(([k, v, title]) => `<span${title ? ` title="${esc(title)}"` : ""}>${k}: <b>${v}</b></span>`).join("");
  if (state.view === "outputs") renderOutputs();
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
window.addEventListener("resize", () => { if (DATA) render(); });

function detail(a) {
  const feed = a.activity.slice().reverse().map(([t, tool, what]) =>
    `<li><span class="t">${clock(t)}</span><span class="tool" title="${esc(tool)}">${esc(tool.replace(/^mcp__.*?__/, ""))}</span><span class="what" title="${esc(what)}">${esc(what)}</span></li>`).join("");
  const tools = Object.entries(a.tools).sort((p, q) => q[1] - p[1]).map(([k, v]) => `${k} ${v}`).join(", ");
  const hooks = a.hooks.slice().reverse().map((h, i) => `<li><div class="head"><span class="t">${clock(h.t)}</span>
      <span title="${esc(h.event)}">${esc(h.event)}</span><span class="tk-${h.kind}">${esc(h.kind)}</span>
      <span title="${esc(h.hook)}">${esc(h.hook)}</span><span class="t">${h.ms ? dur(h.ms / 1000) : ""}</span></div>
      ${h.texts.length ? `<details data-key="hook-${a.id}-${h.t}-${i}"><summary>${esc(h.texts[0].split("\n")[0].slice(0, 120))}</summary><pre>${esc(h.texts.join("\n\n"))}</pre></details>` : ""}</li>`).join("");
  const prompt = a.id === "main" ? "First prompt" : "Prompt";
  return `<div class="detail">
  <p class="statusline"><span class="s-${a.status}">${statusOf(a)[0]}</span> · ${esc(a.type)}${a.background ? " · background" : ""} · ${esc(a.model)}
    · started ${clock(a.start)} · ${dur(a.active)} active${a.segments.length > 1 ? ` in ${a.segments.length} parts` : ""} · last activity ${clock(a.end)}</p>
  <div class="cols">
    <section><h3>Latest activity</h3>${feed ? `<ol class="feed" data-scroll="feed-${a.id}">${feed}</ol>` : `<p class="empty">No tool calls yet.</p>`}</section>
    <section><h3>${a.status === "done" ? "Result" : "Latest reply"}</h3>${a.final ? `<pre data-scroll="final-${a.id}">${esc(a.final)}</pre>` : `<p class="empty">Nothing yet.</p>`}</section>
  </div>
  <details class="more" data-key="more-${a.id}"><summary>More: tokens, tools, ${prompt.toLowerCase()}, hooks (${a.hooks.length})</summary>
    <dl><dt title="Input includes cached context re-read on each turn">Tokens</dt><dd>${kt(a.tokens_in)} in / ${kt(a.tokens_out)} out</dd>
      <dt>Tools</dt><dd>${esc(tools)}</dd>
      <dt>Outputs</dt><dd>${a.files.length} file${a.files.length === 1 ? "" : "s"} changed · ${a.commits.length} commit${a.commits.length === 1 ? "" : "s"}${a.branch ? ` · branch ${esc(a.branch)}` : ""}${a.prs.map(p => ` · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.url.replace(/^.*\/pull\//, "PR #"))}</a>`).join("")}</dd>
      <dt>Transcript</dt><dd>${esc(a.transcript)}</dd></dl>
    <details data-key="prompt-${a.id}"><summary>${prompt}</summary><pre data-scroll="prompt-${a.id}">${esc(a.prompt)}</pre></details>
    <section class="hookbox"><h3>Hooks (${a.hooks.length})</h3>${hooks ? `<ol class="hooks" data-scroll="hooks-${a.id}">${hooks}</ol>` : `<p class="empty">No hook events recorded.</p>`}</section>
  </details></div>`;
}

const ROWS = ".agent, .grouprow";
const rowSelector = row => "group" in row.dataset ? `.grouprow[data-group="${CSS.escape(row.dataset.group)}"]`
  : `.agent[data-id="${CSS.escape(row.dataset.id)}"]`;
function toggle(row) {
  if ("group" in row.dataset) state.groups.set(row.dataset.group, row.getAttribute("aria-expanded") !== "true");
  else { const id = row.dataset.id; state.open.has(id) ? state.open.delete(id) : state.open.add(id); }
  render();
}
$("list").addEventListener("click", e => { const row = e.target.closest(ROWS); if (row) toggle(row); });
$("list").addEventListener("keydown", e => {
  const row = e.target.closest(ROWS);
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); const sel = rowSelector(row); toggle(row); document.querySelector(sel)?.focus(); }
});
// Open an agent's row on the timeline, from the attention line or the Outputs tab.
function gotoAgent(e) {
  const id = e.target.closest("[data-goto]")?.dataset.goto; if (!id) return;
  const a = DATA.agents.find(a => a.id === id);
  if (a) { state.groups.set(a.group, true); state.hide.delete(a.status); }
  if (foldedIds.has(id)) state.groups.set(EARLIER, true);
  state.open.add(id); state.q = ""; $("q").value = "";
  setView("timeline");
  document.querySelector(`.agent[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({block: "center"});
}
$("attention").addEventListener("click", gotoAgent);
$("outputs").addEventListener("click", e => {
  const mode = e.target.closest("[data-mode]"), dir = e.target.closest("[data-dir]"), file = e.target.closest("[data-file]");
  if (mode) { state.fileMode = mode.dataset.mode; renderOutputs(); }
  else if (dir) { state.folders.set(dir.dataset.dir, dir.dataset.open !== "true"); renderOutputs(); }
  else if (file) selectFile(file.dataset.file);
  else gotoAgent(e);
});
function setView(view) {
  state.view = view;
  document.querySelector("main").classList.toggle("view-outputs", view === "outputs");
  for (const t of document.querySelectorAll(".tab")) t.setAttribute("aria-selected", String(t.dataset.view === view));
  $("q").placeholder = view === "outputs" ? "Filter files, commits, agents" : "Filter agents";
  if (DATA) render();
}
document.querySelector(".tabs").addEventListener("click", e => { const t = e.target.closest(".tab"); if (t) setView(t.dataset.view); });
$("list").addEventListener("toggle", e => {
  const d = e.target; if (!d.dataset?.key) return;
  d.open ? state.details.add(d.dataset.key) : state.details.delete(d.dataset.key);
  balance();
}, true);
$("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip"); if (!chip) return;
  if ("hooks" in chip.dataset) state.hooks = HOOK_MODES[state.hooks][1];
  else { const k = chip.dataset.status; state.hide.has(k) ? state.hide.delete(k) : state.hide.add(k); }
  render();
});
$("q").addEventListener("input", e => { state.q = e.target.value; render(); });

// Hook and bar tooltips show at once (a native title waits about a second) and stay inside the window.
$("list").addEventListener("mousemove", e => {
  const hook = e.target.closest(".hook, .bar[data-tip]"), tip = $("tip");
  if (!hook) { tip.hidden = true; return; }
  if (tip.hidden || tip.dataset.for !== hook.dataset.tip) { tip.innerHTML = hook.dataset.tip; tip.dataset.for = hook.dataset.tip; tip.hidden = false; }
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.max(8, Math.min(e.clientX + 14, innerWidth - w - 8))}px`;
  tip.style.top = `${e.clientY + 18 + h > innerHeight - 8 ? e.clientY - h - 10 : e.clientY + 18}px`;
});
$("list").addEventListener("mouseleave", () => { $("tip").hidden = true; });
$("range").addEventListener("change", e => { state.range = e.target.value; render(); });

// Full width is remembered in this browser (per server port, since the port is the origin).
const WIDE_KEY = "agent-timeline-wide";
function setWide(on) {
  document.querySelector("main").classList.toggle("wide", on);
  $("wide").setAttribute("aria-pressed", String(on));
  try { localStorage.setItem(WIDE_KEY, on ? "1" : "0"); } catch {}
}
try { setWide(localStorage.getItem(WIDE_KEY) === "1"); } catch { setWide(false); }
$("wide").addEventListener("click", () => { setWide($("wide").getAttribute("aria-pressed") !== "true"); if (DATA) render(); });

function setLive(ok) {
  $("live").className = "live" + (ok ? "" : " off");
  $("live").innerHTML = LIVE ? `<span class="dot"></span>${ok ? "Live" : "Disconnected (the server may have stopped; run /agent-timeline again)"} · updated ${clock(DATA.now)}`
    : `Snapshot taken ${clock(DATA.now)}`;
}
// The live server hands out data only with the per-run token from the URL fragment, which never leaves the browser.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || "";
async function poll() {
  try {
    const res = await fetch(`data.json${location.search}`, {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}});
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


def is_shared(session):
    """Only sessions under ~/.claude/projects can be served by id from the shared server."""
    return session.resolve().parent.parent == PROJECTS.resolve() and SESSION_ID.fullmatch(session.stem)


def find_server():
    """The shared server's state, if one is running this script's version and answers with its token."""
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        request = urllib.request.Request(f"http://127.0.0.1:{int(state['port'])}/health",
                                         headers={"X-Timeline-Token": state["token"]})
        with urllib.request.urlopen(request, timeout=2) as response:
            health = json.load(response)
        return state if health.get("app") == "agent-timeline" and health.get("version") == VERSION else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_state(state):
    """Record the shared server where only this user can read it (the file holds the token)."""
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(STATE.parent, 0o700)
    temp = STATE.with_name(f"server.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(temp, STATE)


def forget_state():
    try:
        if json.loads(STATE.read_text(encoding="utf-8")).get("pid") == os.getpid():
            STATE.unlink()
    except (OSError, ValueError):
        pass


def session_url(port, session, token):
    return f"http://127.0.0.1:{port}/?s={session.stem}#t={token}"


def open_private(url, keep_seconds=10):
    """Open url in the browser without putting it (and its token) on the browser's command line.

    Other local users can read process command lines on some systems (Linux /proc). Instead,
    write a redirect page only this user can read, open that file, and delete it shortly after.
    """
    folder = tempfile.mkdtemp(prefix="agent-timeline-")  # owner-only on POSIX; per-user %TEMP% on Windows
    launcher = Path(folder) / "open.html"
    target = json.dumps(url).replace("</", "<\\/")
    fd = os.open(launcher, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset=utf-8><script>location.replace({target})</script>")
    webbrowser.open(launcher.as_uri())
    # Non-daemon, so a process that is about to exit still waits to clean up.
    threading.Timer(keep_seconds, shutil.rmtree, args=(folder,), kwargs={"ignore_errors": True}).start()


def serve(session, port, open_browser, idle_minutes):
    """Serve the live page, reusing the shared server when one is already running.

    Transcript data needs the server's token, and only same-host requests are answered, so other
    local users and DNS-rebinding web pages can't read it. The shared server serves any session
    under ~/.claude/projects by id. An open page polls every 5 seconds; once no page has asked
    for idle_minutes, the server exits, so forgotten servers don't pile up.
    """
    shared = port == 0 and is_shared(session)
    existing = find_server() if shared else None
    if existing:
        url = session_url(existing["port"], session, existing["token"])
        print(f"Serving {session} at {url} (existing server, pid {existing['pid']})", flush=True)
        if open_browser:
            open_private(url)
        return

    token = secrets.token_urlsafe(32)
    sessions = {session.stem: session}

    def session_for(query):
        """The session a page asked for: the started one, or any transcript under PROJECTS by id."""
        requested = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("s", session.stem)
        if requested not in sessions and shared and SESSION_ID.fullmatch(requested):
            hits = list(PROJECTS.glob(f"*/{requested}.jsonl"))
            if len(hits) == 1:
                sessions[requested] = hits[0]
        return sessions.get(requested)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (origin is not None and origin not in {f"http://{h}" for h in hosts}):
                self.send_error(403)
                return
            route, _, query = self.path.partition("?")
            if route in ("/data.json", "/health", "/file.json"):
                if not hmac.compare_digest(self.headers.get("X-Timeline-Token", ""), token):
                    self.send_error(403)
                    return
                if route == "/health":
                    body = json.dumps({"app": "agent-timeline", "version": VERSION, "pid": os.getpid()}).encode()
                elif route == "/file.json":
                    target = session_for(query)
                    rel = urllib.parse.parse_qs(query).get("path", [""])[0]
                    detail = file_detail(target, rel) if target and rel else None
                    if detail is None:
                        self.send_error(404)
                        return
                    body = json.dumps(detail).encode()
                else:
                    target = session_for(query)
                    if not target:
                        self.send_error(404)
                        return
                    body = json.dumps(collect(target)).encode()
                ctype = "application/json"
            elif route in ("/", "/index.html"):
                body, ctype = page(None, live=True).encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.server.last_seen = time.monotonic()  # only accepted requests keep the server alive
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1  # handle_request returns at least this often, so the idle check runs
    server.last_seen = time.monotonic()
    if shared:
        save_state({"port": server.server_port, "token": token, "pid": os.getpid(), "version": VERSION})
    url = session_url(server.server_port, session, token)
    stop_note = f"stops after {idle_minutes:g} minutes with no page open" if idle_minutes > 0 else "runs until stopped"
    print(f"Serving {session} at {url} (new server, pid {os.getpid()}; {stop_note})", flush=True)
    if open_browser:
        open_private(url)
    try:
        while idle_minutes <= 0 or time.monotonic() - server.last_seen < idle_minutes * 60:
            server.handle_request()
        print(f"No page open for {idle_minutes:g} minutes; stopped.", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if shared:
            forget_state()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", help="session .jsonl, session id, or project folder")
    parser.add_argument("-o", "--output", help="HTML file to write (default: system temp folder)")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    parser.add_argument("--serve", action="store_true", help="serve a live page that refreshes every 5 seconds")
    parser.add_argument("--port", type=int, default=0,
                        help="run a separate server on this port instead of the shared one (default: shared, random port)")
    parser.add_argument("--idle-exit", type=float, default=10, metavar="MINUTES",
                        help="with --serve, stop after this many minutes with no page open (default: 10; 0 never stops)")
    args = parser.parse_args(argv)

    session = resolve(args.target)
    if args.serve:
        serve(session, args.port, args.open, args.idle_exit)
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
