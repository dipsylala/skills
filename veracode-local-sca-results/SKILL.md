---
name: veracode-local-sca-results
description: Interpret Veracode local SCA scan JSON results, summarising dependency vulnerabilities (SCA) and IaC/Dockerfile misconfigurations (configs) separately. Use when a user provides a Veracode SCA JSON file, asks about dependency vulnerabilities, component CVEs, or IaC security findings from a Veracode local scan.
---

# Veracode Local SCA Results Interpreter

## Quick start

The JSON contains up to three result sections — report on whichever the user asks for (default: both SCA and configs):

- `vulnerabilities.matches` — **SCA**: vulnerable dependencies matched to CVEs
- `configs` — **IaC**: Dockerfile / configuration misconfigurations
- `secrets` — secrets detected (report if non-empty, otherwise skip)

**Default mode is Summary.** Only switch to Detail mode when the user asks to investigate a specific component or CVE.

---

## Mode 1 — Summary (default)

SCA files can be very large. Use scripts to extract the data rather than reading the file directly into context.

### Step 1: Extract data

Run the analysis scripts from the `scripts/` subfolder alongside this skill file. Resolve the path to `scripts/` based on where this SKILL.md was loaded from.

**Run SCA summary:**
```bash
python3 <skill-dir>/scripts/sca_summary.py <path-to-veracode.json>
```
This outputs: policy status, secrets count, and the vulnerability summary table.

**Run IaC summary:**
```bash
python3 <skill-dir>/scripts/iac_summary.py <path-to-veracode.json>
```

> **Duplicate matches note**: The same CVE often appears multiple times in the JSON (once per artifact location). Scripts auto-deduplicate — CVE counts reflect unique advisories only.

### Step 2: Output

1. **Header**: Use the first line of sca_summary.py output directly — it includes policy result, secrets count, component count, and total CVEs broken down by severity
2. **SCA remediation table** (from sca_summary.py output, highest severity first):

| Component | Version | Highest Severity | CVEs | Fix Version | Action |
| ----------- | --------- | ----------------- | ------ | ------------- | -------- |
| name | ver | Critical/High/… | n | x.y.z or none | Upgrade / Replace / Remove |

3. **IaC findings** grouped by severity (CRITICAL → LOW) — from iac_summary.py output:

```
[SEVERITY] ID: Title
Message: <specific finding>
Fix: <Resolution>
Ref: <PrimaryURL>
```

4. **Secrets**: If secrets count > 0, note as CRITICAL priority.

5. **Prioritised action list** combining SCA and IaC.

---

## Mode 2 — Detail (on request)

When the user asks about a specific component or CVE, run the detail script from the `scripts/` subfolder alongside this skill file:

```bash
python3 <skill-dir>/scripts/sca_detail.py <path-to-veracode.json> <component-name>
```

Example:
```bash
python3 <skill-dir>/scripts/sca_detail.py veracode.json snakeyaml
```

State the recommended action (Upgrade / Replace / Remove) with the specific target version if available.

---

## Remediation priority

1. **Upgrade** to `vulnerability.fix.versions[]`
2. **Replace** if `fix.state` is `wont-fix` or `not-fixed`
3. **Remove** if the dependency is unused

See [REFERENCE.md](REFERENCE.md) for the full JSON schema and severity mapping.
