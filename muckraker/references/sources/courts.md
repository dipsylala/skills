# Courts and insolvency

Find cases the company is party to and any insolvency notices. Search the legal name, trading name, former names, and the group companies in the entity record. When your prompt gives `fr-<SIREN>.jsonl` files, French insolvency proceedings are its `fr_insolvency` records (none means BODACC has none); do not query BODACC again.

## Where to look

- **US federal courts and bankruptcy:** CourtListener holds federal and state opinions and the RECAP archive of PACER dockets. Use the first of these you have:
  - The CourtListener MCP server, when its tools are in your tool list (a `search` tool from a server named `courtlistener`, for example `mcp__courtlistener__search`): search with `type` `r` for dockets and `o` for opinions, then open dockets and documents with its item and document-reading tools. Use only its search and read tools; leave its alert, tag, subscription, and Pray and Pay tools alone, since they change the user's CourtListener account. If a call fails for authentication (the server is listed but not signed in), move to the next option and record `CourtListener MCP: not signed in` under Gaps.
  - A token in the `COURTLISTENER_API_TOKEN` environment variable: call `https://www.courtlistener.com/api/rest/v4/search/?q="<name>"&type=r` (dockets) and `&type=o` (opinions) with the header `Authorization: Token <token>`. Keep the token out of your report.
  - Without a token: CourtListener usually answers web fetch tools with HTTP 403 and its API with 401. Search `"<name>"` restricted to courtlistener.com, then open each docket page in a browser tool if you have one; otherwise record each docket from the search result as `CHECKED: snippet`. Record under Gaps that the docket search rests on search results, so suits naming the company as defendant may be missing, and that a CourtListener token or the MCP server would fill this.
  - PACER itself charges and needs a login; record dockets you could not open under Gaps.
- **US state courts:** no single index. Search `"<name>" lawsuit` together with the state of incorporation and the headquarters state, and record what the search cannot cover under Gaps.
- **UK judgments:** `https://caselaw.nationalarchives.gov.uk/search?query=<name>` (Find Case Law).
- **UK insolvency and winding-up:** `https://www.thegazette.co.uk/insolvency/notice?text="<name>"` for winding-up petitions, administration, and liquidation notices. Use this insolvency-only search: the all-notices search, by name or company number, mostly returns bulk register listings that mention thousands of companies. Check each notice's company number against the entity record. Run the UK checks when the entity record has a UK company.

## Checks

1. **Cases:** for each case, record the court, case number, filing date, parties and which side the company is on, the nature of the claim (contract, IP, employment, securities, consumer, regulatory), the amount claimed where stated, and the current status (open, dismissed, settled, judgment).
2. **Patterns:** note repeat claims of the same kind (several employment or contract suits), class actions, and cases brought by regulators or government bodies.
3. **Outcomes:** for closed cases, record the result and any amount awarded or settled. For open cases, record the next scheduled event if the docket shows one.
4. **Insolvency:** any bankruptcy filing (US) or Gazette notice (UK) about the company or a group company, with its date and type.

Status for red flags: a complaint or petition is a filed claim; a judgment, a court order, or a Gazette notice of administration or liquidation is an established finding. A suit the company brought as plaintiff is a fact, not a red flag, unless the claim reveals a problem of its own.
