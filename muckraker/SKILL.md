---
name: muckraker
description: Research a company in parallel across press, registries, financials, lender marks, ratings, and courts, and report a cited dossier of red flags.
disable-model-invocation: true
---

# Muckraker

Given a company name, find out who the company is, what it has filed, what has been reported about it, and where the sources disagree. You are the coordinator: you pin down the entity, send one research agent per source, and write the dossier from their reports. Every fact in the dossier carries a citation.

## 1. Pin down the entity

Take the company name and anything else the user gave (country, website, ticker, company number). When the user names several companies, build one entity record per company and run every later step for each. Search the web to find the candidates.

- One clear match: record its legal name, jurisdiction, website, ticker, SEC CIK, UK company number, US state of formation and state entity number, and parent company, as far as you can find them. Confirm each registry identifier by looking it up in that registry and checking that the name it returns is the entity you mean (a CIK can belong to the UK parent rather than the US company); record the registered name beside the identifier. When a state register sits behind a CAPTCHA, confirm the entity number through OpenCorporates' copy of it (see [us-state-registry.md](references/sources/us-state-registry.md)) and say so in the record; without an OpenCorporates token that copy is often refused too, so record the number as unconfirmed and leave it to the US state registry agent to confirm. Look the entity up in GLEIF (`python <skill folder>/scripts/mr.py gleif "<legal name>"` to find the LEI, then `mr.py gleif <LEI>` for the parent chain and subsidiaries; without Python, the API in [gleif.md](references/sources/gleif.md)) and record its LEI and the countries its parents and subsidiaries are registered in; they decide which registers step 2 sends agents to. Leave a field empty rather than guess it. Until the user has given the SEC contact (step 2), reach sec.gov only through the web fetch and search tools: confirm a CIK by fetching `https://data.sec.gov/submissions/CIK<10-digit zero-padded CIK>.json` with the web fetch tool and checking its `name` field, which is the intended route here, not a workaround (the `browse-edgar` company page comes back blank through web fetch).
- Several plausible matches (different countries, a parent and its subsidiaries, a similar name): list them with what tells them apart and ask the user which one to research. Researching the wrong "Acme Ltd" wastes every agent you send.
- No match: tell the user what you searched and ask for more detail (country, website, company number) before going further.

Done when the user has confirmed one entity, or the search found exactly one and you have recorded its identifiers.

## 2. Choose the sources

Each source has its own reference file in [references/sources/](references/sources/):

| Source | File | Run when | Queries sec.gov |
| --- | --- | --- | --- |
| Press | [press.md](references/sources/press.md) | Always | No |
| Company profile | [company-profile.md](references/sources/company-profile.md) | Always | No |
| SEC EDGAR | [sec-edgar.md](references/sources/sec-edgar.md) | Always: a private or foreign company can still file (Form D, 20-F), and finding nothing is a result | Yes |
| UK Companies House | [companies-house.md](references/sources/companies-house.md) | The entity, its parent, or a subsidiary is UK-registered, or the jurisdiction is unknown | No |
| US state registry | [us-state-registry.md](references/sources/us-state-registry.md) | The entity, its parent, or a subsidiary is registered in a US state, or the jurisdiction is unknown | No |
| National registers | [national-registers.md](references/sources/national-registers.md) | The entity, its parent, or a subsidiary is registered outside the US and UK | No |
| GLEIF ownership | [gleif.md](references/sources/gleif.md) | Always: a company with no LEI is a result | No |
| Sanctions and offshore | [sanctions-offshore.md](references/sources/sanctions-offshore.md) | Always | No |
| Startup | [startup.md](references/sources/startup.md) | The entity was incorporated in the last seven years, or press or the entity record shows venture funding | No |
| S&P Global | [sp-global.md](references/sources/sp-global.md) | Always | No |
| Financials | [financials.md](references/sources/financials.md) | Always | Yes |
| Debt and valuation marks | [debt-and-valuation-marks.md](references/sources/debt-and-valuation-marks.md) | Always: most useful for private and private-equity-owned companies | Yes |
| Courts and insolvency | [courts.md](references/sources/courts.md) | Always; its UK checks only when the entity has a UK company | No |

