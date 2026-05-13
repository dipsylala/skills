---
name: prompt-audit
description: Analyse a prompt or system instruction set for quality issues across five dimensions: contradictions, ambiguity, persona consistency, cognitive load, and semantic coverage. Use when the user wants to audit, review, analyse, or debug a prompt, system prompt, or instruction set.
---

# Prompt Audit

## Quick start

When the user provides a prompt to audit, apply all five analyses below and produce the report. If no prompt is supplied, ask for it.

## Analysis Dimensions

Analyse the supplied prompt across these five areas:

1. **Contradictions**: Find instructions that directly conflict with each other. Explain exactly WHY they conflict and what behavior the model would exhibit.
2. **Ambiguity**: Find vague or underspecified instructions that a model could interpret in multiple ways. Explain the different possible interpretations and suggest a concrete rewrite.
3. **Persona Consistency**: Find places where the expected tone, personality, or role contradicts itself. Explain the specific mismatch.
4. **Cognitive Load**: Find overly complex instruction patterns (deeply nested conditions, too many competing priorities, unclear precedence). Explain why they are hard for a model to follow.
5. **Semantic Coverage**: Find scenarios or edge cases the prompt doesn't address, where the model would have to guess. Explain what could go wrong.

## Output Format

Respond with a human-readable report using the following sections. Each section uses plain prose and bullet points — no JSON, no code blocks.

See [REPORT-TEMPLATE.md](REPORT-TEMPLATE.md) for the full section format.

## Constraints

- All quoted text must be copied exactly from the prompt so issues can be located precisely.
- All explanations and suggestions must be specific and actionable — never vague like "could be clearer".
- Suggestions must be concrete rewrites or additions, not abstract advice.
