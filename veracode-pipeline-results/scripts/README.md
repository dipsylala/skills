# Veracode Pipeline Scan Analysis Scripts

Scripts for extracting structured data from Veracode pipeline scan JSON results, optimised for LLM consumption.

## Scripts

### `pipeline_summary.py`

Extracts a high-level summary: scan status, modules scanned, severity breakdown, issue-type breakdown, and findings grouped by source file (no stack dumps).

```bash
python3 pipeline_summary.py <filtered_results.json>
```

**Sample output:**

```text
============================================================
SCAN OVERVIEW
============================================================
Status:   SUCCESS
Message:  Analysis Successful
Modules:  2
  - app.jar
  - lib.jar
Findings: 7 total

SEVERITY BREAKDOWN
----------------------------------------
Severity     Count  Exploitability range
----------------------------------------
Very High        1  Likely
High             3  Neutral, Likely
Medium           2  Unlikely
Low              1  V.Unlikely

ISSUE TYPE BREAKDOWN
------------------------------------------------------------
Issue Type                                    Count  Max Severity
------------------------------------------------------------
Improper Neutralization of Input (SQL)            2  Very High
Path Traversal                                    2  High
Cross-Site Scripting (Reflected)                  2  High
Insecure Randomness                               1  Medium

FINDINGS BY FILE
============================================================

File: src/main/java/com/example/UserController.java  [3 finding(s), highest: Very High]
  ID     Severity   Issue Type                               CWE      Line  Exploitability
  ------------------------------------------------------------------
  12     Very High  Improper Neutralization of Input (SQL)   89        142  Likely
  8      High       Cross-Site Scripting (Reflected)         79         98  Neutral
  3      Medium     Insecure Randomness                      330        57  Unlikely

File: src/main/java/com/example/FileHelper.java  [2 finding(s), highest: High]
  ID     Severity   Issue Type                               CWE      Line  Exploitability
  ------------------------------------------------------------------
  5      High       Path Traversal                           22         34  Likely
  6      High       Path Traversal                           22         81  Neutral
```

### `pipeline_detail.py`

Extracts full detail for a single finding by `issue_id`: plain-text description, remediation, references (HTML stripped from `display_text`), and the taint data path reconstructed from `stack_dumps` (source → sink).

```bash
python3 pipeline_detail.py <filtered_results.json> <issue_id>
```

**Example:**

```bash
python3 pipeline_detail.py filtered_results.json 12
```

**Sample output:**

```text
Finding #12: Improper Neutralization of Special Elements used in an SQL Command (CWE-89)
Severity:   Very High (5)
File:       src/main/java/com/example/UserController.java
Line:       142
Function:   com.example.UserController.getUser(HttpServletRequest)
Exploitability: Likely (1)

Description:
  This database query is constructed dynamically using user-supplied input from
  request.getParameter("id") without sanitization, allowing an attacker to alter
  the query logic.

Remediation:
  Use parameterized queries or prepared statements instead of string concatenation.
  Validate and allowlist all user-supplied input before use in queries.

References:
  CWE-89: https://cwe.mitre.org/data/definitions/89.html
  OWASP: https://owasp.org/www-community/attacks/SQL_Injection

Data path (taint flow, Source → Sink):
  [Source] src/main/java/com/example/UserController.java:138  getUser()  —  request.getParameter("id")
           src/main/java/com/example/UserController.java:140  getUser()  —  queryStr
  [Sink]   src/main/java/com/example/UserController.java:142  getUser()  —  stmt.executeQuery(queryStr)

Verdict: <confirm whether source is user-controlled or a false positive>
```

**Use this when** the user asks for more information on a specific flaw, wants to assess exploitability, or needs to verify whether a finding is a false positive.
