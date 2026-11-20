# SEC EDGAR

EDGAR holds US public filings, and also filings by private companies raising money (Form D) and foreign issuers (20-F, 6-K).

## Access

- Find the CIK: `https://www.sec.gov/files/company_tickers.json` for listed companies, or the company search at `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=<name>`.
- Filing list: `https://data.sec.gov/submissions/CIK<10-digit zero-padded CIK>.json`.
- Full-text search across filings since 2001: `https://efts.sec.gov/LATEST/search-index?q="<name>"`. Use it for the company named in other companies' filings, as a customer, supplier, defendant, or acquisition. Hits in lenders' and funds' holdings (BDC schedules of investments, N-PORT) belong to the Debt and valuation marks source: record how many there are in one line and leave them.

## Checks

1. **Identity:** CIK and the registered filer name (report it if it is a different group company from the one in the entity record), filer name history (former names), state of incorporation, business address, SIC code.
2. **Filing pattern:** the forms filed in the last 3 years. Note late filings (NT 10-K, NT 10-Q), a stop in filing, and deregistration (Form 15).
3. **Annual report** (10-K or 20-F, latest): risk factors that name specific problems, and the Legal Proceedings section. The Financials agent reads the figures, auditor, and going-concern language.
4. **Events** (8-K, latest 3 years): Item 4.01 auditor changes, 4.02 restatements, 5.02 officer departures, 1.03 bankruptcy.
5. **Ownership and insiders:** the latest proxy (DEF 14A) for officers, directors, and pay; Schedules 13D and 13G for large holders; Forms 3, 4, and 5 for heavy insider selling.
6. **Private raises:** Form D filings, with amounts raised and the related persons listed.
7. **Enforcement:** search the name restricted to sec.gov together with "litigation release" and with "administrative proceeding", and open each hit that names the company.

A company with no EDGAR filings is a valid result: report `STATUS: NOTHING FOUND` with the searches you ran.
