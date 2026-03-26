# Veracode Pipeline Scan JSON Reference

## Top-level fields

| Field | Type | Description |
| ------- | ------ | ------------- |
| `scan_id` | string | Unique scan identifier (UUID) |
| `scan_status` | string | `SUCCESS` or `FAILURE` |
| `message` | string | Human-readable scan result summary |
| `modules` | string[] | Scanned module/file group names |
| `modules_count` | number | Number of modules scanned |
| `findings` | Finding[] | Array of individual flaws |
| `selected_modules` | array | Modules selected for analysis (may be empty) |

---

## Finding object

| Field | Type | Description |
| ------- | ------ | ------------- |
| `issue_id` | number | Unique finding identifier for this scan |
| `title` | string | Internal function reference (e.g. `!php_standard_ns.shell_exec`) |
| `image_path` | string | Source file path where the flaw was found |
| `gob` | string | Grade of Building — alphabetic severity grade |
| `severity` | number | Numeric severity (0–5, see below) |
| `issue_type` | string | Full CWE-aligned issue name |
| `cwe_id` | string | CWE number (without prefix) |
| `exploit_level` | string | Exploitability score (see below) |
| `display_text` | string | HTML-encoded description with three `<span>` sections |
| `files` | FilesObj | Source file location details |
| `flaw_match` | FlawMatch | Hash data for cross-scan deduplication |
| `stack_dumps` | StackDumps | Call stack trace (may be empty `{}`) |

---

## Severity levels

| Value | Label | Priority |
| ------- | ------- | ---------- |
| 5 | Very High | P1 — fix immediately |
| 4 | High | P2 — fix before release |
| 3 | Medium | P3 — fix in next sprint |
| 2 | Low | P4 — schedule for backlog |
| 1 | Very Low | P5 — low risk, address when convenient |
| 0 | Informational | Review only — no code fix required (e.g. CVE environment advisories) |

---

## Exploitability levels (`exploit_level`)

| Value | Label | Meaning |
| ------- | ------- | --------- |
| `-2` | V. Unlikely | Very unlikely to be exploited |
| `-1` | Unlikely | Unlikely to be exploited |
| `0` | Neutral | Neither likely nor unlikely to be exploited |
| `1` | Likely | Likely to be exploited |
| `2` | V. Likely | Very likely to be exploited |

---

## `files.source_file` object

| Field | Description |
| ------- | ------------- |
| `file` | Relative file path |
| `upload_file` | Name of uploaded file |
| `line` | Line number of the sink (where flaw is triggered) |
| `function_name` | Short function name |
| `qualified_function_name` | Fully qualified name including class/scope |
| `function_prototype` | Signature |
| `scope` | Class or file scope |

---

## `display_text` structure

Contains three HTML `<span>` blocks (HTML entities must be decoded):

1. **Description** — what the flaw is, the call involved, and the full taint data flow (source → sink)
2. **Remediation** — how to fix the flaw; the most actionable section
3. **References** — links to CWE, OWASP, and Veracode documentation

Strip `<span>`, `<a href=...>`, and other HTML tags to get readable text.

---

## `stack_dumps` structure

When present, `stack_dumps.stack_dump[].Frame[]` lists frames from sink back to source:

| Field | Description |
| ------- | ------------- |
| `FrameId` | 0 = sink, ascending toward source |
| `FunctionName` | Function at this frame |
| `SourceFile` | File |
| `SourceLine` | Line number |
| `VarNames` | Variable or expression at this frame (shows taint propagation) |

Frame 0 is the dangerous call. The last frame is where untrusted input entered (e.g. `$_GET`, `$_POST`).

---

## Example: reading a finding

Trace the `stack_dumps` frames bottom-up:

- Last frame: source (e.g. `$_GET['src']`)
- Intermediate frames: propagation variables
- Frame 0: sink call (e.g. `shell_exec($command)` at the reported line)

The `display_text` second `<span>` will describe exactly what sanitisation is needed.
