# Skills

A collection of [Agent Skills](https://agentskills.io) — an open standard supported by VS Code, Cursor, Claude Code, Claude, Roo Code, Gemini CLI, and more.

## Available Skills

| Skill | Description |
| ------- | ------------- |
| [code-guardian](./code-guardian/SKILL.md) | Audits LLM-generated code edits for adherence to surrounding code conventions and OWASP Top 10 security practices before applying them. Blocks and self-corrects violations inline. |
| [grill-me](./grill-me/SKILL.md) | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| [prompt-audit](./prompt-audit/SKILL.md) | Analyse a prompt or system instruction set for quality issues across five dimensions: contradictions, ambiguity, persona consistency, cognitive load, and semantic coverage. |
| [write-a-prd](./write-a-prd/SKILL.md) | Create a PRD through user interview, codebase exploration, and module design, then submit as a GitHub issue. |
| [write-a-skill](./write-a-skill/SKILL.md) | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |

## Credits

Based on Matt Pocock's work, with additions:

- [My grill-me skill has gone viral](https://www.aihero.dev/my-grill-me-skill-has-gone-viral)
- [mattpocock/skills](https://github.com/mattpocock/skills)

The `prompt-audit` skill is inspired by the LLM-powered analysis dimensions (contradictions, ambiguity, persona consistency, cognitive load, semantic coverage) from Microsoft's [vscode-chat-customizations-evaluation](https://github.com/microsoft/vscode-chat-customizations-evaluation), used under the [MIT License](https://github.com/microsoft/vscode-chat-customizations-evaluation/blob/main/LICENSE).
