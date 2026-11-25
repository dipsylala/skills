---
name: muckraker
description: Research a company in parallel across press, registries, financials, lender marks, ratings, and courts, and report a cited dossier of red flags.
disable-model-invocation: true
---

# Muckraker

Given a company name, find out who the company is, what it has filed, what has been reported about it, and where the sources disagree. You are the coordinator: you pin down the entity, send one research agent per source, and write the dossier from their reports. Every fact in the dossier carries a citation.

## 1. Pin down the entity

Take the company name and anything else the user gave (country, website, ticker, company number). When the user names several companies, build one entity record per company and run every later step for each. Each company sends up to 13 agents, so with more than two companies, ask the user which two to research first before sending any agents, and research the others only when they ask. Search the web to find the candidates.

- One clear match: build its entity record, as the steps below say.
- Several plausible matches (different countries, a parent and its subsidiaries, a similar name): list them with what tells them apart and ask the user which one to research. Researching the wrong "Acme Ltd" wastes every agent you send.
- No match: tell the user what you searched and ask for more detail (country, website, company number) before going further.

### The entity record

Record the legal name, jurisdiction, website, ticker, SEC CIK, UK company number, US state of formation and state entity number, and parent company, as far as you can find them. Leave a field empty rather than guess it, say where each number came from, and mark anything nothing confirms as unconfirmed. Work through these:

