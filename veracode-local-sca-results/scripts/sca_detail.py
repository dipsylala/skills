#!/usr/bin/env python3
"""Extract detailed CVE information for a specific component."""
import json, sys

if len(sys.argv) < 3:
    print("Usage: python3 sca_detail.py <veracode-json-path> <component-name>")
    sys.exit(1)

sev_order = ['Critical', 'High', 'Medium', 'Low', 'Negligible']
data = json.load(open(sys.argv[1]))
comp = sys.argv[2]

matches = [m for m in data['vulnerabilities']['matches'] 
           if m['artifact']['name'] == comp]

if not matches:
    print(f'No matches for: {comp}')
    sys.exit(1)

a = matches[0]['artifact']
print(f"Component: {a['name']} @ {a['version']} ({a['type']})")
print(f"Location:  {a['locations'][0]['accessPath']}\n")

# Deduplicate CVEs
seen = {}
for m in matches:
    if m['vulnerability']['id'] not in seen:
        seen[m['vulnerability']['id']] = m

for m in sorted(seen.values(), 
                key=lambda m: sev_order.index(m['vulnerability']['severity']) 
                if m['vulnerability']['severity'] in sev_order else 99):
    v = m['vulnerability']
    cvss3 = next((c['metrics']['baseScore'] for c in v.get('cvss', []) 
                  if c.get('type') == 'Primary' and 
                  str(c.get('version', '')).startswith('3')), 'n/a')
    fix_vers = ', '.join(v['fix'].get('versions') or ['none available'])
    
    print(f"CVE:         {v['id']}")
    print(f"Severity:    {v['severity']} (CVSS3: {cvss3})")
    print(f"Description: {v['description']}")
    print(f"Fix state:   {v['fix']['state']}")
    print(f"Fix version: {fix_vers}")
    print(f"Advisory:    {v['dataSource']}\n")
