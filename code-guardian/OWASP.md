# OWASP Top 10 — Detection Guide

For each risk: signals to detect in generated code, and the fix principle to apply.

| # | Risk | Detect | Fix principle |
|---|------|--------|---------------|
| A01 | Broken Access Control | Privileged action with no auth check; user-supplied path or ID used without validation; missing ownership check | Validate identity/role before action; canonicalize and bound-check paths; verify ownership |
| A02 | Cryptographic Failures | Secret or credential as string literal; MD5/SHA1/DES/RC4/ECB usage; sensitive data in logs or plaintext storage | Load secrets from environment; use current algorithms (AES-GCM, bcrypt, SHA-256+); never log sensitive values |
| A03 | Injection | User input interpolated into SQL, shell, HTML, XML, or template strings; dynamic use of `eval`, `exec`, `system` | Use parameterized queries/prepared statements; escape output for context; avoid dynamic execution |
| A04 | Insecure Design | No input validation at trust boundary (API handler, CLI, webhook); insecure default (`debug=true`, `allow_all`); optional field omission bypasses logic | Validate and parse at every trust boundary; default to deny; make required fields explicit |
| A05 | Security Misconfiguration | Stack traces or debug info in HTTP responses; CORS `*` on sensitive routes; placeholder or default credentials | Guard debug output behind env flag; restrict CORS to known origins; reject placeholder secrets at startup |
| A06 | Outdated Components | Deprecated crypto or parsing API; dependency pinned to `*` or `latest` | Flag for human review; suggest pinning to a specific verified version |
| A07 | Auth Failures | Password stored or compared as plaintext; token generated with weak PRNG (`Math.random`); no expiry on JWT or session | Hash passwords with bcrypt/argon2; use `crypto.randomBytes` for tokens; always set expiry |
| A08 | Data Integrity | Untrusted data deserialized without schema validation; user input spread/assigned directly onto a model | Validate schema before deserializing; use explicit allowlist assignment, not mass-assignment |
| A09 | Logging Failures | Auth events, privilege changes, or destructive operations not logged; errors silently swallowed | Log security-relevant events with actor and resource; always surface errors, even if sanitized |
| A10 | SSRF | HTTP client called with URL from user input; redirect target from request parameter | Allowlist permitted URL origins; never pass raw user input to an HTTP client or redirect |
