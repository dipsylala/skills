---
name: veracode-pipeline-results
description: Interpret Veracode pipeline scan JSON results and summarise findings by severity, file, and issue type. Use when a user provides a Veracode pipeline scan JSON file or attachment, asks about Veracode scan results, or wants to understand flaws found in a scan.
---

# Veracode Pipeline Scan Interpreter

## Quick start

If no file is provided, search the workspace for a file matching `filtered_*.json` and use that. If multiple matches exist, ask the user which to use. If none found, ask the user to provide the file.

**Default mode is Summary.** Only switch to Detail mode when the user asks to investigate a specific finding.

Use the scripts in the `scripts/` subfolder alongside this SKILL.md. Resolve the path to `scripts/` based on where this SKILL.md was loaded from.

---

## Mode 1 — Summary (default)

Pipeline scan JSON files can be large. Use the summary script to extract data rather than reading the file directly into context.

### Step 1: Run the summary script

```bash
python3 <skill-dir>/scripts/pipeline_summary.py <filtered_results.json>
```

The script outputs four sections — no stack dumps are read:

1. **Scan Overview** — status, message, module count, module list, total findings
2. **Severity Breakdown** — count per severity level and exploitability range at each level
3. **Issue Type Breakdown** — count and highest severity per unique issue type
4. **Findings by File** — each source file as its own block; header shows finding count and highest severity; rows sorted highest severity first within the file

### Step 2: Interpret and present

1. **One-paragraph executive summary** — scan status, module count, total findings, and severity distribution (draw from Scan Overview and Severity Breakdown sections)
2. **Issue type highlights** — call out any issue type with Very High or High findings, or with a high count (draw from Issue Type Breakdown)
3. **File-by-file analysis** — work through each file block from the script output, summarising what was found and why it matters; group related issues where possible
4. **Prioritised remediation list** — Very High → High → Medium → Low, one action per finding referencing its ID

---

## Mode 2 — Finding detail (on demand)

Switch to this mode when the user asks about a specific finding, wants to assess exploitability, or wants to know if a result is a false positive.

### Step 1: Run the detail script

```bash
python3 <skill-dir>/scripts/pipeline_detail.py <filtered_results.json> <issue_id>
```

This outputs: full finding header, plain-text description / remediation / references (HTML stripped from `display_text`), and the taint data path reconstructed from `stack_dumps` (Source → Sink).

### Step 2: Interpret the data path

- Review the reconstructed call chain from the script output
- Determine whether the taint source is truly user-controlled or a false positive (e.g. a hardcoded filename passed to `file_get_contents` is not HTTP input)
- State your verdict: **Confirmed** (user input genuinely reaches the sink) or **Likely false positive** (source is internal/hardcoded), with a one-sentence reason

Example verdict output:
```
Verdict: Likely false positive — path argument is a hardcoded string literal;
         data originates from a bundled local file, not HTTP input.
```

### Step 3: Remediation advice

- Present the **Remediation** section from the script output as the primary fix guidance
- If verdict is **Likely false positive**, note that mitigation (rather than a code change) may be appropriate and describe compensating controls

---

See [REFERENCE.md](REFERENCE.md) for the full JSON schema, severity map, and exploitability levels.
See [scripts/README.md](scripts/README.md) for script usage details.
