# Skill mechanics

The skill-specific branch of [`writing-for-agents`](SKILL.md): what changes when the document is a skill (frontmatter, the invocation choice, and router skills). Everything else about writing it is the universal reference in `SKILL.md`.

## Portable format

Keep `name` and `description` in `SKILL.md` frontmatter. The description states the capability and when it applies, including a boundary when needed to distinguish nearby tasks. Put additional descriptive metadata under `metadata`. Consult the [Agent Skills specification](https://agentskills.io/specification) when validating fields and types.

## Invocation

Identify the target host before configuring invocation. Preserve the user's chosen policy. When none is specified, retain the host's default discovery behaviour; do not infer an explicit-only requirement from the task having side effects. Discovery does not itself authorise those side effects.

- **Automatic discovery** lets the host consider a skill when its description matches the task. The host determines which metadata is exposed, whether other skills can invoke it, and when its body enters context.
- **Explicit invocation** lets the user select a skill directly. Whether it also disables automatic discovery depends on the host's configuration; explicit use alone does not imply that restriction.

Use host-specific settings only for the target that supports them:

| Host | Explicit-only configuration | Reference |
| --- | --- | --- |
| Claude Code | `disable-model-invocation: true` in `SKILL.md` frontmatter | [Invocation controls](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill) |
| Codex | `policy.allow_implicit_invocation: false` in `agents/openai.yaml` | [Optional metadata](https://learn.chatgpt.com/docs/build-skills#optional-metadata) |

Check the linked host documentation when changing invocation settings or relying on visibility and context-loading behaviour. These settings are not interchangeable parts of the portable format. For other hosts, consult their documentation rather than assuming either setting applies.

Shared reference material can live in ordinary files linked from each skill that needs it. Keep those files available in every installed package that relies on them. Reading a reference is distinct from invoking a skill and must not be used to bypass host invocation restrictions.

## Splitting by invocation

Split off a skill when it has a distinct task that should be discoverable or directly invocable on its own. Keep supporting reference in ordinary files when it has no independent workflow. Account for the added discovery metadata and the user's need to understand which skill to choose.

## Router skills

A **router skill** helps select among related workflows by naming them and explaining when each applies. Add one only when it makes selection easier. It may invoke another skill only when the host permits that invocation and the skill is available; otherwise, direct the user to the appropriate invocation. A router does not override an explicit-only policy.
