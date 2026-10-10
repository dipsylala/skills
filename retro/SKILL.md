---
name: retro
description: "Conduct a retrospective on a coding session."
disable-model-invocation: true
---

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs.

## Steps

1. Read `writing-for-agents` if available through the host's supported skill mechanism. If unavailable, continue with concise recommendations that name the observed problem, proposed change, and completion criterion.

2. Read the primary sources for the session the user specifies. This may mean searching through session logs on this machine. If the user doesn't specify a session, default to the current one.

Limit log access to the specified session. If its sources cannot be accessed, state the limitation and base findings only on available evidence. Distinguish observed failures from proposed preventive improvements.

3. Look for candidates for improvement in these categories.

Recommend automation when it addresses a demonstrated or credible recurring failure and its maintenance cost is proportionate. Describe the proposed check without implementing it unless authorized.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: could linting, typing, tests, or filesystem checks catch an observed or credible recurring failure? Read the repo's existing check commands and CI workflow first. Identify checks that are unwired or silently broken before proposing new ones. Assess missing automation against the failure it would prevent and its maintenance cost; absence alone is not a finding.
- **Coding standards**: should an existing rule be added, removed, or clarified? Distinguish mechanical violations (fixed syntax, banned APIs, import shapes, file-location rules) from judgement calls such as cross-file consistency. Consider deterministic checks for mechanical violations using the repo's existing tooling where practical. Record judgement-based guidance in `CODING_STANDARDS.md`. Follow the project's implementation and review workflow.
- **Global AGENTS.md**: are there any steering instructions that should be moved to coding standards (or automated checks) instead? _Use when_ the AGENTS.md file is particularly large - in the repo OR the user's global scope.
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Is there any custom tooling (CLI's, MCP's) that is particularly token-inefficient? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information. Teeing dev server logs, readonly access to third-party services. _Use when_ a crucial piece of information was not available to the agent.

4. Present these candidates to the user, in order of severity.

For each candidate, cite the session evidence or repository source, explain the likely impact, and propose a concrete change with a verification criterion. This retrospective produces recommendations; implement changes only when the user's request also authorizes them.

## Reference

### Implementation vs Review

When a project separates implementation and review, the implementation agent handles exploration, writing code, and debugging failures, which can create substantial context pressure.

The review agent can focus on the diff, but must still inspect surrounding context when needed to assess correctness.

Use automated checks for mechanically enforceable standards when proportionate. Make judgement-based standards available to both implementation and review; use the project's actual workflow rather than assuming a separate reviewer agent exists.

### Files

You have access to several files in the repo:

- `CLAUDE.md`/`AGENTS.md`: these files are pushed to the context window of any agent working in this repo. They should be used incredibly sparingly, usually only for **navigation pointers** to other files.
- `CODING_STANDARDS.md`: consult relevant standards during implementation and review. Follow the project's configured workflow. Keep detailed guidance in linked reference documents when needed.
- Docs: use docs as references files, pointed to by other files. Look for existing docs before writing new ones.
- Skills: use skills for docs (since their description goes into the agent's context window), or for user-invoked commands. Follow the advice in the `writing-for-agents` skill.
