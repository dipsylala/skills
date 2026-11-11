# Skills

A collection of [Agent Skills](https://agentskills.io) - an open standard supported by VS Code, Cursor, Claude Code, Claude, Roo Code, Gemini CLI, and more.

## Installation

Install from this repository with the Skills CLI:

```bash
npx skills add dipsylala/skills
```

List available skills before installing:

```bash
npx skills add dipsylala/skills --list
```

Install a specific skill:

```bash
npx skills add dipsylala/skills --skill code-judo-review
```

By default, skills are installed at project scope. Use `--global` to install them for all projects supported by your agent.

Manual-only skills set `disable-model-invocation: true` in `SKILL.md` and `allow_implicit_invocation: false` in `agents/openai.yaml`. An agent that honours neither setting may invoke them automatically.

## Recommended Workflow

Use these skills in the following order:

| Step | Skill | Purpose |
| --- | --- | --- |
| 1 | [/grill-me](./grill-me/SKILL.md) or [/grill-with-docs](./grill-with-docs/SKILL.md) | Stress-test the plan and agree consequential decisions. Choose `/grill-with-docs` to also record ADRs and a domain glossary. |
| 2 | [/to-spec](./to-spec/SKILL.md) | Capture agreed outcomes, decisions, acceptance criteria, and unresolved questions in a spec. |
| 3 | [/to-tickets](./to-tickets/SKILL.md) | Break the spec into verifiable tickets with explicit dependencies and review the breakdown before publication. |
| 4 | [/pr](./pr/SKILL.md) | After implementing and validating the tickets, write the PR body from the actual changes and observed evidence. |
| 5 | [/retro](./retro/SKILL.md) | Review the coding session and recommend improvements to the agent's environment for future work. |

Alternatively, run [/do-my-work](./do-my-work/SKILL.md) to drive steps 1–4, which offers these skills at the relevant points.

These six skills are adapted from [Matt Pocock's skills](https://github.com/mattpocock/skills) and have been revised for this collection. The `/pr` visual examples also draw on Dex Horthy's `show-me` skill; see [PR credits](./pr/CREDITS.md).

## Available Skills

| Skill | Description |
| ------- | ------------- |
| [agent-timeline](./agent-timeline/SKILL.md) | Show a live timeline of a Claude Code session's subagents and hook events: which agents are running, quiet, stalled, or done, with each one's recent activity, result, and hooks. Reads Claude Code's own transcripts and changes nothing about how agents run. Claude Code only; requires Python 3.9 or later. |
| [code-judo-review](./code-judo-review/SKILL.md) | Run an extremely strict, review-only maintainability review of a branch's changes for code-judo restructurings, spaghetti growth, file size, and type boundaries, reported as fix-ready findings and a verdict. Adapted from [Cursor Team - Thermo-nuclear code quality review](https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/thermo-nuclear-code-quality-review); see [credits](./code-judo-review/CREDITS.md) for language-reference sources. |
| [de-ai-doc](./de-ai-doc/SKILL.md) | Update one or more documentation files in place to replace AI-heavy writing with concise, natural, technically precise prose while preserving facts, code, structure, and author intent. Adapts the editorial prompt taxonomy from [AUAggy/deslop](https://github.com/AUAggy/deslop/), used under the [MIT License](https://github.com/AUAggy/deslop/blob/main/LICENSE), and patterns from [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing); see [credits](./de-ai-doc/CREDITS.md). |
| [do-my-work](./do-my-work/SKILL.md) | Take a software task from idea, bug report, tracker issue, or spec through clarification, design, implementation, testing, and review, adapting the process and agent team to the work. Keeps each effort's artifacts in `docs/work/<ticket-or-feature>/`, and offers `/grill-me`, `/grill-with-docs`, `/to-spec`, `/to-tickets`, `/pr`, and Matt Pocock's [wayfinder](https://github.com/mattpocock/skills/tree/main/skills/engineering/wayfinder) when installed. |
| [grill-me](./grill-me/SKILL.md) | Interview the user about a plan or design until consequential decisions are agreed or explicitly deferred. Adapted from Matt Pocock's [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me); see [credits](./grill-me/CREDITS.md). |
| [grill-with-docs](./grill-with-docs/SKILL.md) | Interview the user while recording agreed architectural decisions and domain vocabulary in ADRs and a glossary. Adapted from Matt Pocock's [grill-with-docs](https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-with-docs); see [credits](./grill-with-docs/CREDITS.md). |
| [pr](./pr/SKILL.md) | Write a concise PR body with a clear change summary, observed evidence, and merge risks. Adapted from Matt Pocock's [pr](https://github.com/mattpocock/skills/tree/main/skills/engineering/pr); see [credits](./pr/CREDITS.md). |
| [retro](./retro/SKILL.md) | Review a coding session and recommend concrete improvements to the agent's environment. Adapted from Matt Pocock's [retro](https://github.com/mattpocock/skills/tree/main/skills/engineering/retro); see [credits](./retro/CREDITS.md). |
| [to-spec](./to-spec/SKILL.md) | Record agreed decisions in a spec and save it locally or publish to a configured tracker. Adapted from Matt Pocock's [to-spec](https://github.com/mattpocock/skills/tree/main/skills/engineering/to-spec); see [credits](./to-spec/CREDITS.md). |
| [to-tickets](./to-tickets/SKILL.md) | Split agreed work into verifiable tickets with explicit dependencies for local files or a configured tracker. Adapted from Matt Pocock's [to-tickets](https://github.com/mattpocock/skills/tree/main/skills/engineering/to-tickets); see [credits](./to-tickets/CREDITS.md). |
| [prompt-audit](./prompt-audit/SKILL.md) | Write or audit any document an agent consumes: prompts, system prompts, skills, and `AGENTS.md` / `CLAUDE.md`. Audits cover contradictions, ambiguity, persona consistency, cognitive load, semantic coverage, and agent-writing practice. Adapts Microsoft's [vscode-chat-customizations-evaluation](https://github.com/microsoft/vscode-chat-customizations-evaluation) analysis dimensions and Matt Pocock's [writing-for-agents](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents); see [credits](./prompt-audit/CREDITS.md). |
| [sphinx](./sphinx/SKILL.md) | Review technical documentation through one focused question at a time. Use when the user wants Socratic critique while retaining authorship of the draft. Adapted from [Daniel Miessler's Socrates Agent](https://danielmiessler.com/blog/the-socrates-agent), refocused for technical documentation review; see [credits](./sphinx/CREDITS.md). |
