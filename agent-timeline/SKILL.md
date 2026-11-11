---
name: agent-timeline
description: Show a live timeline of a Claude Code session's subagents and hook events, with each agent's status, recent activity, and result. Claude Code only.
disable-model-invocation: true
---

# Agent Timeline

Show the user a timeline of the subagents and hook events in a Claude Code session. The script only reads the transcripts Claude Code already writes under `~/.claude/projects`; it changes nothing about how agents run. It does not read Codex or other tools' sessions.

## Run it

Start the live view in the background, from the skill's base directory:

```bash
python "<skill base directory>/scripts/agent-timeline.py" [TARGET] --serve --open
```

Use `python3` where `python` is not Python 3.9 or later.

- With no `TARGET`, it shows the current session. Pass a project folder (its latest session) or a session ID when the user names one.
- One server is shared across sessions. If one is already running, the command prints a URL for this session on it and exits at once; otherwise it starts the server and keeps running in the background.
- Wait for the line `Serving <transcript> at <url>`, then give the user that URL. It contains a per-run access token: give it only to the user, and never publish or upload it.
- `--open` also opens the URL in the user's default browser. Leave it out if the user only wants the link.
- When the user asks for a file instead of a live view, drop `--serve`: the script writes a one-off HTML page and prints its path. Use `-o <path>` to choose where.

The server stops itself 10 minutes after the last page showing any session is closed (`--idle-exit MINUTES` changes this; `0` keeps it running). When the user says they are done with it, stop the background task if this session started the server; otherwise it stops on its own. If the page shows "Disconnected", the server has stopped: run the command again for a new URL.

## What the page shows

- One row per agent: status (Running, Quiet, Stalled, Done), active time, and bars for when it was busy. The main session is the first row.
- Hook events as markers on each row: every Stop hook run, and any hook output on other events. Hooks that print nothing on events other than Stop are not recorded by Claude Code, so they cannot appear.
- Clicking a row shows its latest tool calls, its result or latest reply, its prompt, tokens, and hook events.

## Privacy

The page shows prompts, replies, commands, and file paths from the user's transcripts. The live server listens only on 127.0.0.1, uses a random port, and serves data only with the token in the URL. Because one server covers all of the user's sessions, its token opens any of them; the token is kept in `~/.claude/agent-timeline/server.json`, readable only by the user. Do not paste the page's content or the URL anywhere outside this conversation.

## Limits

The transcript format and `CLAUDE_CODE_SESSION_ID` are not documented Claude Code interfaces, so a Claude Code update can break the script. If it fails to find a session, report the error and offer to run it with an explicit project folder or session ID.
