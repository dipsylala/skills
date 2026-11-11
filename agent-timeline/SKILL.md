---
name: agent-timeline
description: Show a live timeline of a Claude Code session's subagents and hook events, with each agent's status, recent activity, and result, plus the files, commits, and pull requests they produced. Claude Code only.
disable-model-invocation: true
---

# Agent Timeline

Show the user a timeline of the subagents and hook events in a Claude Code session, and what they produced. The script reads the transcripts Claude Code already writes under `~/.claude/projects` and, for the live file viewer, the current copies of files those transcripts show agents changing; it writes nothing and changes nothing about how agents run. It does not read Codex or other tools' sessions.

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

- One row per agent: status (Running, Quiet, Stalled, Done), active time, and bars for when it was busy. The main session is the first row. Agents launched together (from the same message) form a group, labelled by the words their descriptions share; in longer runs, a group whose agents are all done starts collapsed to a single row. Beyond the latest 8 groups or rows, finished work folds into one "Earlier" row; anything unfinished stays visible, and a search shows every match.
- A "Needs attention" line names stalled agents and agents whose hooks blocked or failed in the last 15 minutes.
- Hook events as markers on each row. By default only blocked, failed, and message-producing hooks are marked; the Hooks chip switches to all hook runs, or none. Hooks that print nothing on events other than Stop are not recorded by Claude Code, so they cannot appear.
- Hovering a bar shows that agent's status, result, start and finish, tokens, and top tools; hovering a hook marker shows its output, with hooks too close to tell apart listed together.
- Clicking a row shows its latest tool calls and its result or latest reply; "More" adds tokens, tools, the prompt, and hook events.
- "Full width" removes the page's width limit, and the System / Light / Dark switch sets the colour theme; the browser remembers both while the same server runs.
- "← All sessions" steps out of the current session to a list of the user's sessions, grouped by project and most recent first, with each session's title, last prompt, agent count, and whether it is active now. Picking one switches the page to it. The full list needs the shared server; a server started with `--port` lists only its own session.
- The Outputs tab lists the files agents changed as a folder tree, marking files that several agents changed (and those changed by agents running at the same time, a likely merge conflict). Selecting a file shows each agent's changes as diffs, the file as it is now with syntax colouring, and, for markdown, a rendered preview. If the file no longer exists, the viewer rebuilds its last known version from the transcript. Commits and pull requests are listed below the tree. Files come from Write and Edit calls only; changes made through shell commands are not tracked. The file viewer needs the live view.

## Privacy

The page shows prompts, replies, commands, file paths, and file contents from the user's transcripts. The file viewer also reads current files from disk, but only files that the session's transcripts show agents changing; it refuses any other path. The page loads no third-party code: syntax colouring and markdown rendering are built in, markdown images are not loaded, and only http(s) and mailto links are clickable. The live server listens only on 127.0.0.1, uses a random port, and serves data only with the token in the URL. Because one server covers all of the user's sessions, its token opens any of them; the token is kept in `~/.claude/agent-timeline/server.json`, readable only by the user. `--open` keeps the token off the browser's command line, which other local users can read on some systems: it opens a short-lived redirect file that only the user can read. Do not paste the page's content or the URL anywhere outside this conversation.

## Limits

The transcript format and `CLAUDE_CODE_SESSION_ID` are not documented Claude Code interfaces, so a Claude Code update can break the script. If it fails to find a session, report the error and offer to run it with an explicit project folder or session ID.
