# Veracode Local SCA JSON Reference

## Top-level fields

| Field | Type | Description |
| ------- | ------ | ------------- |
| `vulnerabilities` | VulnReport | SCA dependency vulnerability findings |
| `configs` | ConfigFinding[] | IaC / Dockerfile misconfiguration findings |
| `secrets` | Secret[] | Detected secrets (empty array if none) |
| `policy-passed` | string | Overall policy result: `"passed"`, `"failed"`, or `"not evaluated"` |

---

## `vulnerabilities` object

| Field | Description |
| ------- | ------------- |
| `descriptor.db` | Vulnerability database metadata (source, build time, schema version) |
| `descriptor.timestamp` | When the scan ran |
| `matches` | Array of Match objects — one per artifact×CVE combination |
| `linux_distro` | OS distro info if scanning a container image |

---

## Match object (`vulnerabilities.matches[]`)

| Field | Type | Description |
| ------- | ------ | ------------- |
| `artifact` | Artifact | The dependency that was matched |
| `vulnerability` | Vulnerability | The CVE matched to that dependency |
| `relatedVulnerabilities` | Vulnerability[] | Aliases or related CVEs |
| `matchDetails` | MatchDetail[] | How the match was determined |
| `customerPolicyResult.Status` | string | Policy evaluation: `"pass"`, `"fail"`, `"not evaluated"` |

> Note: multiple Match entries may share the same `artifact` — one per CVE. Group by artifact when reporting.

---

## Artifact object

| Field | Description |
| ------- | ------------- |
| `name` | Component name (e.g. `log4j-core`, `spring-webmvc`) |
| `version` | Installed version |
| `type` | Package type: `java-archive`, `npm`, `python`, `gem`, etc. |
| `locations[].path` | File path(s) where the artifact was found |
| `purl` | Package URL (canonical identifier) |
| `language` | Programming language |

---

## Vulnerability object

| Field | Description |
| ------- | ------------- |
| `id` | CVE or GHSA identifier (e.g. `CVE-2021-44228`) |
| `severity` | String severity: `Critical`, `High`, `Medium`, `Low`, `Negligible` |
| `description` | Human-readable description of the vulnerability |
| `fix.state` | `"fixed"`, `"not-fixed"`, `"wont-fix"` |
| `fix.versions[]` | Version(s) that resolve the vulnerability (empty if not fixed) |
| `cvss[]` | Array of CVSS score objects (prefer `type: "Primary"` with highest version) |
| `cvss[].metrics.baseScore` | Numeric CVSS base score (0.0–10.0) |
| `cvss[].version` | CVSS version (`"2.0"`, `"3.0"`, `"3.1"`) |
| `dataSource` | URL of the advisory source |
| `urls[]` | Advisory/reference URLs |

---

## Severity levels (SCA + IaC)

String-based severities used throughout this format:

| Label | Priority | Action |
| ------- | ---------- | -------- |
| Critical | P1 | Fix immediately |
| High | P2 | Fix before release |
| Medium | P3 | Fix in next sprint |
| Low | P4 | Address when convenient |
| Negligible | P5 | Informational only |

---

## SCA remediation priority

For each vulnerable component, attempt in order:

1. **Upgrade** — update to the version listed in `fix.versions[]`
2. **Replace** — if `fix.state` is `"wont-fix"` or `"not-fixed"`, find an alternative component
3. **Remove** — if the dependency is unused, remove it entirely

Do not edit lockfiles or package manifests directly unless the package manager is unavailable.

---

## Config finding object (`configs[]`)

| Field | Description |
| ------- | ------------- |
| `ID` | Rule identifier (e.g. `DS002`, `DS031`) |
| `Title` | Short rule name |
| `Description` | Explanation of why this is a risk |
| `Message` | Specific finding detail — what was detected in the file |
| `Resolution` | How to fix it |
| `Severity` | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` |
| `Status` | `FAIL` or `PASS` |
| `Target` | File or resource checked (e.g. `Dockerfile`) |
| `Type` | Check category (e.g. `Dockerfile Security Check`) |
| `PrimaryURL` | Reference URL for the rule |
| `Namespace` | Internal rule namespace |
| `customerPolicyResult.Status` | Policy evaluation result |

---

## Common Dockerfile rule IDs

| ID | Title | Severity |
| ---- | ------- | ---------- |
| DS002 | Image user should not be 'root' | HIGH |
| DS026 | No HEALTHCHECK defined | LOW |
| DS029 | `apt-get` missing `--no-install-recommends` | HIGH |
| DS031 | Secrets passed via build-args or envs | CRITICAL |

---

## `secrets` object

When non-empty, each entry contains the secret type, file, and line. Always treat secrets as CRITICAL — rotate any exposed credentials immediately.
