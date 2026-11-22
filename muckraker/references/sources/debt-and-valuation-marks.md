# Debt and valuation marks

Lenders and funds that file with the SEC publish what they hold and what they think it is worth. For a private or private-equity-owned company this is often the only outside view of its debt and valuation.

- **Business development companies (BDCs)** and private credit funds list every loan in a schedule of investments in their 10-K and 10-Q filings: borrower, instrument, interest terms, maturity, principal, cost, and fair value.
- **Mutual funds and closed-end funds** list their holdings, including private company shares, in N-PORT and N-CSR filings, valued each quarter.

These values are the holders' own fair-value estimates, not market prices. Report them as such.

When Python and the SEC `User-Agent` are available, the coordinator runs this source itself with `mr.py marks` (SKILL.md step 3) instead of sending an agent; this file's checks apply either way.

## Finding the holders

A company bought by private equity usually borrows through an acquisition company with an unrelated code name (a buyout loan to "Acme Software" might be filed under "Falcon Purchaser, Inc."), and most holders list only that name. Before searching, collect the borrower names:

- the company's legal and trading names, and its former names, and any parent names in the entity record;
- parent and holding company names from a subsidiary's latest accounts: open them yourself (for a UK subsidiary, from its Companies House filing history; the `?format=xhtml` version of an accounts document has a text layer) and search for "ultimate parent" and "controlling party";
- names that turn up beside the company's name in fund filings: search `"<name>"` in N-PORT filings, and note the issuer names in the matching holdings, which often read "<company> (<acquisition company>)".

Holders spell the same borrower differently (one lists "Falcon Corporate Purchaser, Inc.", another "Falcon Purchaser, Inc."), and the search matches exact phrases, so also search the most distinctive single word of each alias ("Falcon").

**With the script:** `mr.py marks "<alias>" "<distinctive word>" "<company name>" ...` searches lenders' 10-K and 10-Q filings and funds' N-PORT filings from the last 15 months, takes each holder's latest filing and the one closest to a year earlier, and returns one record per matching row:

- `loan_or_equity`: a row from a lender's tagged schedule of investments, with principal, cost, fair value, `mark` (fair value as a percentage of principal), interest rate, spread, maturity, the row's identifier text, and `quote`: the row as the page shows it, figures included, to use as the red flag's quote;
- `fund_holding`: an N-PORT holding, with the fund's name and `series_id`, balance, value, `mark`, maturity, and the fund's own default, arrears, and PIK flags. One trust files separately for each of its funds, so compare a fund's mark only with the same fund's earlier mark (the same `series_id`; a fund can be renamed);
- `table_row`: a matching row from a schedule without row-level tags, with the table's column headings as `header`, the date in the heading above the table as `table_date` (a filing's prior-period schedule carries the earlier date), and the filing's `period_ending`, as text for you to read;
- `no_earlier_filing`: a holder, or with `fund` one fund of a trust, with no filing about a year before its latest, so it has no trend point; nothing was substituted;
- `search_summary`: printed when a search found more filings than it read (`truncated`); widen `--since` or add a narrower alias.

Records can carry `notes`: a revolving or delayed-draw facility (its mark is not comparable with a term loan's, since fair value can include unfunded commitments), a position held through the filer's joint venture (it may duplicate the filer's direct position, so count it once in the debt picture), or a negative fair value (no mark computed). A negative fair value on a revolver is real, not an error: the filer values the funded amount and the unfunded commitment together, and a discount on a large unfunded commitment outweighs the funded part. Find the unfunded amount in the filer's unfunded-commitments table (a `table_row` naming the borrower often carries it) and work out the implied mark as 100 × (fair value + unfunded) ÷ (principal + unfunded); for example, fair value −2,031 on 1,438 funded and 7,938 unfunded implies about 63. `--verbose` also prints filings that matched the search but had no row for these names, usually companies naming the borrower as a customer.

A lender's row carries `flagged_footnotes` when the filing links a footnote mentioning non-accrual, PIK, an amendment, a default, or a waiver to that row; report those as the filing states them. Lenders that put such marks only in the row text, without linked footnotes, show up in a `table_row` or not at all: for a loan whose mark is falling and that has no `flagged_footnotes`, open its latest filing and check the row's footnote markers. Use `--since`, `--per-filer` (more points for a trend), and `--max-filers` to widen the search. To search more names after a first run, add `--skip-seen <first output file>` and append to that file: it skips names the first run's searches already covered and records the file already has.

**Without the script:** search EDGAR full-text search for each borrower name, for loans at `https://efts.sec.gov/LATEST/search-index?q="<name>"&forms=10-K,10-Q` and for fund holdings at `https://efts.sec.gov/LATEST/search-index?q="<name>"&forms=NPORT-P,N-CSR`. Keep the hits from lenders and funds (names with Capital, Credit, Lending, BDC, Fund, or Trust are typical) and set aside companies that mention the name as a customer or competitor. Open the most recent filing from each holder, and the same holder's filing from about a year earlier.

Either way, report each alias you used and the filing that links it to the company, so the coordinator can check the link.

## Checks

1. **Loans:** for each lender and instrument (first lien term loan, revolver, second lien), record the interest terms (reference rate and spread, any PIK interest), maturity date, principal, cost, and fair value. Work out the mark as fair value divided by principal.
2. **Loan trend:** compare each loan's mark with the earlier filing. Note a mark below 95, a fall of more than 3 points, interest moved from cash to PIK, an amended or extended maturity, or a loan placed on non-accrual.
3. **Debt picture:** add up the principal across lenders for an estimate of total debt, and note the nearest maturity. Say that lenders who do not file with the SEC are missing.
4. **Equity holdings:** for each fund holding the company's shares, record shares held and value, and work out value per share. Compare with the earlier filing and with the price of the last funding round if the entity record or press gives one. Note a markdown of more than 20%.

Report red flags as established findings about the holder's valuation, citing the filing: "<Lender> valued the first lien term loan at <mark> at <period end> (<filing URL>)."
