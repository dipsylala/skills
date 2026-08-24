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

## Available Skills

| Skill | Description |
| ------- | ------------- |
| [code-guardian](./code-guardian/SKILL.md) | Audits LLM-generated code edits for adherence to surrounding code conventions, OWASP Top 10:2025 application security, and OWASP LLM security practices before applying them. Use as a heuristic guardrail alongside deterministic scanners, linting, and tests. |
| [continuation](./continuation/SKILL.md) | Create compact continuation notes so another agent or future session can resume work with minimal rediscovery. |
| [de-ai-doc](./de-ai-doc/SKILL.md) | Update one or more documentation files in place to replace AI-heavy writing with concise, natural, technically precise prose while preserving facts, code, structure, and author intent. Adapts the editorial prompt taxonomy from [AUAggy/deslop](https://github.com/AUAggy/deslop/), used under the [MIT License](https://github.com/AUAggy/deslop/blob/main/LICENSE) |
| [grill-me](./grill-me/SKILL.md) | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Based on [Grill-Me by Matt Pocock](https://www.aihero.dev/my-grill-me-skill-has-gone-viral) |
| [prompt-audit](./prompt-audit/SKILL.md) | Analyse a prompt or system instruction set for quality issues across five dimensions: contradictions, ambiguity, persona consistency, cognitive load, and semantic coverage. Inspired by the LLM-powered analysis dimensions (contradictions, ambiguity, persona consistency, cognitive load, semantic coverage) from Microsoft's [vscode-chat-customizations-evaluation](https://github.com/microsoft/vscode-chat-customizations-evaluation), used under the [MIT License](https://github.com/microsoft/vscode-chat-customizations-evaluation/blob/main/LICENSE). |
| [thermo-nuclear-code-quality-review](./thermo-nuclear-code-quality-review/SKILL.md) | Run an extremely strict maintainability review for abstraction quality, giant files, and spaghetti-condition growth. Based on [Cursor Team - Thermo-nuclear code quality review](https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/thermo-nuclear-code-quality-review)|
| [write-a-prd](./write-a-prd/SKILL.md) | Create a PRD through user interview, codebase exploration, and module design, then submit as a GitHub issue. |
| [write-a-skill](./write-a-skill/SKILL.md) | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |
| [writing-for-agents](./writing-for-agents/SKILL.md) | Writing documents for agents. Based on [Writing-For-Agents by Matt Pocock](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-for-agents) |