When the user asks to skip SEC, leave out SEC EDGAR and Debt and valuation marks, tell the Financials agent to make no sec.gov requests, and record both skipped sources under Gaps. Otherwise, before sending the agents marked "Queries sec.gov", ask the user for the name and email address to declare in the `User-Agent` header (sent as `<name> <email>`), since SEC asks automated clients to identify themselves. Ask every run, and use only what the user types in answer, or a value they typed earlier in this conversation that they explicitly choose to reuse; never a name or email you know from elsewhere. Put this question in the same message as any entity question from step 1. If the user answers the entity question and leaves this one unanswered, ask it once more on its own; if they pass over it again, treat that as declining. If the user declines, send those agents without a value; the brief tells them what to do instead. Your own sec.gov requests follow the same rule as the agents' (see the SEC bullet in [references/brief.md](references/brief.md)).

Record in the dossier's Gaps every register the entity is in that no source searched: outside the US and UK, any country's register the National registers agent could not reach, and every national court system (no source searches courts outside the US and UK); for a US entity, any state register the US state registry agent could not reach.

Done when the source list is fixed and the SEC contact has been given or declined, or the user has asked to skip SEC.

## 3. Send the agents

Create a run folder for each company outside the user's project: in the session's scratchpad or temp directory if the runtime names one, otherwise `<system temp>/muckraker/<company-slug>-<YYYYMMDD-HHMM>/`. Record its absolute path in your next message so it survives context compaction.

Some sources you run yourself with the script instead of sending an agent, as the sections below say: UK Companies House when you can run Python and `COMPANIES_HOUSE_API_KEY` is set (run it before sending the agents, since it decides who writes Financials), Financials too when the UK accounts are the only filed accounts, GLEIF ownership whenever you can run Python, and Debt and valuation marks when you can also give sec.gov the SEC `User-Agent` (run those two while the agents work). Send one agent per other chosen source per company, all at once, in parallel. Each prompt contains:

- the absolute paths of [references/brief.md](references/brief.md) and the agent's source file, with the instruction to read both first;
- that company's entity record from step 1;
- the absolute path of its report file: `<run folder>/<source file name>`, for example `<run folder>/press.md`;
- the SEC `User-Agent` value, for the agents marked "Queries sec.gov" only;
- the absolute path of [scripts/mr.py](scripts/mr.py), the skill's fetcher for EDGAR filings, XBRL figures, lender and fund marks, and quote checks;
- for the Financials agent, the absolute path of `uk-accounts.jsonl` when you made one.

Each agent writes its full report to that file and replies with only its status line (the brief gives the format). Wait for the status lines; leave the report files unread until step 4. If an agent has not replied long after the others, stop it, record its source as `FAILED: no reply` under Gaps, and continue.

### UK Companies House, run by you

For each UK company in the entity record (the entity, a UK parent or a UK subsidiary), before sending the agents:

1. Run `python <skill folder>/scripts/mr.py ch <company number> > "<run folder>/companies-house-<number>.jsonl"`. It returns the profile, officers, persons with significant control and their statements, charges, insolvency cases, the latest filings, and `ch_flag` records: overdue accounts or confirmation statements, Gazette notices, and filings made after their statutory deadline, each with the rule it breaks.
2. Run `python <skill folder>/scripts/mr.py uk-accounts <company number> > "<run folder>/uk-accounts.jsonl"` (append with `>>` for a second company). It returns each year's figures from the iXBRL accounts (signed as the accounts print them, with `sign_mismatch` where the filer's XBRL tag disagrees), the auditor and going-concern basis, year-on-year changes, `uk_accounts_notes` with the latest accounts' sentences on the parent chain, going concern, events after the year end, and borrowing, and `uk_accounts_needs_ocr` for accounts filed only as a PDF. `python <skill folder>/scripts/mr.py uk-pages <its url> "<run folder>/pages-<made up date>" [--pages 1-5,33]` saves a scanned PDF's pages as PNG or JPEG images, one per page, to open with the Read tool.
3. Add the parent and controlling-party names in `uk_accounts_notes` to the entity record if they are new, before sending the agents.
4. Write `<run folder>/companies-house.md` from the `ch` records, in the brief's report format, working through the checks in [companies-house.md](references/sources/companies-house.md). Overdue items, Gazette notices, and late accounts (`severity: major`) are red flags, established by the register's own dates. Late officer, PSC, and confirmation-statement filings (`severity: minor`) are register housekeeping: list them under Facts, and make them one red flag only as a pattern (`ch_summary` counts those in the last 24 months; several is a pattern). A late-accounts flag's deadline assumes no extension or first-accounts period, so say so, and pass on its `possible_extension` when it has one. Each red flag cites the record's URL and quotes its `quote` field (the filing as the website prints it, such as "31 Oct 2024 AA"). Take check 8's parent chain from `uk_accounts_notes`.

