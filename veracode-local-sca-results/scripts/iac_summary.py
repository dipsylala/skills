#!/usr/bin/env python3
"""Extract IaC/Dockerfile config findings from Veracode local scan results."""
import json, sys

if len(sys.argv) < 2:
    print("Usage: python3 extract_configs.py <veracode-json-path>")
    sys.exit(1)

data = json.load(open(sys.argv[1]))
configs = data.get('configs', [])

sev_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NEGLIGIBLE']

sorted_configs = sorted(configs, key=lambda x:
    sev_order.index(x['Severity']) if x.get('Severity') in sev_order else 99)

for c in sorted_configs:
    print(f"\n[{c.get('Severity', 'N/A')}] {c.get('ID', 'N/A')}: {c.get('Title', 'N/A')}")
    print(f"Message: {c.get('Message', 'N/A')}")
    print(f"Fix: {c.get('Resolution', 'N/A')}")
    print(f"Ref: {c.get('PrimaryURL', 'N/A')}")
