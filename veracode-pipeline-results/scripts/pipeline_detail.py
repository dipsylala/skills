#!/usr/bin/env python3
"""Extract full detail for a specific Veracode pipeline scan finding.

Strips HTML from display_text, presents description/remediation/references
as plain text, and reconstructs the taint data path from stack_dumps.

Usage: python3 pipeline_detail.py <filtered_results.json> <issue_id>
"""
import html, json, re, sys

if len(sys.argv) < 3:
    print("Usage: python3 pipeline_detail.py <filtered_results.json> <issue_id>")
    sys.exit(1)

SEV_LABELS = {
    5: "Very High", 4: "High", 3: "Medium",
    2: "Low",       1: "Very Low",  0: "Informational",
}
EXPLOIT_LABELS = {
    "-2": "Very Unlikely", "-1": "Unlikely", "0": "Neutral",
    "1": "Likely",         "2": "Very Likely",
}


def strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r" {2,}", " ", text).strip()


def extract_spans(raw: str) -> list[str]:
    """Return plain text for each top-level <span> block."""
    spans = re.findall(r"<span[^>]*>(.*?)</span>", raw, re.DOTALL | re.IGNORECASE)
    return [strip_tags(s) for s in spans]


def clean_varname(var: str) -> str:
    """Strip /**X-VC … */ taint-tracking annotations, keep readable expression."""
    return re.sub(r"/\*\*X-VC.*?\*/", "", var).strip()


# ── Load finding ──────────────────────────────────────────────────────────────
data     = json.load(open(sys.argv[1]))
issue_id = int(sys.argv[2])

finding = next(
    (f for f in data.get("findings", []) if f.get("issue_id") == issue_id),
    None,
)
if not finding:
    print(f"No finding with issue_id {issue_id}")
    sys.exit(1)

sev     = SEV_LABELS.get(finding.get("severity", 0), str(finding.get("severity")))
exploit = EXPLOIT_LABELS.get(str(finding.get("exploit_level", "")),
                              str(finding.get("exploit_level", "")))
sf      = finding.get("files", {}).get("source_file", {})

# ── Header ────────────────────────────────────────────────────────────────────
print(f"Finding #{issue_id}: {finding.get('issue_type', '')} (CWE-{finding.get('cwe_id', '')})")
print(f"Severity:   {sev} ({finding.get('severity')})")
print(f"File:       {sf.get('file', finding.get('image_path', ''))}")
print(f"Line:       {sf.get('line', '')}")
print(f"Function:   {sf.get('qualified_function_name', sf.get('function_name', ''))}")
print(f"Exploitability: {exploit} ({finding.get('exploit_level', '')})")
print()

# ── display_text sections ─────────────────────────────────────────────────────
spans = extract_spans(finding.get("display_text", ""))

labels = ["Description", "Remediation", "References"]
for i, label in enumerate(labels):
    if i < len(spans) and spans[i]:
        print(f"{label}:")
        # Wrap long lines at ~120 chars for readability
        text = spans[i]
        for para in text.split("  "):
            para = para.strip()
            if para:
                print(f"  {para}")
        print()

# ── Stack dump / data path ────────────────────────────────────────────────────
sd              = finding.get("stack_dumps", {})
stack_dump_list = sd.get("stack_dump", []) if isinstance(sd, dict) else []

if stack_dump_list:
    print("Data path (taint flow, Source → Sink):")
    for dump in stack_dump_list:
        frames = dump.get("Frame", [])
        # Descending FrameId = source first, 0 = sink
        frames_sorted = sorted(frames, key=lambda fr: -int(fr.get("FrameId", 0)))
        total = len(frames_sorted)
        for i, fr in enumerate(frames_sorted):
            if i == 0:
                label = "[Source]"
            elif i == total - 1:
                label = "[Sink]  "
            else:
                label = "        "
            loc    = f"{fr.get('SourceFile', '')}:{fr.get('SourceLine', '')}"
            fn     = f"  {fr['FunctionName']}" if fr.get("FunctionName") else ""
            var    = clean_varname(fr.get("VarNames", ""))
            var_str = f"  —  {var}" if var else ""
            print(f"  {label} {loc}{fn}{var_str}")
    print()
    print("Verdict: <confirm whether source is user-controlled or a false positive>")
else:
    print("Data path: no stack dump available for this finding.")
