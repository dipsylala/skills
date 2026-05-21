---
name: code-guardian
description: Audits LLM-generated code edits for adherence to surrounding code conventions, OWASP Top 10:2025 application security, and OWASP LLM security practices before applying them. Use when writing, editing, or generating code as a pre-apply guardrail, especially when a deterministic SAST, lint, or test hook is unavailable or as a supplement to one.
---

# Code Guardian

## Quick start

After generating any code edit, run this checklist **before applying**:

1. Scan 3–5 nearby files → infer conventions
2. Apply those conventions to the generated code
3. Run deterministic checks first when available (SAST, lint, typecheck, tests)
4. Run traditional OWASP Top 10:2025 checks (see [OWASP-APP.md](OWASP-APP.md))
5. If the edit touches LLM/GenAI code, run OWASP LLM checks too (see [OWASP-LLM.md](OWASP-LLM.md))
6. If any violation found → fix inline when the safe fix is clear, or block and escalate
7. Only apply the edit when convention checks pass and security issues are fixed or explicitly escalated

## Convention scan

Read files in the same directory or module. Extract and apply:

| Dimension | Look for |
|-----------|----------|
| Naming | variable/function/class casing (camelCase, snake_case, PascalCase) |
| Imports | ordering, aliasing, named vs default exports |
| Error handling | try/catch vs Result/Either, error logging style |
| Types | inferred vs explicit annotations, strictness level |
| Structure | function length norms, single-responsibility patterns |
| Comments | JSDoc vs inline, docstring style |

Generated code must match the detected style. When in doubt, match the majority pattern.

## Security check

Scan every edit against the traditional OWASP Top 10:2025 signals in [OWASP-APP.md](OWASP-APP.md).

Also scan against [OWASP-LLM.md](OWASP-LLM.md) when the edit touches prompts, model calls, RAG, embeddings, vector search, tool/function calling, autonomous agents, model training, fine-tuning, AI memory, or AI billing/rate limits.

This skill is a heuristic review guardrail, not a replacement for deterministic SAST, dependency scanning, secret scanning, linting, tests, or human security review. Prefer deterministic scanners when they exist. Do not claim code is secure solely because this checklist passed.

## Violation handling

When a violation is found, report it before applying:

```
[GUARDIAN] <Category>: <what and why>
Fix: <corrected code>
```

Fix inline only when the correct remediation is local and clear, such as parameterizing a query, escaping output, removing a literal secret, switching to a strong random source, or adding schema validation.

If the fix depends on product policy or deployment context, block the edit and ask or flag the missing decision. Do not invent authorization rules, ownership checks, CORS origins, secret locations, or allowlists.

Re-verify after fixing. Apply silently when clean.