If `COMPANIES_HOUSE_API_KEY` is not set or the script fails, send the UK Companies House agent instead, and the Financials agent reads the accounts itself.

### Financials, run by you when only UK accounts are filed

When the entity has no tagged SEC financials (no CIK, or `mr.py edgar-facts <CIK>` returns `no_xbrl_financials`) and the entity record names no company outside the UK and US that files accounts, `uk-accounts` has covered every filed set of accounts. Then write `<run folder>/financials.md` yourself from the `uk-accounts` records instead of sending the Financials agent, working through the checks in [financials.md](references/sources/financials.md): the multi-year table, the derived figures, the notes from `uk_accounts_notes`, and any `sign_mismatch` or `uk_accounts_needs_ocr` records. Say under Gaps that group accounts are not published, and leave group figures from ratings or press to step 4. In every other case, send the Financials agent with the path of `uk-accounts.jsonl`.

### GLEIF ownership, run by you

You already ran `mr.py gleif <LEI>` in step 1. Run it also for each parent and acquisition-company name in the entity record that has an LEI of its own (`mr.py gleif "<name>"` finds it), since a group's holding companies often have one when the operating company does not. Write `<run folder>/gleif.md` from the records, in the brief's report format, working through the checks in [gleif.md](references/sources/gleif.md): the entity record, the parent chain or the `exception_reason` where it stops, the subsidiaries and their countries, and any `gleif_flag` record (an offshore parent) as a red flag quoting the parent's name and country. A company with no LEI is a result: say so and list the searches you ran. If the script fails, send the GLEIF ownership agent instead.

### Debt and valuation marks, run by you

The script does this source's searching and reading, so an agent would mostly add cost. After sending the agents:

1. Collect the borrower names: the legal and trading names, former names, and the parent and holding company names in the entity record, plus the most distinctive single word of each (holders spell the same borrower differently).
2. Run `python <skill folder>/scripts/mr.py --user-agent "<SEC User-Agent>" marks "<name>" "<word>" ... > "<run folder>/debt-and-valuation-marks.jsonl"`.
3. Look through the records' `identifier` fields (lender rows) and `name` and `title` fields (fund holdings) for borrower names you did not search, such as a fund holding titled "<company> (<acquisition company>)". Run `marks` again only for names whose distinctive word you have not already searched (a round-1 search for "Falcon" already matched every "Falcon …" vehicle), appending (`>>`) to the same file with `--skip-seen "<run folder>/debt-and-valuation-marks.jsonl"`: the script also skips a name an earlier search covered (reported as `already_searched`) and leaves out records already there (`already_seen`). One extra round is enough. Drop any name `marks` reports as `generic_alias`: it is a common word, and its results are mostly unrelated.
4. Write `<run folder>/debt-and-valuation-marks.md` from the records, in the brief's report format, working through the checks in [debt-and-valuation-marks.md](references/sources/debt-and-valuation-marks.md). Each red flag cites its filing URL and quotes the record's `quote` (a loan row as the page shows it) or, for a fund holding, its name, balance, and value in the brief's XML form. A loan's `flagged_footnotes` (non-accrual, PIK, an amendment, a default) come from the filing's own footnotes, so they need no further opening.

If the script fails (an `error` record or no output at all), send the Debt and valuation marks agent after all, telling it what you ran. A `no_holdings_found` record is a result, not a failure: no SEC-filing lender or fund holds these names, so say so in the report.