1. **Confirm each registry identifier.** Look it up in its registry and check that the name it returns is the entity you mean (a CIK can belong to the UK parent rather than the US company); record the registered name beside the identifier. Until the user has given the SEC contact (section 2), reach sec.gov only through the web fetch and search tools: confirm a CIK by fetching `https://data.sec.gov/submissions/CIK<10-digit zero-padded CIK>.json` with the web fetch tool and checking its `name` field, which is the intended route here, not a workaround (the `browse-edgar` company page comes back blank through web fetch).
2. **Find the US state of formation.** When a state register sits behind a CAPTCHA or forbids automated use (Delaware's does), run `python <skill folder>/scripts/mr.py us-states "<name>"`: other states' open registers often hold the entity's foreign registration, which names its state of formation (see [us-state-registry.md](references/sources/us-state-registry.md)). If nothing confirms the number, leave it to the US state registry agent.
3. **Look the entity up in GLEIF.** Run `python <skill folder>/scripts/mr.py gleif "<legal name>"` to find the LEI, or `mr.py gleif --registered-as <national register number>` when the name finds none, then `mr.py gleif <LEI>` for the parent chain and subsidiaries (without Python, the API in [gleif.md](references/sources/gleif.md)). Record the LEI and the countries its parents and subsidiaries are registered in: they decide which registers section 2 sends agents to. A candidate whose `category` is `FUND`, or a `gleif_fund` record, is a fund vehicle such as an investor's sub-fund named after the company, not the company: leave it out. Run `mr.py gleif` for each acquired company's own name too: an acquired subsidiary, often a regulated one, keeps an LEI of its own that a search for the parent's name never finds.
4. **Check an EU company's current name.** Run `mr.py vat <country> <VAT number>` (VIES): most countries return the name the tax authority holds now, which catches a holding renamed after the brand was set, while the press still uses the old name. GLEIF's `other_names` keeps former names too.
5. **Find the group companies.**
   - For an entity registered outside the UK, search Companies House for its name (`mr.py ch-search "<name>"` when `COMPANIES_HOUSE_API_KEY` is set; otherwise `https://find-and-update.company-information.service.gov.uk/search/companies?q=<name>`): add any UK company with the same directors and any overseas registration (an FC number, with its UK establishment) to the record, which brings in UK Companies House.
   - A venture-backed company outside the US often sits under a US holding company ("<name> Holdings, Inc.", usually in Delaware) and contracts through a US subsidiary. Search the company's press releases for "registered in the U.S. as", and read its data processing agreement, terms, and subprocessor or affiliates list for the contracting entities and group companies: a subprocessor list often names every subsidiary with its address, more than the about page does. Terms pages are often named after the entity, such as `/general-terms-<company>-inc-<date>`; read a terms PDF with `mr.py pdf-text <url>`. Add any US entity to the record.
   - For a Dutch company, also read the group heads named on its KvK product page (the Netherlands row in [national-registers.md](references/sources/national-registers.md)).
6. **Search the CEO's and founders' names,** since a group company can carry a name or address the company name never finds:
   - in EDGAR full-text search for Form D: fetch `https://efts.sec.gov/LATEST/search-index?q=%22<first%20last>%22&forms=D` with the web fetch tool; the filer named in each hit is a US company that raised money with that person as an officer, often the US parent of a "flip";
   - in Companies House's officer search (`https://find-and-update.company-information.service.gov.uk/search/officers?q=<name>`), which finds a UK subsidiary that a name search for a common word buries among hundreds of unrelated companies.
7. **Note a US office with no known US entity.** Add the office's city and state to the record, so the US state registry agent searches for the entity behind it.

Done when one entity is confirmed (by the user, or as the only match) and you have worked through items 1–7 above, with each identifier recorded beside its source or left empty.

## 2. Choose the sources

Each source has its own reference file in [references/sources/](references/sources/):

| Source | File | Run when | Queries sec.gov |
| --- | --- | --- | --- |
| Press | [press.md](references/sources/press.md) | Always | No |
| Company profile | [company-profile.md](references/sources/company-profile.md) | Always | No |
| SEC EDGAR | [sec-edgar.md](references/sources/sec-edgar.md) | Always: a private or foreign company can still file (Form D, 20-F), and finding nothing is a result | Yes |
| UK Companies House | [companies-house.md](references/sources/companies-house.md) | The entity, its parent, or a subsidiary is UK-registered, or the jurisdiction is unknown | No |
| US state registry | [us-state-registry.md](references/sources/us-state-registry.md) | The entity, its parent, or a subsidiary is registered in a US state, the entity record names a US office with no known US entity, or the jurisdiction is unknown | No |
| National registers | [national-registers.md](references/sources/national-registers.md) | The entity, its parent, or a subsidiary is registered outside the US and UK | No |
| GLEIF ownership | [gleif.md](references/sources/gleif.md) | Always: a company with no LEI is a result | No |
| Sanctions and offshore | [sanctions-offshore.md](references/sources/sanctions-offshore.md) | Always | No |
| Startup | [startup.md](references/sources/startup.md) | The entity was incorporated in the last seven years, or press or the entity record shows venture funding in the last seven years (not a company bought out by private equity or a strategic buyer since its last round) | No |
| S&P Global | [sp-global.md](references/sources/sp-global.md) | Always | No |
| Financials | [financials.md](references/sources/financials.md) | Always | Yes |
| Debt and valuation marks | [debt-and-valuation-marks.md](references/sources/debt-and-valuation-marks.md) | Always: most useful for private and private-equity-owned companies | Yes |
| Courts and insolvency | [courts.md](references/sources/courts.md) | Always; its UK checks only when the entity has a UK company | No |

When the user asks to skip SEC, leave out SEC EDGAR and Debt and valuation marks, tell the Financials agent to make no sec.gov requests, and record both skipped sources under Gaps. Otherwise, first check whether the `MUCKRAKER_SEC_UA` environment variable is set (`python -c "import os; print(os.environ.get('MUCKRAKER_SEC_UA', ''))"`). When it is, the user has given the SEC contact for every run: its value is the SEC `User-Agent`, `mr.py` sends it to sec.gov whenever `--user-agent` is left out, and you skip the question below. When it is not, before sending the agents marked "Queries sec.gov", ask the user for the name and email address to declare in the `User-Agent` header (sent as `<name> <email>`), since SEC asks automated clients to identify themselves. Ask every run, and use only what the user types in answer, or a value they typed earlier in this conversation that they explicitly choose to reuse; never a name or email you know from elsewhere. Put this question in the same message as any entity question from step 1. If the user answers the entity question and leaves this one unanswered, ask it once more on its own; if they pass over it again, treat that as declining. If the user declines, send those agents without a value; the brief tells them what to do instead. Your own sec.gov requests follow the same rule as the agents' (see the SEC bullet in [references/brief.md](references/brief.md)).

Record in the dossier's Gaps every register the entity is in that no source searched: outside the US and UK, any country's register the National registers agent could not reach, and each country's courts unless its row in national-registers.md names a court search that the agent ran (the Courts agent searches US and UK courts only); for a US entity, any state register the US state registry agent could not reach.

Done when the source list is fixed and the SEC contact has been given or declined, or the user has asked to skip SEC.

## 3. Send the agents

Create a run folder for each company outside the user's project: `<base>/muckraker/<company-slug>-<YYYYMMDD-HHMM>/`, where `<base>` is the session's scratchpad or temp directory if the runtime names one, otherwise the system temp directory. Record its absolute path in your next message so it survives context compaction.

### Sources you run yourself

Some sources you run yourself with the script instead of sending an agent. Each has its own file in [references/coordinator/](references/coordinator/): when a source's condition below holds, read its file and follow it. Run commands with `python`, or `python3` where `python` is missing or older than 3.9.

Run these before sending the agents, since their records go into the agents' prompts or decide who writes a report:

| Source | File | Run when |
| --- | --- | --- |
| UK Companies House, then who writes Financials | [uk-companies-house.md](references/coordinator/uk-companies-house.md), [uk-financials.md](references/coordinator/uk-financials.md) | You can run Python and `COMPANIES_HOUSE_API_KEY` is set |
| National registers | [national-register-commands.md](references/coordinator/national-register-commands.md) | You can run Python and a group company is registered in a country that file's table lists |
| Form D | [form-d.md](references/coordinator/form-d.md) | You can run Python and the user gave the SEC contact |

Run these while the agents work:

| Source | File | Run when |
| --- | --- | --- |
| GLEIF ownership | [gleif-ownership.md](references/coordinator/gleif-ownership.md) | You can run Python |
| US federal money | [us-federal-money.md](references/coordinator/us-federal-money.md) | You can run Python and the entity record has a US entity |
| Debt and valuation marks | [debt-marks.md](references/coordinator/debt-marks.md) | You can run Python and the user gave the SEC contact |
| Layoffs and hiring | [layoffs-and-hiring.md](references/coordinator/layoffs-and-hiring.md) | You can run Python |

Without Python, send the agent for each source in these tables that has one (UK Companies House, National registers, GLEIF ownership, Debt and valuation marks), and list US federal money, WARN layoff notices, and the hiring trend under Gaps, since they have no agent.

### The facts file, written by you

Agents in earlier runs spent much of their budget finding the same basics: four to six of them searched the same funding rounds, leadership page, and about page. Before sending the agents (after the scripts that run first), write `<run folder>/facts.md` with what step 1 and those scripts established, so each agent starts from it instead of finding it again. Spend at most three more lookups on it: the company's leadership or about page, one search for its funding rounds, and its careers page. Keep it under about 60 lines, one fact per line, each with its source URL, and no analysis:

- **Entities:** each legal entity in the entity record with its jurisdiction, register number, LEI, and the parent and subsidiaries known so far; former names.
- **People in company roles:** the CEO, CFO, chair, and founders, with their titles as the company's own page gives them.
- **Funding:** each round found so far, with date, stage, amount, and lead investors.
- **Footprint:** website, careers page, headquarters and other offices, and the headcount the company claims.
- **Financial year end:** the date each entity's financial year ends, from its register entry (Virre in Finland, for example) or its latest accounts, so that deadline checks use the right year end and not 31 December.
- **Known events:** layoffs, executive departures and appointments, acquisitions, and the company's headline revenue or ARR claim from the last three years that step 1 or the scripts already turned up, each with its date and the article or filing that reports it. Leave this empty rather than search for it: it stops agents chasing the same story, and the Press agent still looks for events missing from it. Leave out claims found only on an aggregator with no primary source (a layoff tracker, a funding database): agents treat this file as known, and aggregators often attach another company's news to a similar name.
- **Not this company:** other companies with the same or a similar name that searches will turn up (a games company sharing the brand name, a fund or SPAC named after the same word), each with what tells it apart, so agents can drop their results at once.

Mark anything unconfirmed as such. Agents treat these facts as known: they cite them from the file's URLs when they use them, check and extend them only where their own source file asks for that (the Startup agent still owns funding, the Company profile agent leadership, and the Press agent events), and record any contradiction they find under Facts with both URLs. Only you write the file.

### The agents

Send one agent per other chosen source per company, all at once, in parallel. The exception is a `lu` run still going in the background: send the National registers and Financials agents once it has finished, and the rest now. When the group has companies in more than three countries outside the US and UK, split National registers into one agent per two or three countries, each with its own report file (`national-registers-<cc>-<cc>.md`), since a single agent covering them all is the slowest of the run. Each prompt contains:

- the absolute paths of [references/brief.md](references/brief.md), the agent's source file, and `<run folder>/facts.md`, with the instruction to read all three first;
- that company's entity record from step 1;
- the absolute path of its report file: `<run folder>/<source file name>`, for example `<run folder>/press.md`;
- the SEC `User-Agent` value, for the agents marked "Queries sec.gov" only;
- the absolute path of [scripts/mr.py](scripts/mr.py), the skill's fetcher for EDGAR filings, XBRL figures, lender and fund marks, and quote checks;
- for the Financials agent, the absolute path of `uk-accounts.jsonl` when you made one;
- for each agent the national-registers table names, the absolute paths of the `<cc>-<number>.jsonl` files you made (and Luxembourg's saved extract), with the instruction to take that country's register facts from them as national-registers.md's "Records from mr.py" says, and not to query that register's APIs, notices, or filings again;
- for the SEC EDGAR, US state registry, and Startup agents, the absolute path of `formd.jsonl` when you made it, with the instruction to take the Form D filings from it and not to search or open them again.

Each agent writes its full report to that file and replies with only its status line (the brief gives the format). Wait for the status lines; leave the report files unread until step 4. If an agent has not replied 15 minutes after the last of the others, stop it, record its source as `FAILED: no reply` under Gaps, and continue.

If the runtime has no subagents, work through the sources yourself one at a time, following the same two files for each and writing the same report files. If it has no web access at all, stop and tell the user: this skill cannot run without it.

Done when every agent has replied or been stopped, every report file exists or the agent's status line says why it does not, and you have written the report for each source you ran yourself (UK Companies House, Financials when [uk-financials.md](references/coordinator/uk-financials.md) gave it to you, GLEIF ownership, Debt and valuation marks) or sent its agent.

## 4. Write the dossier

Read every report file in the run folder before writing anything. After context compaction, read them again rather than working from a summary. When the S&P Global report says `RATINGS SEARCH: needs a browser`, open that search yourself in a browser tool (the URL is in [sp-global.md](references/sources/sp-global.md), check 1), record the rating actions as that check says (from their article pages; never open a PDF or other document link in a browser, which starts a download dialog for the user), and use them as part of the S&P findings; with no browser tool, keep it under Gaps. Then:

- **Cross-check.** Record each disagreement in the dossier with both citations, not just the version you prefer.
  - **Facts several sources cover:** officers and directors, registered and head office addresses, headcount (a company's filed staff count covers that legal entity only, not its subsidiaries, so compare it with a group headcount claim only when the accounts are consolidated), revenue, ownership, and dates.
  - **Funding against the registers:** compare the rounds the Startup or Press report claims with the share allotments, capital increases, and shareholder lists in the register reports. Funding the company itself claims that no share allotment or disclosed debt matches is a red flag, established by the register filing. An allotment that exists but is too small for the round is a conflict, not a red flag: a round of new money adds about `amount ÷ post-money valuation` to the share count, so compare that with the percentage increase in shares or nominal capital (a $150m round at $2.5bn post-money is about 6%; a 2% increase means most of the round was a sale of existing shares, or the register filing is not the whole round), and record both under Conflicts between sources.
  - **Layoffs and hiring:** compare layoffs (`warn_notice` records and the Press report) and the open-roles trend (`jobs_snapshot` records, or `jobs_posting_ages` where the board has no archive) with the company's headcount and growth claims: a layoff of 10% or more of its headcount in the last 12 months, or one that contradicts a growth claim made after it, is a red flag; open roles falling by more than half over 6 to 12 months, or a department's roles disappearing, go under Facts, and count as a red flag only beside a layoff or a funding gap.
  - **Charges against debt:** compare outstanding charges in the UK register (`ch_charge` records) with the debt note in the accounts and the Financials report: a charge the accounts do not explain, such as an outstanding charge beside a statement that the company has no debt, goes under Conflicts between sources with both citations.
- **Follow up names found late.** When the reports name group companies, people, or owners the entity record lacked, follow [late-names.md](references/coordinator/late-names.md) for each kind, and fold what it finds into the reports.
- **Merge duplicates.** When several agents report the same red flag (the same loan mark, the same rating action), keep it once and cite every filing behind it.
- **Confirm red flags.** Every red flag must be found on its cited page, saying what the agent reported, and be about this entity. Run `python <skill folder>/scripts/mr.py --user-agent "<SEC User-Agent>" verify-report "<run folder>"`, leaving out `--user-agent` when the user declined the SEC contact or asked to skip SEC: it reads every report's red flags, fetches each cited page once (filings of tens of megabytes included), and returns one `red_flag_check` per flag with its `result`:
  - `confirmed`: the quote is on the page; read the returned `context` to check it says what the agent reported and is about this entity. A `warnings` entry means the quote is too short to carry the flagged figures, or appears more than once so the context may show another row or period: check that flag with `quote-check` and a fuller quote;
  - `unreachable`: no cited page could be fetched, usually a site that refuses scripts such as spglobal.com; check the quote in a browser tool;
  - `unreachable` with a note that sec.gov needs the SEC contact: the user gave none, so check the quote with the web fetch tool, and pass `--user-agent` only with a contact the user typed for this run or set in `MUCKRAKER_SEC_UA`;
  - `too_large`: the cited file is bulk open data over the size limit (Luxembourg's quarterly files); check the quote against the run folder's extract with `mr.py quote-check <extract> "<quote>"`;
  - `js_page`: the cited page is built by JavaScript (a register app such as KvK's), so its data is not in the fetched HTML; check the quote in a browser tool;
  - `not_found`: the page loaded but the quote is not on it; open the page yourself, and if it does not say what the agent reported, move the flag to Gaps;
  - `no_text_layer`: the cited page is a PDF with no text to search, often a scan; read it yourself;
  - `no_quote` or `no_url`: the agent left the quote or URL out; find the evidence in the report or move the flag to Gaps.

  `mr.py quote-check <url> "<quote>"` checks a single quote the same way. Without Python, open each cited page yourself and search it for the quote; for a large filing, download it, strip the markup, and search the text for the quote's distinctive values, such as the borrower name and the fair value. Move a red flag you cannot confirm to Gaps with the reason.
- **Rank red flags.** Rank the confirmed red flags, most serious first, judged by the likely effect on the company's ability to keep operating and pay its debts: insolvency, default, a sanctions listing, a CCC-range rating, or loans valued far below par usually come before enforcement actions, litigation, overdue filings, auditor changes or qualified accounts, ownership hidden behind offshore or nominee layers, and adverse press. For each one, say whether it is an allegation, a filed claim, or an established finding (a fact on the record from the body that made it: a court judgment, a regulator's decision, a company filing, a rating agency's action, or a lender's or fund's filed valuation).
- **List gaps.** Name every source that failed or found nothing, and what it could not cover.

Use this structure:

```markdown
# <Legal name> — muckraker dossier (<date>)

## Entity
Legal name, jurisdiction, identifiers, website, parent, one-paragraph summary of what the company does.

## Red flags
Ranked, each with status (allegation / filed claim / established finding) and citations. "None found" is a valid entry.

## Financials
The multi-year table and derived figures from the Financials report, then debt (lenders, maturities, marks) and valuation marks. Cited.

## Key facts
People in company roles, ownership, filings, headcount, ratings, cases, recent events. Cited.

## Conflicts between sources
Each disagreement with both citations.

## Gaps
Sources that failed, returned nothing, or were paywalled, and what that leaves unknown.

## Sources
Every URL cited, grouped under a bold line per source, one `- [Title or site, date](url)` per URL.
```

Write every link as standard markdown, so it works in any viewer and when the dossier is shown in the chat:

- **Citations** in the body are inline links with short text, such as `([Companies House filing](https://find-and-update.company-information.service.gov.uk/company/09677925/filing-history))`. Do not use labels such as `[NR1]` or `[cro-co]` that point to the Sources section: without a matching definition line they are plain text, and definition lines do not display.
- **Sources** lists each URL as a visible inline link, as in the structure above. No bare URLs, no `[label]: url` definition lines, and no links to the report files in place of URLs (the run folder path, given after the dossier, covers those).
- **Characters:** percent-encode spaces, double quotes, braces, and parentheses in a URL (`%20`, `%22`, `%7B`, `%7D`, `%28`, `%29`), as in `https://www.thegazette.co.uk/insolvency/notice?text=%22Snyk%22`; unencoded, they break the link.

Write one dossier per company and save it as `<run folder>/dossier.md`. Show the dossier in the chat, and give the run folder's path so the user can read it and the full source reports.

Done when every claim in the dossier has a citation, from an agent's report or from a page you opened yourself in this step, every chosen source appears under its findings or under Gaps, every link is an inline markdown link as above, and the dossier is saved and shown.
