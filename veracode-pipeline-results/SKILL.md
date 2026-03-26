---
name: veracode-pipeline-results
description: Interpret Veracode pipeline scan JSON results and summarise findings by severity, file, and issue type. Use when a user provides a Veracode pipeline scan JSON file or attachment, asks about Veracode scan results, or wants to understand flaws found in a scan.
---

# Veracode Pipeline Scan Interpreter

## Quick start

When given a Veracode pipeline scan JSON:

1. Check `scan_status` — if not `SUCCESS`, report the failure.
2. Report modules scanned (`modules` array).
3. Summarise findings by severity (see severity map in [REFERENCE.md](REFERENCE.md)).
4. For each finding, show: severity label, file, line, function, issue type, CWE, and remediation.

## Workflow

### 1. Scan overview
- Status: `scan_status` + `message`
- Modules scanned: list `modules[]`
- Total findings: `findings` array length

### 2. Findings summary table

Group by severity (highest first). For each severity level present, output a section:

| Severity | Count | Issue Types |
|----------|-------|-------------|
| Very High (5) | n | list |
| High (4) | n | list |
| Medium (3) | n | list |
...

### 3. Per-finding detail

For each finding (highest severity first):

```
[SEVERITY] issue_type (CWE-cwe_id)
File: image_path, Line: files.source_file.line
Function: files.source_file.qualified_function_name
Exploitability: exploit_level (see REFERENCE.md)
Remediation: <extracted from display_text — strip HTML tags, keep second <span> block>
```

### 4. Remediation guidance

The `display_text` field contains three `<span>` blocks (HTML-encoded):
1. **What**: describes the flaw and data flow
2. **How to fix**: remediation steps — always include this
3. **References**: CWE/OWASP links

Strip HTML tags and present the second block as remediation advice.

### 5. Shell-shock findings (severity 0, issue_type_id: shell_shock)

These are informational — flag them separately as environment review items, not flaws requiring code changes.

## Output format

- Lead with a one-paragraph executive summary
- Use a severity table for the overview
- Use collapsible or indented sections per finding
- End with a prioritised remediation list (Very High → High → Medium → Low)

See [REFERENCE.md](REFERENCE.md) for the full JSON schema, severity map, and exploitability levels.
