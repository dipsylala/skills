---
name: prompt-audit
description: "Write or audit any document an agent consumes: a prompt, system prompt, skill, or AGENTS.md / CLAUDE.md. Use when creating or editing a skill or agent instruction file, or when the user wants a prompt or skill audited, reviewed, or debugged."
---

# Prompt Audit

Applies to any document an agent consumes: a prompt, a system prompt, a skill, an `AGENTS.md` / `CLAUDE.md`. [references/writing.md](references/writing.md) is the writing reference for both modes below. When the document is a skill, also read [references/skill-mechanics.md](references/skill-mechanics.md).

Both modes grade findings on one severity scale:

- **ERROR**: Prevents the intended task from completing correctly.
- **WARNING**: Creates a plausible failure in an intended use case.
- **INFO**: Improves clarity or maintenance without an identified functional failure.

## Writing

When creating or editing a document, read the writing reference and apply it. For a new document, or an edit that changes its steps, rules, or description, audit the draft as below before finishing. Fix every ERROR and WARNING finding, then list what you fixed and any remaining INFO findings in one line each, without the full report.

## Auditing

Resolve the audit target from supplied text, named files, or conversation context. Ask the user to supply the target only when it cannot be identified or accessed. When the target links to instruction files (a skill's references, docs an `AGENTS.md` points at), read the ones it links to directly and audit them with the target as one instruction set. Treat other skills it names as dependencies: check how the target uses them, not their contents. Apply all six analyses below and produce the report. File each issue once, under the most specific dimension, and cross-reference it from any other dimension it touches.

Assess findings against the intended use cases and available instruction context. State material assumptions and review limitations; ask for additional context only when it could change a finding.

### Analysis Dimensions

Analyse the target across these six areas:

1. **Contradictions**: Find instructions that apply to the same situation and remain incompatible after accounting for instruction precedence and explicit exceptions. Explain why they conflict and the plausible failure mode.
2. **Ambiguity**: Find vague or underspecified instructions that a model could interpret in multiple ways. Explain the different possible interpretations and suggest a concrete rewrite.
3. **Persona Consistency**: Find places where the expected tone, personality, or role contradicts itself. Explain the specific mismatch.
4. **Cognitive Load**: Find overly complex instruction patterns (deeply nested conditions, too many competing priorities, unclear precedence). Explain why they are hard for a model to follow.
5. **Semantic Coverage**: Find omissions that affect an intended use case and are not covered by the surrounding environment. Explain what could go wrong.
6. **Agent Writing**: Check the target against each section of the writing reference: context pointers (a skill's description is one), information hierarchy and sprawl, completion criteria, leading words and negation, and pruning. For a skill, also check its frontmatter and invocation choice against the skill mechanics reference. Name the lever and explain the behaviour it puts at risk.

### Output Format

Respond with a human-readable report using the following sections. Each section uses plain prose and bullet points - no JSON, no code blocks.

Read [REPORT-TEMPLATE.md](REPORT-TEMPLATE.md) when preparing the report, and use its section format.

### Constraints

- Distinguish predicted behaviour from behaviour observed in an evaluation. Label static analysis as such and identify any evaluation evidence used.
- All quoted text must be copied exactly from the target so issues can be located precisely; name the file when the target spans several.
- Anything pertaining to quoted secrets (API keys, tokens, passwords) should be replaced with a placeholder.
- All explanations and suggestions must be specific and actionable - never vague like "could be clearer".
- Suggestions must be concrete rewrites or additions, not abstract advice, written to the writing reference.
