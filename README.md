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
npx skills add dipsylala/skills --skill code-guardian
```

By default, skills are installed at project scope. Use `--global` to install them for all projects supported by your agent.

## Recommended Workflow

Use these skills in the following order:

| Step | Skill | Purpose |
| --- | --- | --- |
| 1 | [/grill-me](./grill-me/SKILL.md) or [/grill-with-docs](./grill-with-docs/SKILL.md) | Stress-test the plan and agree consequential decisions. Choose `/grill-with-docs` to also record ADRs and a domain glossary. |
| 2 | [/to-spec](./to-spec/SKILL.md) | Capture agreed outcomes, decisions, acceptance criteria, and unresolved questions in a spec. |
| 3 | [/to-tickets](./to-tickets/SKILL.md) | Break the spec into verifiable tickets with explicit dependencies and review the breakdown before publication. |
| 4 | [/pr](./pr/SKILL.md) | After implementing and validating the tickets, write the PR body from the actual changes and observed evidence. |
| 5 | [/retro](./retro/SKILL.md) | Review the coding session and recommend improvements to the agent's environment for future work. |

These six skills are adapted from [Matt Pocock's skills](https://github.com/mattpocock/skills) and have been revised for this collection. The `/pr` visual examples also draw on Dex Horthy's `show-me` skill; see [PR credits](./pr/CREDITS.md).

## Available Skills

| Skill | Description |
| ------- | ------------- |
| [code-guardian](./code-guardian/SKILL.md) | **Proof of concept.** Audits LLM-generated code edits for adherence to surrounding code conventions, OWASP Top 10:2025 application security, and OWASP LLM security practices before applying them. Use as a heuristic guardrail alongside deterministic scanners, linting, and tests. Prose cannot enforce a pre-apply gate; see [the rationale for moving this to a hook](./code-guardian/README.md). |
| [continuation](./continuation/SKILL.md) | Create compact continuation notes so another agent or future session can resume work with minimal rediscovery. |
| [de-ai-doc](./de-ai-doc/SKILL.md) | Update one or more documentation files in place to replace AI-heavy writing with concise, natural, technically precise prose while preserving facts, code, structure, and author intent. Adapts the editorial prompt taxonomy from [AUAggy/deslop](https://github.com/AUAggy/deslop/), used under the [MIT License](https://github.com/AUAggy/deslop/blob/main/LICENSE) |
| [grill-me](./grill-me/SKILL.md) | Interview the user about a plan or design until consequential decisions are agreed or explicitly deferred. |
| [grill-with-docs](./grill-with-docs/SKILL.md) | Interview the user while recording agreed architectural decisions and domain vocabulary in ADRs and a glossary. |
| [pr](./pr/SKILL.md) | Write a concise PR body with a clear change summary, observed evidence, and merge risks. |
| [retro](./retro/SKILL.md) | Review a coding session and recommend concrete improvements to the agent's environment. |
| [to-spec](./to-spec/SKILL.md) | Record agreed decisions in a spec and save it locally or publish to a configured tracker. |
| [to-tickets](./to-tickets/SKILL.md) | Split agreed work into verifiable tickets with explicit dependencies for local files or a configured tracker. |
| [prompt-audit](./prompt-audit/SKILL.md) | Analyse a prompt or system instruction set for quality issues across five dimensions: contradictions, ambiguity, persona consistency, cognitive load, and semantic coverage. Inspired by the LLM-powered analysis dimensions (contradictions, ambiguity, persona consistency, cognitive load, semantic coverage) from Microsoft's [vscode-chat-customizations-evaluation](https://github.com/microsoft/vscode-chat-customizations-evaluation), used under the [MIT License](https://github.com/microsoft/vscode-chat-customizations-evaluation/blob/main/LICENSE). |
| [sphinx](./sphinx/SKILL.md) | Review technical documentation through one focused question at a time. Use when the user wants Socratic critique while retaining authorship of the draft. Adapted from [Daniel Miessler's Socrates Agent](https://danielmiessler.com/blog/the-socrates-agent), refocused for technical documentation review. |
| [thermo-nuclear-code-quality-review](./thermo-nuclear-code-quality-review/SKILL.md) | Run an extremely strict maintainability review for abstraction quality, giant files, and spaghetti-condition growth. Based on [Cursor Team - Thermo-nuclear code quality review](https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/thermo-nuclear-code-quality-review) |
| [write-a-prd](./write-a-prd/SKILL.md) | Create a PRD from user context, focused questions, and available repository evidence, with scope and acceptance criteria. Based on [Write A PRD With The /write-a-prd Skill by Matt Pocock](https://www.aihero.dev/write-a-prd-with-the-write-a-prd-skill-4kldl) |
| [write-a-skill](./write-a-skill/SKILL.md) | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |
| [writing-for-agents](./writing-for-agents/SKILL.md) | Writing documents for agents. Based on [Writing-For-Agents by Matt Pocock](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents) |
