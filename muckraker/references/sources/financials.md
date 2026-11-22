# Financials

Read the company's own financial statements and turn them into a multi-year table the coordinator can compare and reason about. The other registry agents report filing health; this source reads the numbers.

## Where the numbers are

- **US public filers:** `mr.py edgar-facts <CIK>` returns revenue, gross and operating profit, net income, cash, short-term investments, long-term debt, equity, and operating cash flow for the last five fiscal years, from the company's XBRL filings, with the latest restated value for each year. A `no_xbrl_financials` record means the CIK has never filed tagged statements. Without the script, the same data is at `https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit zero-padded CIK>.json`; use the annual (`10-K` / `20-F`, `fp: FY`) values. Open the latest annual report for the notes listed in check 3.
- **UK companies, with `uk-accounts.jsonl`:** when your prompt gives this file, the coordinator has already read the iXBRL accounts with `mr.py uk-accounts`. Take the multi-year table and derived figures from its `uk_accounts_year` and `uk_accounts_derived` records, citing their `sources` URLs; figures carry the sign the accounts print. Take check 3's parent chain, going concern, events after the year end, and borrowing from its `uk_accounts_notes` sentences, and open the accounts only for a note those sentences leave unanswered (covenants, impairments, related-party balances). Say in the report where a `sign_mismatch` shows the filer's XBRL tag disagreeing with the printed sign, For a `uk_accounts_needs_ocr` filing you need, run `mr.py uk-pages <its url> <folder>` to save its pages as images (image n is page n) and read the pages that hold the figures and notes; list a filing under Gaps as `needs OCR` only when its pages could not be read.
- **UK companies, without it:** open the latest two sets of accounts from the filing history (`https://find-and-update.company-information.service.gov.uk/company/<n>/filing-history`; each accounts entry links to `/document?format=pdf`). Accounts filed electronically also have an iXBRL version with a text layer, at the same link with `?format=xhtml`; read that first, since the PDF is often an image. For a group, use the group accounts filed by the top UK company. Each set gives two years, so two sets give three or four.
- **UK listed companies:** large companies often file their accounts at Companies House as image-only PDFs with no iXBRL version. Use the annual report PDF from the company's investor site, or its ESEF iXBRL filing on the FCA National Storage Mechanism (`https://data.fca.org.uk/#/nsm/nationalstoragemechanism`), and the latest interim results for the current year.
- **Other jurisdictions:** use the register for that country in [national-registers.md](national-registers.md), Accounts column, where it publishes accounts free. Record under Gaps any that charge or need a login.
- **Scanned accounts:** older filings with no iXBRL version are often image-only PDFs. Read them only if you have an OCR tool; otherwise list each one under Gaps as `needs OCR` with its URL, and take what figures you can from the prior-year comparatives in the next year's accounts.
- **No filed accounts** (a private US company, for example): record figures the company or reputable press have stated, each marked as a company claim or press report, and say under Gaps that no audited figures exist. Lenders' loan marks and credit ratings belong to the Debt and valuation marks and S&P Global sources; leave them to those agents.

## Checks

1. **Multi-year table:** for each of the last 3–5 years: revenue, gross profit, operating profit or loss, net profit or loss, cash and short-term investments, total debt, net assets, operating cash flow, and average headcount. State the currency and year end, and leave a cell empty rather than estimate it.
2. **Derived figures:** revenue growth for each year, operating margin, the year-on-year change in cash and investments, and runway (cash and investments divided by the last year's fall in them, when they fell and operating cash flow was negative; a fall funded by capital spending or dividends out of positive operating cash flow is not burn, so record it without a runway). Show each calculation's inputs so the coordinator can check it.
3. **The notes that predict trouble:**
   - auditor and audit opinion, and any emphasis of matter or going-concern paragraph;
   - the directors' going-concern statement and the period it covers;
   - debt: lenders, amounts, interest terms, maturity dates, and covenants, with any breach or waiver;
   - events after the balance sheet date (layoffs, refinancing, acquisitions, disposals);
   - impairments and write-offs;
   - principal risks the directors name;
   - related-party transactions and amounts owed to or by the parent.
4. **Changes between years:** a change of auditor, of year end, or of accounts type (full to abridged, for example), and any restated prior-year figures.

Report red flags here as established findings, since they come from the company's own filed accounts: a qualified or adverse opinion, material uncertainty on going concern, a covenant breach, debt due within 18 months without agreed refinancing, a runway (as check 2 defines it) under two years, or a large impairment.
