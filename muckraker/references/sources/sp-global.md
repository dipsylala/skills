# S&P Global

Most S&P Global data (Capital IQ, Market Intelligence) is subscription-only. Report what is public, and list the rest under Gaps so the user knows what a subscriber could add.

## Checks

1. **Credit ratings:** open S&P Global Ratings' public search for the company's name, and for its parent or acquisition-company names when the rated entity may differ (a private-equity-owned "Acme Software" is often rated as its holding company, "Acme Parent L.P."):
   `https://www.spglobal.com/ratings/en/regulatory/consolidated-search-landing/searchType/Entity/searchTerm/<name>`
   The page needs a real browser: curl and web fetch tools get HTTP 403. Open it with a browser tool if you have one. If you have none, write `RATINGS SEARCH: needs a browser` under Gaps, and the coordinator will open it. In the browser, read the rating actions' text on their article pages; never open a PDF link (a tear sheet or report download), which starts a download on the user's screen. Record a PDF you could not read under Gaps with its title and URL.
   For each rating action listed (research updates, downgrades, upgrades, outlook changes, tear sheets), record the date, the rated entity, the issuer and issue ratings before and after, the outlook, and the reason S&P gives in the summary. Tear sheet summaries often give figures the company never publishes (revenue trend, recurring revenue, margins, leverage); record them as S&P's figures. Report a downgrade, a rating of CCC+ or below, a negative outlook, or a CreditWatch negative placement as a red flag, established by S&P's rating action.
2. **Market Intelligence news:** search `"<company name>" "Market Intelligence"` restricted to spglobal.com for public articles that mention the company, and record what each says about it.
3. **Indices:** note whether the company is in an S&P index (S&P 500, S&P SmallCap 600, and others), and any recent addition or removal.
4. **Paywalled data:** when a result leads to a login or subscription page, record its title and URL under Gaps rather than its content.
