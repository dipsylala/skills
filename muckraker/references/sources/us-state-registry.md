# US state registry

Each US state keeps its own register of companies and LLCs, usually run by the Secretary of State. For a private US company this is the main public record: status, formation date, registered agent, and often the officers, managers, or members. A company formed in one state (commonly Delaware) registers as a foreign entity in each other state where it does business.

## Access

- **Find every state first.** OpenCorporates copies the state registers and links each foreign registration to the company's home registration. Search `https://opencorporates.com/companies?q=<name>` (all jurisdictions; each result shows its state) and open the matching company pages (`https://opencorporates.com/companies/us_<state code>/<entity number>`); a "Branch of" or branch list on the page names the other states. Add those states to the ones the entity record lists (state of formation, headquarters state).
- **Then each state's own register.** Search the state's business entity search by name or entity number, and take facts from it rather than from the copy, which can lag. Most are free web pages. Some sit behind a CAPTCHA or bot check (California's bizfileonline.sos.ca.gov, for example); leave the CAPTCHA alone and use the OpenCorporates page for that state instead.
- **OpenCorporates limits.** Without a token, its website hides officers, incorporation dates, and filing details behind a login, and its API refuses calls; record those under Gaps. With a token in the `OPENCORPORATES_API_TOKEN` environment variable, use the API (`https://api.opencorporates.com/v0.4/`) with `api_token=<token>` as a query parameter, and keep the token out of your report: `/companies/search?q=<name>&country_code=us`, `/companies/us_<state code>/<entity number>` (officers, filings, branches), and `/officers/search?q=<person>&country_code=us`. Record which source, the state register or OpenCorporates, each fact came from.
- Delaware's public search shows name, number, formation date, and registered agent only; status and filings cost a fee. Record the fee-only items under Gaps.
- **When every route is blocked** (OpenCorporates answers 403 and the state registers are behind CAPTCHAs, forms that forbid automated use, or 403s), stop after one try at each, record each under Gaps, and report `STATUS: FAILED` without searching further. Before stopping, try the city's open business-registration data where the company has an office, which names the legal owner of a business location: for San Francisco, `https://data.sf.gov/resource/g8m3-pdis.json?$where=upper(ownership_name) like '%<NAME>%'`. It is a city record, not a state register, so say so.

## Checks

1. **Profile:** registered name, entity number, entity type (corporation, LLC, partnership), status, formation date, state of formation, principal and mailing addresses, registered agent.
2. **Status:** a status other than active or good standing: suspended, forfeited, revoked, delinquent, or administratively dissolved. In California, "Suspended - FTB" means the Franchise Tax Board suspended the entity for unpaid tax or unfiled returns.
3. **Officers and managers:** the people the latest annual report or statement of information names (officers, directors, managers, managing members), with the filing date. Note a filing that is overdue.
4. **Filing history:** formation, amendments, name changes, mergers, conversions, and the dates of annual reports or statements of information.
5. **Foreign registrations:** the other states where the entity is registered, with each one's number and status.
6. **Liens:** where the state's UCC search is free, any UCC financing statements naming the company as debtor, with the secured party and date. They show who has lent against its assets.
7. **Officers' other companies** (with an OpenCorporates token): run the officer search for each officer or manager, and record their other US companies with each one's status. Match on name and state together, since common names return many people.

Report as red flags, established by the register: a suspended, forfeited, revoked, or administratively dissolved status, in any state, that is current or began in the last three years (an older lapsed foreign registration since replaced or no longer needed goes under Facts); and an officer whose other companies were repeatedly dissolved by the state (administrative dissolution, forfeiture, revocation) rather than voluntarily. An overdue annual report or statement of information goes under Facts.
