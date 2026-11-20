# Company profile

What the company says about itself, and what public profiles say about it. The company's own website is the most current source for leadership; LinkedIn has no public API, puts most pages behind a login, and usually answers direct fetches with HTTP 403, so it is a fallback.

## Checks

1. **Leadership:** open the company's leadership, management, or about page and record every executive and title it lists, and any board members. Note interim or acting titles. Then search `"<company name>"` together with CEO, founder, CFO, and director, restricted to linkedin.com, and note any name or title that differs from the company page. Record names and titles only, for the coordinator to compare with registry filings.
2. **Profile:** from the company's about page and its LinkedIn company page (search `"<company name>"` restricted to linkedin.com if the page will not open), record the stated industry, headcount or headcount band, headquarters, founded year, and website. Check that the website matches the entity record.
3. **Consistency:** note where these disagree with the entity record or with each other (a different headquarters or founding year, a headcount out of line with the company's size, a leader listed on LinkedIn but not on the company page).
4. **Newsroom:** open the company's press or newsroom page and record announcements from the last 12 months about leadership, acquisitions, restructuring, or financing. Treat them as the company's own claims.
5. **Hiring signals:** open the company's careers page; if it lists nothing, search `"<company name>" jobs` restricted to linkedin.com or use public job boards. Note whether the company appears to be hiring and in which locations, as a sign of activity.
6. **Product footprint:** take the company's domain from its own site, footer, or GitHub links rather than guessing `<name>.com`, which is often parked or owned by someone else. Then record:
   - the company number in the site footer or legal page, and whether it matches the entity record;
   - the domain's registration date, from RDAP (`https://rdap.org/domain/<domain>`) or, for country domains with no RDAP (.io, .ai), port-43 WHOIS (`whois.nic.io` for .io);
   - the site's history, from the Wayback Machine (`https://web.archive.org/cdx/search/cdx?url=<domain>&fl=timestamp,statuscode`; retry on HTTP 504);
   - for a software company, its GitHub organisation (`https://api.github.com/orgs/<org>` and `/orgs/<org>/repos?sort=pushed`): created date, last push, public repos, and stars.

   Report as red flags: a site company number that does not match the entity record; and a domain registered after the founding year the company claims, or now parked or for sale. Product activity that has stopped (no GitHub push or site change for over six months) goes under Facts.
