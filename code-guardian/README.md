# Code Guardian

**Status: proof of concept.** The checklist and reference material are usable,
but the delivery mechanism is wrong for what this is trying to do. See
[Why this belongs in a hook](#why-this-belongs-in-a-hook) before relying on it.

Audits generated code edits against the conventions of the surrounding
codebase, the OWASP Top 10:2025, and OWASP LLM security practices. The skill
uses the active agent directly. It does not call an external review service.

## Structure

- [`SKILL.md`](SKILL.md) defines the workflow: scan nearby files for
  conventions, run deterministic checks first, apply the security checklists,
  then fix inline or block and escalate.
- [`OWASP-APP.md`](OWASP-APP.md) holds the traditional application security
  signals.
- [`OWASP-LLM.md`](OWASP-LLM.md) holds the signals specific to prompts, model
  calls, RAG, tool calling, and agent code.

Keeping the checklists separate from the workflow lets them be updated as the
OWASP lists change without rewriting the procedure.

## Why this belongs in a hook

The skill instructs the agent to review an edit *before applying it*. As
written — a checklist in prose — it cannot enforce that, for three reasons.

**Invocation is discretionary.** A model-invoked skill runs when the agent
decides it is relevant. A guardrail that the guarded party can decline to
consult is advisory, not a control. The failure mode is silent: nothing
reports that the review was skipped.

**Prose cannot withhold the edit.** Step 7 of `SKILL.md` says to apply the
edit only once checks pass, but instructions have no mechanism to prevent the
`Edit` or `Write` call. They can only ask the agent to police itself in the
same turn that the agent is trying to finish a task.

**Self-review is the weakest form of review.** The same model that produced
the edit judges it, against criteria it just read. That catches careless
mistakes and misses reasoning errors, which is the opposite of the profile you
want from a security gate.

A `PreToolUse` hook fixes the first two. It fires on every matching tool call
rather than when the model elects to, and it can refuse the write.

## What that would look like

Claude Code skills can register hooks in frontmatter, so the checklist and its
enforcement can ship in the same directory:

```yaml
hooks:
  PreToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: prompt
          prompt: "Audit this edit against OWASP-APP.md. Deny on violation."
```

A hook refuses a call in one of two ways: exit 2 with the reason on stderr, or
exit 0 with JSON on stdout.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Query built by string concatenation."
  }
}
```

Either way the reason is fed back to the model, which can then correct the
edit and retry. See the [hooks
reference](https://code.claude.com/docs/en/hooks). The docs name `Edit` and
`Write` as the file-editing tools; whether `MultiEdit` and `NotebookEdit` need
matching too is untested here.

One gap does not close. A skill's hooks register when the skill is invoked and
last for the rest of the session, so discretionary invocation still governs
whether the gate exists at all — edits made before the skill runs are
ungated. Registering the hook in `.claude/settings.json` instead makes it
unconditional for the project.

## Limits of the hook approach

A hook is not a free upgrade.

- Hooks are specific to the host agent. They are not part of the
  [agentskills.io](https://agentskills.io) standard, so a hook-based guardrail
  does not travel to other agents the way this skill does. That portability is
  the reason the checklist is packaged as a skill today.
- The OWASP checks are judgement calls, not pattern matches, so the hook needs
  a model to evaluate them: `type: prompt` for a single-turn judgement, or
  `type: agent` for one with tool access. Agent hooks are documented as
  experimental. Both default to a short timeout — 30 and 60 seconds
  respectively — and both cost tokens on every edit. A plain `type: command`
  hook cannot make the call, because it communicates only over
  stdin, stdout, stderr, and exit codes.
- Convention inference needs the surrounding files, so the hook has to read
  repository context rather than only inspecting the diff.

## Scope

This is a heuristic review guardrail. It is not a replacement for SAST,
dependency scanning, secret scanning, linting, tests, or human security
review. Deterministic tools should run first where they exist, and a passing
checklist is not evidence that code is secure.

The skill fixes a finding inline only when the remediation is local and
unambiguous, such as parameterising a query, escaping output, removing a
literal secret, or adding schema validation. Where a fix depends on product
policy or deployment context, it blocks and asks instead of inventing
authorization rules, ownership checks, CORS origins, or allowlists.
