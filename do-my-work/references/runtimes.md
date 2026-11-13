# Runtime capabilities

At step 1, check what this runtime can do by looking at your own tools and settings, not by the client's name. The execution models in step 4 depend on it. For multi-stage work, record the result in the progress file.

| Capability | How to tell | Without it |
| --- | --- | --- |
| Spawn subagents | A tool that starts another agent with its own context | Work as the single owner (model A). For a review the skill requires, do it yourself as a separate pass against the reviewer brief, say it was not independent, offer an independent review in a fresh session, and continue without waiting |
| Run subagents in parallel | Several spawn calls in one message, or a background option | Run subagents one at a time; model C's workstreams run one after another |
| Isolate a subagent's files | A worktree or sandbox option on the spawn tool | Never run parallel writers in one checkout. If you can run git, create a worktree per engineer (`git worktree add`) and give each its path; otherwise run engineers one at a time |
| Choose each agent's model | A model parameter on the spawn tool, or agent definitions that set one | Every agent uses the session's model; skip step 4's "Choosing models" |
| Message or resume an agent | A tool that sends a follow-up to an agent you spawned | Spawn a fresh agent of that role with its earlier report and the new input |
| Ask the user mid-run | A question tool, or a live conversation | You are unattended ([autonomy.md](autonomy.md)) |

## Client notes

Reviewed November 2026. Clients change quickly; when these notes disagree with your tools, trust your tools.

- **Claude Code:** subagents through its agent tool, in parallel when several calls are sent in one message, with optional worktree isolation, a model per agent, and follow-up messages to running agents. `claude -p` and cloud sessions started without a user are unattended. `agent-timeline` works only here.
- **Codex:** subagents in local clients when the `multi_agent` feature is enabled, with custom agents that set their own model. `codex exec` and Codex cloud are unattended.
- **GitHub Copilot:** in VS Code agent mode and the Copilot CLI, subagents run through custom agents (`.agent.md`), which can set their own model. The cloud coding agent works from an issue and opens a pull request, so it is unattended.
- **Cursor:** subagents through its task tool, in the foreground or background, in parallel when several are started in one message, with a model set per agent in `.cursor/agents/*.md`. Background and cloud agents work in worktrees or on remote machines and are unattended.
- **Gemini CLI:** subagents and Agent Skills. `gemini -p` is unattended.
