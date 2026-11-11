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
PAGE_DIR = Path(__file__).with_name("page")
PAGE_FILES = ("index.html", "style.css", "app.js")
# An updated script or page starts a fresh shared server instead of reusing one running older code.
VERSION = hashlib.sha256(b"".join(p.read_bytes() for p in [Path(__file__), *(PAGE_DIR / n for n in PAGE_FILES)])).hexdigest()[:12]
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


_titles = {}


def session_card(path):
    """Title, project folder, last prompt and size of one session, read from the ends of its transcript (cached)."""
    stat = path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _titles.get(path)
    if cached and cached[0] == key:
        return cached[1]
    title = last_prompt = cwd = first_prompt = ""
    with open(path, "rb") as f:
        head = f.read(65536)
        f.seek(max(0, stat.st_size - 262144))
        tail = f.read()
    for line in head.splitlines():
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # a line cut off at the end of the read
        cwd = cwd or entry.get("cwd") or ""
        if entry.get("type") == "user" and not first_prompt:
            first_prompt = text_of((entry.get("message") or {}).get("content"))
    for line in tail.splitlines():
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if entry.get("type") == "custom-title":
            title = entry.get("customTitle") or title
        elif entry.get("type") == "last-prompt":
            last_prompt = entry.get("lastPrompt") or last_prompt
    subagents = path.parent / path.stem / "subagents"
    # Slash commands are stored as markup ("<command-message>...</command-message> <command-name>/x</command-name>").
    # App-injected <system-reminder> blocks are not what the user typed.
    prompt = re.sub(r"<command-message>.*?</command-message>|<system-reminder>.*?(?:</system-reminder>|$)", "",
                    last_prompt or first_prompt, flags=re.S)
    prompt = " ".join(re.sub(r"</?(?:local-)?command-[a-z-]+>", " ", prompt).split())
    card = {"id": path.stem, "project": cwd or path.parent.name, "title": title,
            "prompt": prompt[:300], "mtime": stat.st_mtime,
            "agents": len(list(subagents.glob("agent-*.jsonl"))) if subagents.is_dir() else 0}
    _titles[path] = (key, card)
    return card


def list_sessions(limit=300):
    """The user's sessions, most recently active first."""
    paths = [p for p in PROJECTS.glob("*/*.jsonl") if SESSION_ID.fullmatch(p.stem)]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [session_card(p) for p in paths[:limit]]


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
        "title": session_card(session)["title"],
        "main": {"running": now - main["end"] <= RUNNING_WINDOW, "transcript": str(session), "branch": "",
                 **outputs(main, [main["cwd"]]),
                 **{k: main[k] for k in ("start", "end", "segments", "active", "models", "tokens_in", "tokens_out",
                                         "tools", "prompt", "final", "activity", "hooks", "cwd")}},
        "chapters": main["chapters"],
        "agents": agents,
    }


def page(data, live):
    """The page, with its stylesheet and script put inline so a snapshot is one self-contained file."""
    html, css, js = ((PAGE_DIR / name).read_text(encoding="utf-8") for name in PAGE_FILES)
    payload = json.dumps(data).replace("</", "<\\/")
    js = js.replace("__LIVE__", "true" if live else "false").replace("__DATA__", payload)  # the data goes in last
    return html.replace("/*__STYLE__*/", css).replace("/*__SCRIPT__*/", js)


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
            if route in ("/data.json", "/health", "/file.json", "/sessions.json"):
                if not hmac.compare_digest(self.headers.get("X-Timeline-Token", ""), token):
                    self.send_error(403)
                    return
                if route == "/health":
                    body = json.dumps({"app": "agent-timeline", "version": VERSION, "pid": os.getpid()}).encode()
                elif route == "/sessions.json":
                    # The shared server can show any session under ~/.claude/projects; a separate one only its own.
                    body = json.dumps(list_sessions() if shared else [session_card(session)]).encode()
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
