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

## Tool detection

Before running commands, check what is available in the terminal:

1. Try `pwsh --version` or `powershell --version` — use PowerShell if available
2. Otherwise try `python3 --version` or `python --version` — use Python

Both modes below provide PowerShell and Python variants. Use whichever matches the available tool.

> **Duplicate matches are expected.** The same CVE often appears multiple times in the JSON (once per artifact location). All commands below deduplicate automatically — CVE counts reflect unique advisories only.

---

## Mode 1 — Summary (default)

SCA files can be very large. Use a terminal command to extract the data rather than reading the file directly into context.

### Step 1: Extract SCA data via terminal

**Option A — PowerShell** (run as a **single line**; multiline blocks are collapsed and will fail):

```powershell
$j = Get-Content '<path>' | ConvertFrom-Json; $sevOrder = @('Critical','High','Medium','Low','Negligible'); $j.vulnerabilities.matches | Group-Object { $_.artifact.name + '@' + $_.artifact.version } | ForEach-Object { $cves = $_.Group.vulnerability.id | Select-Object -Unique; $sev = ($_.Group.vulnerability.severity | Sort-Object { $sevOrder.IndexOf($_) } | Select-Object -First 1); $fixVers = @($_.Group | ForEach-Object { $_.vulnerability.fix.versions } | Where-Object { $_ } | Select-Object -Unique); $fix = if ($fixVers.Count -gt 0) { ($fixVers | Sort-Object | Select-Object -Last 1) } else { 'none' }; [PSCustomObject]@{ Component=$_.Name; Sev=$sev; CVEs=$cves.Count; Fix=$fix } } | Sort-Object { $sevOrder.IndexOf($_.Sev) } | Format-Table -AutoSize
```

**Option B — Python** (create a temp script, run it, then delete it):

Create `sca_summary.py`:
```python
import json, sys
from collections import defaultdict
sev_order = ['Critical', 'High', 'Medium', 'Low', 'Negligible']
data = json.load(open(sys.argv[1]))
comps = defaultdict(list)
for m in data['vulnerabilities']['matches']:
    comps[m['artifact']['name'] + '@' + m['artifact']['version']].append(m)
rows = []
for k, v in comps.items():
    sev = min((m['vulnerability']['severity'] for m in v), key=lambda s: sev_order.index(s) if s in sev_order else 99)
    cves = len({m['vulnerability']['id'] for m in v})
    fv = sorted({ver for m in v for ver in (m['vulnerability']['fix'].get('versions') or [])})
    rows.append((k, sev, cves, fv[-1] if fv else 'none'))
rows.sort(key=lambda r: sev_order.index(r[1]) if r[1] in sev_order else 99)
print(f"{'Component':<55} {'Sev':<10} {'CVEs':<6} Fix")
for r in rows:
    print(f'{r[0]:<55} {r[1]:<10} {r[2]:<6} {r[3]}')
```

Run: `python3 sca_summary.py <path>` (or `python` on Windows)

Delete the temp file after running.

Replace `<path>` with the absolute path to the JSON file.

Also read `policy-passed`, `secrets`, and `configs` directly — these are small.

### Step 2: Output

1. **Header**: policy result, total unique components affected, total CVE matches, secrets count
2. **SCA remediation table** (from terminal output, highest severity first):

| Component | Version | Highest Severity | CVEs | Fix Version | Action |
| ----------- | --------- | ----------------- | ------ | ------------- | -------- |
| name | ver | Critical/High/… | n | x.y.z or none | Upgrade / Replace / Remove |

3. **IaC findings** grouped by severity (CRITICAL → LOW) — read `configs[]` directly, it is small:

```
[SEVERITY] ID: Title
Message: <specific finding>
Fix: <Resolution>
Ref: <PrimaryURL>
```

4. **Secrets**: list any entries in `secrets[]` as CRITICAL.

5. **Prioritised action list** combining SCA and IaC.

---

## Mode 2 — Detail (on request)

When the user asks about a specific component or CVE, use a terminal command to extract deduplicated detail — do **not** read matches directly from the file.

**Option A — PowerShell** (single line; replace `<component>` with the artifact name e.g. `snakeyaml`):

```powershell
$j = Get-Content '<path>' | ConvertFrom-Json; $art = ($j.vulnerabilities.matches | Where-Object { $_.artifact.name -eq '<component>' } | Select-Object -First 1).artifact; Write-Host "Component: $($art.name) @ $($art.version) ($($art.type))"; Write-Host "Location:  $(($art.locations | Select-Object -First 1).accessPath)`n"; $j.vulnerabilities.matches | Where-Object { $_.artifact.name -eq '<component>' } | Group-Object { $_.vulnerability.id } | ForEach-Object { $m = $_.Group[0]; $cvss3 = ($m.vulnerability.cvss | Where-Object { $_.type -eq 'Primary' -and $_.version -like '3*' } | Select-Object -First 1).metrics.baseScore; [PSCustomObject]@{ CVE=$m.vulnerability.id; Severity=$m.vulnerability.severity; CVSS3=$cvss3; State=$m.vulnerability.fix.state; FixVer=(($m.vulnerability.fix.versions) -join ', '); Description=$m.vulnerability.description; Advisory=$m.vulnerability.dataSource } } | Sort-Object { @('Critical','High','Medium','Low','Negligible').IndexOf($_.Severity) } | Format-List
```

**Option B — Python** (create `sca_detail.py`, run it, then delete it):

```python
import json, sys
sev_order = ['Critical', 'High', 'Medium', 'Low', 'Negligible']
data = json.load(open(sys.argv[1]))
comp = sys.argv[2]
matches = [m for m in data['vulnerabilities']['matches'] if m['artifact']['name'] == comp]
if not matches:
    print(f'No matches for: {comp}'); sys.exit(1)
a = matches[0]['artifact']
print(f"Component: {a['name']} @ {a['version']} ({a['type']})")
print(f"Location:  {a['locations'][0]['accessPath']}\n")
seen = {}
for m in matches:
    if m['vulnerability']['id'] not in seen:
        seen[m['vulnerability']['id']] = m
for m in sorted(seen.values(), key=lambda m: sev_order.index(m['vulnerability']['severity']) if m['vulnerability']['severity'] in sev_order else 99):
    v = m['vulnerability']
    cvss3 = next((c['metrics']['baseScore'] for c in v.get('cvss', []) if c.get('type') == 'Primary' and str(c.get('version', '')).startswith('3')), 'n/a')
    fix_vers = ', '.join(v['fix'].get('versions') or ['none available'])
    print(f"CVE:         {v['id']}")
    print(f"Severity:    {v['severity']} (CVSS3: {cvss3})")
    print(f"Description: {v['description']}")
    print(f"Fix state:   {v['fix']['state']}")
    print(f"Fix version: {fix_vers}")
    print(f"Advisory:    {v['dataSource']}\n")
```

Run: `python3 sca_detail.py <path> <component-name>`

Delete the temp file after running.

Include all CVEs for that component, deduplicated. State the recommended action (Upgrade / Replace / Remove) with the specific target version if available.

---

## Remediation priority

1. **Upgrade** to `vulnerability.fix.versions[]`
2. **Replace** if `fix.state` is `wont-fix` or `not-fixed`
3. **Remove** if the dependency is unused

See [REFERENCE.md](REFERENCE.md) for the full JSON schema and severity mapping.