If the runtime has no subagents, work through the sources yourself one at a time, following the same two files for each and writing the same report files. If it has no web access at all, stop and tell the user: this skill cannot run without it.

Done when every agent has replied, every report file exists or the agent's status line says why it does not, and you have written the reports for the sources you ran yourself (UK Companies House, GLEIF ownership, Debt and valuation marks) or sent their agents.

## 4. Write the dossier

Read every report file in the run folder before writing anything. After context compaction, read them again rather than working from a summary. When the S&P Global report says `RATINGS SEARCH: needs a browser`, open that search yourself in a browser tool (the URL is in [sp-global.md](references/sources/sp-global.md), check 1), record the rating actions as that check says, and use them as part of the S&P findings; with no browser tool, keep it under Gaps. Then:

- **Cross-check.** Compare the facts that more than one source covers: officers and directors, registered and head office addresses, headcount, revenue, ownership, dates, and funding rounds the Startup or Press report claims against the share allotments and shareholder lists in the register reports. Record each disagreement in the dossier with both citations, not just the version you prefer. Funding the company itself claims that no share allotment or disclosed debt matches is a red flag, established by the register filing.
- **Follow up group names found late.** Reports often name group companies the entity record lacked: an ultimate parent or controlling party in a subsidiary's accounts, the entity a rating agency rates, a borrower or holding vehicle in lenders' filings. For each such name, run `mr.py gleif "<name>"` and, if it could borrow, `mr.py marks --skip-seen "<run folder>/debt-and-valuation-marks.jsonl" "<name>" "<distinctive word>" >> "<run folder>/debt-and-valuation-marks.jsonl"`, adding what they find to the GLEIF and Debt and valuation marks reports. Then, if any new name is not already screened (a spelling variant of a screened name counts as screened, and so does any name containing a distinctive word the Sanctions and offshore agent already searched in every list it used, such as "Mitnick" for every Mitnick vehicle; its report lists its searches per list), send one agent with the Sanctions and offshore source file, those names only, and its own report file (`<run folder>/late-names.md`), and fold its findings in. Holding vehicles rarely have court cases of their own, so leave courts to the main run. If you send none, list the unscreened names under Gaps.
- **Registers for group companies found late.** When reports name group companies registered outside the US and UK (subsidiaries in GLEIF, a register, or the accounts) and the National registers agent was not sent, send it now for those companies, with its own report file, and fold its findings in; if you send none, list those companies under Gaps.
- **Merge duplicates.** When several agents report the same red flag (the same loan mark, the same rating action), keep it once and cite every filing behind it.
- **Confirm red flags.** Every red flag must be found on its cited page, saying what the agent reported, and be about this entity. Run `python <skill folder>/scripts/mr.py --user-agent "<SEC User-Agent>" verify-report "<run folder>"`: it reads every report's red flags, fetches each cited page once (filings of tens of megabytes included), and returns one `red_flag_check` per flag with its `result`:
  - `confirmed`: the quote is on the page; read the returned `context` to check it says what the agent reported and is about this entity. A `warnings` entry means the quote is too short to carry the flagged figures, or appears more than once so the context may show another row or period: check that flag with `quote-check` and a fuller quote;
  - `unreachable`: no cited page could be fetched, usually a site that refuses scripts such as spglobal.com; check the quote in a browser tool;
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
Ranked, each with status (allegation / filed claim / established) and citations. "None found" is a valid entry.

## Financials
The multi-year table and derived figures from the Financials report, then debt (lenders, maturities, marks) and valuation marks. Cited.

## Key facts
People in company roles, ownership, filings, headcount, ratings, cases, recent events. Cited.

## Conflicts between sources
Each disagreement with both citations.

## Gaps
Sources that failed, returned nothing, or were paywalled, and what that leaves unknown.

## Sources
Every URL cited, grouped by source.
```

Write one dossier per company and save it as `<run folder>/dossier.md`. Show the dossier in the chat, and give the run folder's path so the user can read it and the full source reports.

Done when every claim in the dossier has a citation, from an agent's report or from a page you opened yourself in this step, every chosen source appears under its findings or under Gaps, and the dossier is saved and shown.
