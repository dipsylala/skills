#!/usr/bin/env python3
"""Extract SCA vulnerability summary from Veracode local scan results."""
import json, sys
from collections import defaultdict

if len(sys.argv) < 2:
    print("Usage: python3 sca_summary.py <veracode-json-path>")
    sys.exit(1)

sev_order = ['Critical', 'High', 'Medium', 'Low', 'Negligible']
data = json.load(open(sys.argv[1]))

# Extract policy status and secrets
secrets_count = len(data.get('secrets', []))
policy_status = 'unknown'
if data.get('vulnerabilities', {}).get('matches'):
    policy_status = data['vulnerabilities']['matches'][0].get('customerPolicyResult', {}).get('Status', 'not evaluated')

comps = defaultdict(list)

for m in data['vulnerabilities']['matches']:
    comps[m['artifact']['name'] + '@' + m['artifact']['version']].append(m)

rows = []
for k, v in comps.items():
    sev = min((m['vulnerability']['severity'] for m in v), 
              key=lambda s: sev_order.index(s) if s in sev_order else 99)
    cves = len({m['vulnerability']['id'] for m in v})
    fv = sorted({ver for m in v for ver in (m['vulnerability']['fix'].get('versions') or [])})
    rows.append((k, sev, cves, fv[-1] if fv else 'none'))

rows.sort(key=lambda r: sev_order.index(r[1]) if r[1] in sev_order else 99)

# Compute totals
total_components = len(rows)
total_cves = sum(r[2] for r in rows)
cves_by_sev = defaultdict(int)
for r in rows:
    cves_by_sev[r[1]] += r[2]
sev_parts = ' '.join(f"{cves_by_sev[s]} {s}" for s in sev_order if cves_by_sev[s] > 0)
print(f"Policy: {policy_status} | Secrets: {secrets_count} | Components: {total_components} | Total CVEs: {total_cves} ({sev_parts})")
print()

print(f"{'Component':<55} {'Sev':<10} {'CVEs':<6} Fix")
for r in rows:
    print(f'{r[0]:<55} {r[1]:<10} {r[2]:<6} {r[3]}')
