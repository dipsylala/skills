# Veracode SCA Analysis Scripts

This folder contains extraction scripts for analyzing Veracode local SCA scan results.

## Scripts

### `sca_summary.py`

Extracts a summary table of vulnerable dependencies grouped by component, showing severity, CVE count, and available fix versions.

**Usage:**

```bash
python3 sca_summary.py <path-to-veracode.json>
```

### `extract_configs.py`

Extracts IaC/Dockerfile configuration findings sorted by severity.

**Usage:**

```bash
python3 extract_configs.py <path-to-veracode.json>
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
