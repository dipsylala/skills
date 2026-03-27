#!/usr/bin/env python3
"""Extract IaC/Dockerfile config findings from Veracode local scan results."""
import json, sys

if len(sys.argv) < 2:
    print("Usage: python3 extract_configs.py <veracode-json-path>")
    sys.exit(1)

data = json.load(open(sys.argv[1]))
configs = data.get('configs', [])

# Auto-detect field name casing (handles Pascal/lowercase/snake_case variations)
def get_field(obj, *names):
    for name in names:
        if name in obj:
            return obj[name]
    return 'N/A'

sev_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NEGLIGIBLE']

# Normalize severity to uppercase for consistent sorting
def get_severity(c):
    sev = get_field(c, 'Severity', 'severity', 'SEVERITY')
    return sev.upper() if isinstance(sev, str) else 'UNKNOWN'

sorted_configs = sorted(configs, key=lambda x: 
    sev_order.index(get_severity(x)) if get_severity(x) in sev_order else 99)

for c in sorted_configs:
    sev = get_field(c, 'Severity', 'severity', 'SEVERITY')
    id_val = get_field(c, 'ID', 'id', 'Id')
    title = get_field(c, 'Title', 'title')
    msg = get_field(c, 'Message', 'message')
    fix = get_field(c, 'Resolution', 'resolution', 'Fix', 'fix')
    url = get_field(c, 'PrimaryURL', 'primaryURL', 'primary_url', 'url')
    print(f"\n[{sev}] {id_val}: {title}")
    print(f"Message: {msg}")
    print(f"Fix: {fix}")
    print(f"Ref: {url}")
