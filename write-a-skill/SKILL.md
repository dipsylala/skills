---
name: write-a-skill
description: Create new agent skills with proper structure, progressive disclosure, and bundled resources. Use when user wants to create, write, or build a new skill.
---

# Writing Skills

## Process

1. **Establish scope and destination.** Use the request and existing context to identify the task, representative use cases, target host, and destination. Ask only about missing information that affects the result. Inspect an existing skill at that location before editing, and preserve unrelated content. Retain the user's chosen invocation policy or the host default when none is specified.

2. **Choose the necessary resources.** Start with instructions. Add references, examples, assets, or scripts only when they improve the actual workflow. Account for available tools and dependencies; state how to proceed when a required resource is unavailable.

3. **Draft the skill.** Define its inputs, intended result, essential constraints, and completion criteria. Keep the workflow within the user's request and existing authorisation. Use the structure below as an example, adapting it to the task. A reference skill may need guidance rather than ordered steps.

4. **Validate the result.** Follow the validation checklist below. Resolve failures and distinguish structural checks from behavioural evaluation. Keep evaluation side effects within the authorised scope and use temporary artifacts when needed.

5. **Deliver the completed files.** Report their location, the behaviour they define, checks performed, and any unresolved limitation. Ask for feedback on material open choices without making a routine review questionnaire a prerequisite for delivery.

## Skill Structure

```
skill-name/
├── SKILL.md           # Main instructions (required)
├── references/        # Detailed docs or examples (if needed)
├── assets/            # Files used in output (if needed)
└── scripts/           # Executable helpers (if needed)
```

Create only the resources the task needs. Link each supporting reference from the instructions that use it, with a clear condition for reading it. Keep required files inside the distributed skill unless an external dependency is intentional and documented. Host-specific configuration belongs in the location supported by that host.

## SKILL.md Template

Use this as a starting point, not a required set of headings. Replace all placeholders and omit sections that do not help the task.

```md
---
name: skill-name
description: Brief description of capability. Use when [specific triggers].
---

# Skill Name

## Inputs and result

[Required inputs and the intended result]

## Workflow

[Essential instructions, constraints, and completion criteria]

## Supporting material

[If needed, link to a real reference file and say when to read it.]
```

## Description Requirements

The description helps the host decide when to load a skill. Discovery can also expose its name, path, or other metadata; exact behaviour depends on the host. Write a concise description identifying the capability and activation conditions, with a boundary when nearby tasks should not trigger it.

**Portable format requirements**:

- Include a non-empty `name` and `description` in YAML frontmatter.
- Use a name of at most 64 characters containing lowercase letters, digits, and hyphens; avoid leading, trailing, or consecutive hyphens. Match the containing directory's name.
- Keep the description within 1024 characters. No particular grammatical person or sentence count is required.
- Check optional fields and their types against the [Agent Skills specification](https://agentskills.io/specification). Verify host-specific settings against that host's documentation rather than assuming they are portable.

Leading with the capability followed by "Use when..." is a useful convention, not a format requirement.

**Good example**:

```
Extract text and tables from PDFs, fill PDF forms, and merge PDF documents. Use when the requested input or output is a PDF.
```

**Bad example**:

```
Helps with documents.
```

The bad example gives your agent no way to distinguish this from other document skills.

## When to Add Scripts

Add a script when a repeated operation or a need for deterministic execution justifies a maintained helper. Reuse suitable existing tools before creating one. Document its inputs, outputs, dependencies, and meaningful failure behaviour. Verify scripts with representative inputs, including relevant failure cases; a script's presence alone does not establish reliability.

## When to Split Files

Keep the entrypoint focused on essential instructions. Move substantial optional or domain-specific detail into linked references when that improves navigation. Treat length as a warning signal, not the sole reason to split. Include examples when they clarify non-obvious behaviour. For information that changes, specify an authoritative source and when to consult it instead of banning time-sensitive topics.

## Validation Checklist

After drafting:

- [ ] Validate YAML frontmatter, field types, naming, and optional host configuration against the target format. Use an available validator and report any limitation when validation cannot run.
- [ ] Check that local references resolve, required resources are included or declared as dependencies, and template placeholders have been removed.
- [ ] Check that instructions preserve the user's scope, use consistent terminology, and define an observable result or completion criterion.
- [ ] Run added scripts with representative inputs and relevant failure cases, within authorised resources and side effects.
- [ ] Evaluate representative requests that should activate the skill and nearby requests that should not. Check that a representative task produces the intended result and respects its constraints. Use live execution when practical and authorised; label a static walkthrough as such.
- [ ] Resolve observed failures and report what was tested. Do not present formatting checks as proof of reliable behaviour.
