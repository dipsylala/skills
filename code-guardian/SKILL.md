---
name: code-guardian
description: Audits LLM-generated code edits for adherence to surrounding code conventions and OWASP Top 10 security practices before applying them. Blocks and self-corrects violations inline. Use when writing, editing, or generating any code — activates automatically after every code change to intercept and fix violations before they land.
---

# Code Guardian

## Quick start

After generating any code edit, run this checklist **before applying**:

1. Scan 3–5 nearby files → infer conventions
2. Apply those conventions to the generated code
3. Run OWASP Top 10 checks (see [OWASP.md](OWASP.md))
4. If any violation found → fix inline and re-verify
5. Only apply the edit when both checks pass

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

Scan every edit against the OWASP Top 10 signals in [OWASP.md](OWASP.md).

## Violation handling

When a violation is found, report it and fix inline before applying:

```
[GUARDIAN] <Category>: <what and why>
Fix: <corrected code>
```

Re-verify after fixing. Apply silently when clean.
