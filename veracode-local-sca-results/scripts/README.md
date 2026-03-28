# Veracode SCA Analysis Scripts

This folder contains extraction scripts for analyzing Veracode local SCA scan results.

## Scripts

### `sca_summary.py`

Extracts a summary table of vulnerable dependencies grouped by component, showing severity, CVE count, and available fix versions.

**Usage:**

```bash
python3 sca_summary.py <path-to-veracode.json>
```

**Sample output:**

```text
Policy: Policy Breached | Secrets: 0 | Components: 4 | Total CVEs: 11 (2 Critical 5 High 4 Medium)

Component                                               Sev        CVEs   Fix
com.fasterxml.jackson.core:jackson-databind@2.12.3      Critical   3      2.13.4.2
org.yaml:snakeyaml@1.28                                 High       2      2.0
commons-codec:commons-codec@1.11                        High       1      1.15
org.apache.httpcomponents:httpclient@4.5.9              Medium     4      4.5.14
```

### `iac_summary.py`

Extracts IaC/Dockerfile configuration findings sorted by severity.

**Usage:**

```bash
python3 iac_summary.py <path-to-veracode.json>
```

**Sample output:**

```text
[CRITICAL] DS002: Image user should not be 'root'
Message: Running containers as root is a security risk. Use a non-root user.
Fix: Add a USER instruction to the Dockerfile with a non-root user
Ref: https://avd.aquasec.com/misconfig/ds002

[HIGH] DS014: RUN using 'sudo' is not allowed
Message: sudo usage detected in RUN instruction
Fix: Use gosu or a non-root user instead of sudo
Ref: https://avd.aquasec.com/misconfig/ds014
```

### `sca_detail.py`

Extracts detailed CVE information for a specific component, including CVSS scores, descriptions, and fix details.

**Usage:**

```bash
python3 sca_detail.py <path-to-veracode.json> <component-name>
```

**Example:**

```bash
python3 sca_detail.py veracode.json snakeyaml
```

**Sample output:**

```text
Component: snakeyaml @ 1.28 (java-archive)
Location:  /app/lib/snakeyaml-1.28.jar

CVE:         CVE-2022-1471
Severity:    Critical (CVSS3: 9.8)
Description: SnakeYaml's Constructor class does not restrict types which can be
             instantiated during deserialization, allowing remote code execution.
Fix state:   fixed
Fix version: 2.0
Advisory:    https://github.com/advisories/GHSA-mjmj-j48q-9wg2

CVE:         CVE-2022-41854
Severity:    High (CVSS3: 7.5)
Description: DoS via stack overflow when parsing deeply nested YAML.
Fix state:   fixed
Fix version: 2.0
Advisory:    https://github.com/advisories/GHSA-w37g-rhq8-7m4j
```
