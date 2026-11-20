# Debt and valuation marks

Lenders and funds that file with the SEC publish what they hold and what they think it is worth. For a private or private-equity-owned company this is often the only outside view of its debt and valuation.

- **Business development companies (BDCs)** and private credit funds list every loan in a schedule of investments in their 10-K and 10-Q filings: borrower, instrument, interest terms, maturity, principal, cost, and fair value.
- **Mutual funds and closed-end funds** list their holdings, including private company shares, in N-PORT and N-CSR filings, valued each quarter.

These values are the holders' own fair-value estimates, not market prices. Report them as such.

## Finding the holders

A company bought by private equity usually borrows through an acquisition company with an unrelated name (Veracode's buyout loan is filed under "Mitnick Corporate Purchaser, Inc."), and most holders list only that name. Before searching, collect the borrower names:

- the company's legal and trading names, and its former names;
- parent and holding company names from a subsidiary's accounts (the note naming the immediate and ultimate parent) and from the UK register of persons with significant control;
- names that turn up beside the company's name in fund filings: search `"<name>"` in N-PORT filings, and note the issuer names in the matching holdings, which often read "<company> (<acquisition company>)".

Search EDGAR full-text search for each borrower name:

- loans: `https://efts.sec.gov/LATEST/search-index?q="<name>"&forms=10-K,10-Q`
- fund holdings: `https://efts.sec.gov/LATEST/search-index?q="<name>"&forms=NPORT-P,N-CSR`

Report each alias you used and the filing that links it to the company, so the coordinator can check the link.

Send the SEC `User-Agent` the coordinator gave you; without one, use the web fetch tool. Keep the hits from lenders and funds (names with Capital, Credit, Lending, BDC, Fund, or Trust are typical) and set aside companies that mention the name as a customer or competitor. Open the most recent filing from each holder, and the same holder's filing from about a year earlier.

## Checks

1. **Loans:** for each lender and instrument (first lien term loan, revolver, second lien), record the interest terms (reference rate and spread, any PIK interest), maturity date, principal, cost, and fair value. Work out the mark as fair value divided by principal.
2. **Loan trend:** compare each loan's mark with the earlier filing. Note a mark below 95, a fall of more than 3 points, interest moved from cash to PIK, an amended or extended maturity, or a loan placed on non-accrual.
3. **Debt picture:** add up the principal across lenders for an estimate of total debt, and note the nearest maturity. Say that lenders who do not file with the SEC are missing.
4. **Equity holdings:** for each fund holding the company's shares, record shares held and value, and work out value per share. Compare with the earlier filing and with the price of the last funding round if the entity record or press gives one. Note a markdown of more than 20%.

Report red flags as established findings about the holder's valuation, citing the filing: "<Lender> valued the first lien term loan at <mark> at <period end> (<filing URL>)."
