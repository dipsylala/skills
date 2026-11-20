---
name: muckraker
description: Research a company across the press, its own website and LinkedIn, SEC EDGAR, UK Companies House, S&P Global, its filed financials, lender and fund marks, and the courts in parallel, and report a cited dossier with red flags, conflicts between sources, and gaps.
disable-model-invocation: true
---

# Muckraker

Given a company name, find out who the company is, what it has filed, what has been reported about it, and where the sources disagree. You are the coordinator: you pin down the entity, send one research agent per source, and write the dossier from their reports. Every fact in the dossier carries a citation.

## 1. Pin down the entity

Take the company name and anything else the user gave (country, website, ticker, company number). When the user names several companies, build one entity record per company and run every later step for each. Search the web to find the candidates.

- One clear match: record its legal name, jurisdiction, website, ticker, SEC CIK, UK company number, and parent company, as far as you can find them. Confirm each registry identifier by looking it up in that registry and checking that the name it returns is the entity you mean (a CIK can belong to the UK parent rather than the US company); record the registered name beside the identifier. Leave a field empty rather than guess it.
- Several plausible matches (different countries, a parent and its subsidiaries, a similar name): list them with what tells them apart and ask the user which one to research. Researching the wrong "Acme Ltd" wastes every agent you send.

Done when the user has confirmed one entity, or the search found exactly one and you have recorded its identifiers.

## 2. Choose the sources

Each source has its own reference file in [references/sources/](references/sources/):

| Source | File | Run when | Queries sec.gov |
| --- | --- | --- | --- |
| Press | [press.md](references/sources/press.md) | Always | No |
| Company profile | [company-profile.md](references/sources/company-profile.md) | Always | No |
| SEC EDGAR | [sec-edgar.md](references/sources/sec-edgar.md) | Always: a private or foreign company can still file (Form D, 20-F), and finding nothing is a result | Yes |
| UK Companies House | [companies-house.md](references/sources/companies-house.md) | The entity, its parent, or a subsidiary is UK-registered, or the jurisdiction is unknown | No |
| S&P Global | [sp-global.md](references/sources/sp-global.md) | Always | No |
| Financials | [financials.md](references/sources/financials.md) | Always | Yes |
| Debt and valuation marks | [debt-and-valuation-marks.md](references/sources/debt-and-valuation-marks.md) | Always: most useful for private and private-equity-owned companies | Yes |
| Courts and insolvency | [courts.md](references/sources/courts.md) | Always; its UK checks only when the entity has a UK company | No |

Before sending the agents marked "Queries sec.gov", ask the user for the name and email address to declare in the `User-Agent` header (sent as `<name> <email>`), since SEC asks automated clients to identify themselves. Ask every run, and use only what the user types in answer, or a value they typed earlier in this conversation that they explicitly choose to reuse; never a name or email you know from elsewhere. Put this question in the same message as any entity question from step 1. If the user declines, tell those agents to use only the web fetch and search tools, which send their own header.

## 3. Send the agents

Create a run folder for each company outside the user's project: in the session's scratchpad or temp directory if the runtime names one, otherwise `<system temp>/muckraker/<company-slug>-<YYYYMMDD-HHMM>/`. Record its absolute path in your next message so it survives context compaction.

Send one agent per chosen source per company, all at once, in parallel. Each prompt contains:

- the absolute paths of [references/brief.md](references/brief.md) and the agent's source file, with the instruction to read both first;
- that company's entity record from step 1;
- the absolute path of its report file: `<run folder>/<source file name>`, for example `<run folder>/press.md`;
- the SEC `User-Agent` value, for the agents marked "Queries sec.gov" only.

Each agent writes its full report to that file and replies with only its status line (the brief gives the format). Wait for the status lines; leave the report files unread until step 4.

If the runtime has no subagents, work through the sources yourself one at a time, following the same two files for each and writing the same report files. If it has no web access at all, stop and tell the user: this skill cannot run without it.

Done when every agent has replied, and every report file exists or the agent's status line says why it does not.

## 4. Write the dossier

Read every report file in the run folder before writing anything. After context compaction, read them again rather than working from a summary. When the S&P Global report says `RATINGS SEARCH: needs a browser`, open that search yourself in a browser tool (the URL is in [sp-global.md](references/sources/sp-global.md), check 1), record the rating actions as that check says, and use them as part of the S&P findings; with no browser tool, keep it under Gaps. Then:

- **Cross-check.** Compare the facts that more than one source covers: officers and directors, registered and head office addresses, headcount, revenue, ownership, dates. Record each disagreement in the dossier with both citations, not just the version you prefer.
- **Rank red flags.** Use the red flags the agents found, most serious first: regulatory or enforcement actions, litigation, insolvency or overdue filings, charges and debt, auditor changes or qualified accounts, ownership hidden behind offshore or nominee layers, adverse press. For each one, say whether it is an allegation, a filed claim, or an established finding (a court judgment, a regulator's decision, a filing by the company itself). For every red flag, open the cited URL yourself and search the page for the agent's quote; confirm it says what the agent reported, and that it is about this entity. Move one you cannot confirm to Gaps with the reason.
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

Write one dossier per company. Show the dossier in the chat, and give the run folder's path so the user can read the full source reports. Save the dossier to a file only when the user asks.

Done when every claim in the dossier has a citation from an agent's report, and every chosen source appears under its findings or under Gaps.
