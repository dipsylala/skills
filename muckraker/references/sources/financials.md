# Financials

Read the company's own financial statements and turn them into a multi-year table the coordinator can compare and reason about. The other registry agents report filing health; this source reads the numbers.

## Where the numbers are

- **US public filers:** `https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit zero-padded CIK>.json` holds every figure the company has tagged in its filings. Use the annual (`10-K` / `20-F`, `fp: FY`) values. Open the latest annual report for the notes listed in check 3.
- **UK companies:** open the latest two sets of accounts from the filing history (`https://find-and-update.company-information.service.gov.uk/company/<n>/filing-history`; each accounts entry links to `/document?format=pdf`). For a group, use the group accounts filed by the top UK company. Each set gives two years, so two sets give three or four.
- **Other jurisdictions:** use the national register named in the entity record where it publishes accounts (for example Germany's Unternehmensregister, France's Infogreffe, Ireland's CRO). Record under Gaps any that charge or need a login.
- **Scanned accounts:** older filings are often image-only PDFs with no text layer. Read them only if you have an OCR tool; otherwise list each one under Gaps as `needs OCR` with its URL, and take what figures you can from the prior-year comparatives in the next year's accounts.
- **No filed accounts** (a private US company, for example): record figures the company or reputable press have stated, each marked as a company claim or press report, and say under Gaps that no audited figures exist.

## Checks

1. **Multi-year table:** for each of the last 3–5 years: revenue, gross profit, operating profit or loss, net profit or loss, cash and short-term investments, total debt, net assets, operating cash flow, and average headcount. State the currency and year end, and leave a cell empty rather than estimate it.
2. **Derived figures:** revenue growth for each year, operating margin, the year-on-year change in cash and investments, and runway (cash and investments divided by the last year's fall in them, when they fell). Show each calculation's inputs so the coordinator can check it.
3. **The notes that predict trouble:**
   - auditor and audit opinion, and any emphasis of matter or going-concern paragraph;
   - the directors' going-concern statement and the period it covers;
   - debt: lenders, amounts, interest terms, maturity dates, and covenants, with any breach or waiver;
   - events after the balance sheet date (layoffs, refinancing, acquisitions, disposals);
   - impairments and write-offs;
   - principal risks the directors name;
   - related-party transactions and amounts owed to or by the parent.
4. **Changes between years:** a change of auditor, of year end, or of accounts type (full to abridged, for example), and any restated prior-year figures.

Report red flags here as established findings, since they come from the company's own filed accounts: a qualified or adverse opinion, material uncertainty on going concern, a covenant breach, debt due within 18 months without agreed refinancing, a falling cash runway under two years, or a large impairment.
