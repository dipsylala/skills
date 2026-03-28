#!/usr/bin/env python3
"""Extract a scan summary from a Veracode pipeline scan JSON result.

Outputs:
  1. Scan status and module list
  2. Severity breakdown table
  3. Issue-type breakdown table
  4. Per-file breakdown (findings grouped by file, highest severity first)

Optimised for LLM consumption.
"""
import json, sys
from collections import defaultdict

if len(sys.argv) < 2:
    print("Usage: python3 pipeline_summary.py <filtered_results.json>")
    sys.exit(1)

SEV_LABELS = {5: "Very High", 4: "High", 3: "Medium", 2: "Low", 1: "Very Low", 0: "Info"}
SEV_ORDER  = [5, 4, 3, 2, 1, 0]
EXPLOIT_LABELS = {
    "-2": "V.Unlikely", "-1": "Unlikely", "0": "Neutral",
    "1": "Likely",      "2": "V.Likely",
}

data     = json.load(open(sys.argv[1]))
status   = data.get("scan_status", "unknown")
message  = data.get("message", "")
modules  = data.get("modules", [])
findings = data.get("findings", [])

# ── 1. Scan overview ──────────────────────────────────────────────────────────
print("=" * 60)
print("SCAN OVERVIEW")
print("=" * 60)
print(f"Status:   {status}")
print(f"Message:  {message}")
print(f"Modules:  {len(modules)}")
for m in modules:
    print(f"  - {m}")
print(f"Findings: {len(findings)} total")
print()

# ── 2. Severity breakdown ─────────────────────────────────────────────────────
sev_counts   = defaultdict(int)
sev_exploits = defaultdict(list)
for f in findings:
    s = f.get("severity", 0)
    sev_counts[s] += 1
    sev_exploits[s].append(str(f.get("exploit_level", "0")))

print("SEVERITY BREAKDOWN")
print("-" * 40)
print(f"{'Severity':<12} {'Count':>6}  {'Exploitability range'}")
print("-" * 40)
for s in SEV_ORDER:
    if sev_counts[s]:
        exploits = sorted(set(sev_exploits[s]),
                          key=lambda x: int(x) if x.lstrip("-").isdigit() else 0)
        exploit_labels = [EXPLOIT_LABELS.get(e, e) for e in exploits]
        print(f"{SEV_LABELS[s]:<12} {sev_counts[s]:>6}  {', '.join(exploit_labels)}")
print()

# ── 3. Issue-type breakdown ───────────────────────────────────────────────────
type_counts = defaultdict(int)
type_max_sev = {}
for f in findings:
    itype = f.get("issue_type", "Unknown")
    type_counts[itype] += 1
    type_max_sev[itype] = max(type_max_sev.get(itype, 0), f.get("severity", 0))

print("ISSUE TYPE BREAKDOWN")
print("-" * 60)
print(f"{'Issue Type':<45} {'Count':>6}  Max Severity")
print("-" * 60)
for itype, cnt in sorted(type_counts.items(),
                         key=lambda x: (-type_max_sev[x[0]], -x[1])):
    print(f"{itype[:44]:<45} {cnt:>6}  {SEV_LABELS.get(type_max_sev[itype], '?')}")
print()

# ── 4. Per-file breakdown ─────────────────────────────────────────────────────
files_map = defaultdict(list)
for f in findings:
    sf       = f.get("files", {}).get("source_file", {})
    filepath = sf.get("file", f.get("image_path", "unknown"))
    files_map[filepath].append(f)

# Sort files by their highest severity finding descending
files_sorted = sorted(
    files_map.items(),
    key=lambda kv: -max(f.get("severity", 0) for f in kv[1])
)

print("FINDINGS BY FILE")
print("=" * 60)

id_w    = 6
sev_w   = 10
type_w  = 40
cwe_w   = 8
line_w  = 6

for filepath, file_findings in files_sorted:
    file_findings_sorted = sorted(file_findings, key=lambda f: -f.get("severity", 0))
    max_sev = SEV_LABELS.get(file_findings_sorted[0].get("severity", 0), "?")
    print(f"\nFile: {filepath}  [{len(file_findings)} finding(s), highest: {max_sev}]")
    print(f"  {'ID':<{id_w}} {'Severity':<{sev_w}} {'Issue Type':<{type_w}} {'CWE':<{cwe_w}} {'Line':>{line_w}}  Exploitability")
    print(f"  {'-'*(id_w+sev_w+type_w+cwe_w+line_w+20)}")
    for f in file_findings_sorted:
        sev     = SEV_LABELS.get(f.get("severity", 0), str(f.get("severity", "")))
        sf      = f.get("files", {}).get("source_file", {})
        line    = str(sf.get("line", ""))
        exploit = EXPLOIT_LABELS.get(str(f.get("exploit_level", "")),
                                     str(f.get("exploit_level", "")))
        print(
            f"  {f.get('issue_id', ''):<{id_w}} "
            f"{sev:<{sev_w}} "
            f"{f.get('issue_type', '')[:type_w - 1]:<{type_w}} "
            f"{f.get('cwe_id', ''):<{cwe_w}} "
            f"{line:>{line_w}}  "
            f"{exploit}"
        )
