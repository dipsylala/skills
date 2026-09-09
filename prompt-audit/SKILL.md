---
name: prompt-audit
description: "Analyse a prompt or system instruction set for quality issues across five dimensions: contradictions, ambiguity, persona consistency, cognitive load, and semantic coverage. Use when the user wants to audit, review, analyse, or debug a prompt, system prompt, or instruction set."
---

# Prompt Audit

## Quick start

Resolve the audit target from supplied text, named files, or conversation context. Ask the user to supply the target only when it cannot be identified or accessed. Apply all five analyses below and produce the report.

Assess findings against the intended use cases and available instruction context. State material assumptions and review limitations; ask for additional context only when it could change a finding.

## Analysis Dimensions

Analyse the supplied prompt across these five areas:

1. **Contradictions**: Find instructions that apply to the same situation and remain incompatible after accounting for instruction precedence and explicit exceptions. Explain why they conflict and the plausible failure mode.
2. **Ambiguity**: Find vague or underspecified instructions that a model could interpret in multiple ways. Explain the different possible interpretations and suggest a concrete rewrite.
3. **Persona Consistency**: Find places where the expected tone, personality, or role contradicts itself. Explain the specific mismatch.
4. **Cognitive Load**: Find overly complex instruction patterns (deeply nested conditions, too many competing priorities, unclear precedence). Explain why they are hard for a model to follow.
5. **Semantic Coverage**: Find omissions that affect an intended use case and are not covered by the surrounding environment. Explain what could go wrong.

## Output Format

Respond with a human-readable report using the following sections. Each section uses plain prose and bullet points - no JSON, no code blocks.

Read [REPORT-TEMPLATE.md](REPORT-TEMPLATE.md) when preparing the report, and use its section format and shared severity scale.

## Constraints

- Distinguish predicted behaviour from behaviour observed in an evaluation. Label static analysis as such and identify any evaluation evidence used.
- All quoted text must be copied exactly from the prompt so issues can be located precisely.
- Anything pertaining to quoted secrets (API keys, tokens, passwords) should be replaced with a placeholder.
- All explanations and suggestions must be specific and actionable - never vague like "could be clearer".
- Suggestions must be concrete rewrites or additions, not abstract advice.
