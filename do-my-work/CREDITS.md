# Credits

do-my-work adopts ideas from the sources below, not their text. Each entry says what was taken.

## Team techniques

Reviewed November 2026.

- Cognition, "Don't Build Multi-Agents", on conflicting implicit decisions
  between parallel agents: the decisions log.
- Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (UC Berkeley), which
  found step repetition common and verification effective: the stall rule and
  completion gate.
- [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams): plan
  approval for teammates and investigation with competing hypotheses.
- [Agent Team Topologies, "Risky Refactor"](https://eirwin.github.io/agent-team-topologies/topologies/risky-refactor),
  GSD's plan checker, [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD),
  and [Gas Town](https://github.com/steveyegge/gastown): plan contents and
  approval criteria, the "won't touch" list, and `BLOCKED` reports that list
  what was tried.
- [shhac/skills competing-hypotheses](https://github.com/shhac/skills/tree/main/skills/competing-hypotheses),
  [rune](https://github.com/vinhnxv/rune/tree/main/plugins/rune/skills/debug),
  [npow/claude-skills deep-debug](https://github.com/npow/claude-skills/tree/main/deep-debug),
  [Compound Engineering](https://github.com/EveryInc/compound-engineering-plugin)
  `ce-debug`, and Gas City's read-only review check: isolated investigators,
  predictions, verdicts, and the `git status` check.
- [obra/superpowers](https://github.com/obra/superpowers), compared but not
  adopted: it reviews after implementation rather than gating plans per
  worker.

## Runtime notes

The client notes in [`references/runtimes.md`](references/runtimes.md) were
checked against these, reviewed November 13, 2026:

- OpenAI, [Codex subagents](https://developers.openai.com/codex/subagents)
- Visual Studio Code, [Custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents)
- Cursor, [Subagents](https://cursor.com/docs/subagents)
- Gemini CLI, [Subagents](https://geminicli.com/docs/core/subagents/) and
  [CLI documentation](https://google-gemini.github.io/gemini-cli/docs/cli/)

## Spec review, rollback point, and documentation updates

Reviewed November 13, 2026.

- [spec-driven-dev](https://github.com/mkrtchian/spec-driven-dev) by Roman
  Mkrtchian, available under the MIT License: having fresh agents that never
  saw the work review the plan in a separate pass before implementation. This
  became the spec review with the plan lens.
- [Agent Army](https://www.skills.sh/onewave-ai/claude-skills/agent-army), a
  skill in OneWave AI's `claude-skills` library, available under the MIT
  License: a git checkpoint before deploying parallel agents. This became the
  rollback point before parallel engineers start.
- Factory, a plugin by Pedro Schneider in the Anthropic plugin directory: a
  documentation-sync agent that keeps docs in step with code changes. This
  became the stage-end documentation update. No public repository was found;
  the idea comes from the plugin's directory listing.
