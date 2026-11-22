# UK Companies House

The UK register of companies, at `https://find-and-update.company-information.service.gov.uk`. Both the website and the API are free.

## Access

An overseas company (an FC number) is a foreign company's UK registration: it has a UK establishment (a BR number) and must register within one month of opening it. `mr.py ch` lists the establishment and flags a late registration as minor. Its accounts are its home-country accounts, delivered within three months of their publication, or, where home law does not require it to publish, within 13 months of each period end.

When Python is available and `COMPANIES_HOUSE_API_KEY` is set, the coordinator runs this source itself with `mr.py ch` (SKILL.md step 3), which also works out late filings against the statutory deadlines; this file's checks apply either way. The routes below are the manual path.

- With an API key in the `COMPANIES_HOUSE_API_KEY` environment variable: call `https://api.company-information.service.gov.uk` with the key as the HTTP basic auth username and an empty password. Keep the key out of your report and out of any command output you quote.
- Without a key: fetch the public website pages. For company number `<n>`: `/company/<n>`, `/company/<n>/officers`, `/company/<n>/persons-with-significant-control`, `/company/<n>/filing-history`, `/company/<n>/charges`, `/company/<n>/insolvency`.
- Find the company number with the website's search (`/search/companies?q=<name>`) or the API's `/search/companies?q=<name>`. When several companies match, use the one whose name, address, and status fit the entity record; list the near misses under Gaps.

## Checks

1. **Profile:** registered name and number, status (active, dissolved, in administration, liquidation), incorporation date, registered office, SIC codes, previous names.
2. **Filing health:** accounts and confirmation statement due dates, and whether either is overdue. Note a "compulsory strike-off" or "first Gazette notice" in the filing history.
3. **Accounts:** the latest accounts' type (micro, small, full, group, dormant) and filing date. Note a late filing. The Financials agent reads the figures and notes.
4. **Officers:** current and resigned directors and secretaries, with appointment dates. Note a director who resigned shortly before a problem, and very high officer turnover.
5. **Persons with significant control:** who owns or controls the company, and through what chain. Note control held through overseas or nominee companies, and statements that the PSC cannot be identified.
6. **Charges:** outstanding charges (secured lending), with the lender and date.
7. **Insolvency:** any insolvency case and its practitioner. The `/insolvency` page often returns HTTP 500; when it does, record the status from the profile page (active, in administration, liquidation) and any insolvency filings in the filing history instead.
8. **Group:** record the immediate parent, ultimate parent, and ultimate controlling party named in the latest accounts' related-party or controlling-party note (read the `?format=xhtml` version of the accounts document and search for "ultimate parent" and "controlling party"). Then check the parent named in the PSC register, and any UK subsidiaries the entity record lists, with checks 1 and 2.
9. **Share capital and funding** (for a company under about seven years old, or one with no full accounts, where these filings are the only filed money figures):
   - List each SH01 (return of allotment) in the filing history: allotment date, share class, number allotted, and amount paid per share. An electronically filed SH01 has a text layer: read it with `mr.py pdf-text <its document?format=pdf url>` (web fetch cannot follow Companies House document links, which redirect to short-lived storage URLs). SH02 and SH08 PDFs are often image-only (read those with `mr.py uk-pages`), so take class names and totals from the SH01 statements of capital where you can.
   - Work out the cash raised per round (number × price paid) and the implied post-money valuation (price × total shares in issue after the allotment). Show the inputs.
   - Tie each round to the filings around it: new articles (RES01, MA), allotment authority and disapplied pre-emption (RES10, RES11), and class changes (SH08, SH10). New articles with a new share class usually mark a priced round.
   - Read the latest confirmation statement filed "with updates": its shareholder list gives founders' stakes, funds and nominees, crowdfunding nominees (Seedrs, Crowdcube), and angel investors. Record funds and nominees by name, and count individual angels rather than naming them.
   - Founders' other companies: for each director, open `/officers/<officer id>/appointments`, and for each company that ended, read its filing history to tell a voluntary strike-off (DS01) apart from a compulsory strike-off (first Gazette notice with no DS01), liquidation (LIQ forms), or administration (AM forms).

   Report as red flags, established by the register: an allotment price below an earlier round's price for the same or a senior class (a down round), outside option grants and same-day discount tranches; shares allotted with a large amount unpaid; and a director whose earlier company ended in compulsory strike-off, liquidation, or administration, or who is disqualified. A voluntary strike-off of a company that never traded goes under Facts.
