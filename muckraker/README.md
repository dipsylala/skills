# Muckraker

Muckraker researches a company and writes a cited dossier: who the company is, what it has filed, what its lenders and rating agencies think of it, what the courts and press say about it, and where those sources disagree.

Run it by name with a company name, or several:

```text
/muckraker Greggs
/muckraker Greggs and Pret A Manger
```

It is manual-only. The agent never starts it on its own.

## How it works

1. **Pin down the entity.** Muckraker finds the legal entity behind the name and checks each identifier in its registry: the SEC CIK, the UK company number, the US state entity number, and so on. If several companies match, it asks you which one you mean.
2. **Ask for SEC contact details.** SEC asks automated clients to identify themselves, so Muckraker asks for a name and email to send in the `User-Agent` header. It asks on every run. If you decline, the SEC sources use only web fetch and search tools.
3. **Send one agent per source, in parallel.** Each agent reads one source, writes its full report to a run folder outside your project, and replies with a single status line, so the main session isn't flooded with output.
4. **Check and write.** The coordinator reads the reports, opens the source behind every red flag to confirm it, compares facts that more than one source covers, and writes the dossier.

## Sources

| Source | What it covers |
| --- | --- |
| Press | Recent coverage, with one search per adverse term (lawsuit, fraud, layoffs, administration, and so on) |
| Company profile | Leadership, newsroom, and careers pages on the company's own site, with LinkedIn as a fallback |
| SEC EDGAR | Filings, Form D private raises, mentions in other companies' filings, and enforcement actions |
| UK Companies House | Officers, persons with significant control, charges, filing health, and insolvency (when the company, its parent, or a subsidiary is UK-registered) |
| US state registry | Status (including suspensions), formation, registered agent, officers or managers, foreign registrations, and UCC liens where free (when the company, its parent, or a subsidiary is registered in a US state). Falls back to OpenCorporates when a state register sits behind a CAPTCHA |
| National registers | Profile, officers, filed accounts, and insolvency notices in France, Luxembourg, Germany, the Netherlands, Ireland, Norway, Denmark, and Canada (when the company, its parent, or a subsidiary is registered there) |
| GLEIF ownership | The company's Legal Entity Identifier, its parent chain up to the ultimate parent, and its subsidiaries in every country |
| Sanctions and offshore | Sanctions and politically-exposed-person screening (OpenSanctions, OFAC) and the ICIJ Offshore Leaks database, for the company, its group, and its leaders |
| S&P Global | Rating actions and tear sheets from S&P Global Ratings' public search |
| Financials | A multi-year table from filed accounts or SEC data, plus notes on going concern, debt, and events after the year end |
| Debt and valuation marks | How listed lenders (business development companies) and funds value the company's loans and shares, quarter by quarter |
| Courts and insolvency | US federal dockets, US federal and state opinions, UK judgments, and UK Gazette insolvency notices |

The dossier has these sections: Entity, Red flags (each marked as an allegation, a filed claim, or an established finding), Financials, Key facts, Conflicts between sources, Gaps, and Sources. It appears in the chat and is saved as `dossier.md` in the run folder, beside the full source reports.

## Setup

Muckraker works without any setup, but some sources return much more with credentials.

### Companies House API key

Without a key, the Companies House agent reads the public website. With one, it uses the Companies House API. Register for a free key at the [Companies House developer hub](https://developer.company-information.service.gov.uk/), then set it in your environment:

```bash
export COMPANIES_HOUSE_API_KEY=<your key>
```

### CourtListener

The courts agent tries these in order:

1. **The CourtListener MCP server.** Free Law Project hosts it at `https://mcp.courtlistener.com/` ([source and docs](https://github.com/freelawproject/courtlistener-mcp)). Add it to Claude Code with:

   ```bash
   claude mcp add --transport http courtlistener https://mcp.courtlistener.com/
   ```

   The first call opens a browser to sign in with a free CourtListener account. Muckraker uses only its search and read tools, never the ones that create alerts, tags, or subscriptions.
2. **A CourtListener API token** in `COURTLISTENER_API_TOKEN`, from your [CourtListener profile](https://www.courtlistener.com/profile/api/).
3. **Web search** of courtlistener.com. This is the weakest option: CourtListener blocks most direct page fetches, so the agent often works from search snippets.

### OpenSanctions API key

Without a key, the sanctions agent reads the OpenSanctions website search and the OFAC list. With a key in `OPENSANCTIONS_API_KEY`, it uses the OpenSanctions API. OpenSanctions data is free for non-commercial use; commercial use needs a licence from [OpenSanctions](https://www.opensanctions.org/licensing/).

### Browser tool

S&P Global Ratings' public search only loads in a real browser. If the agent can't open it, the coordinator opens it in its own browser tool. If neither has one, the S&P ratings go under Gaps.

## Limits

- LinkedIn and most of S&P Global sit behind logins or paywalls, so Muckraker reports only what is public and lists the rest under Gaps.
- Lenders and funds that don't file with the SEC are invisible, so debt totals from valuation marks are a floor.
- A private company's group accounts are often unpublished. The financial table then covers only subsidiaries that file accounts, such as a UK subsidiary.
- UK accounts are read from their iXBRL version where one exists. Older scanned accounts with no text layer are listed as `needs OCR` unless the agent has an OCR tool.
- Each run sends one agent per source per company (up to twelve per company), so research on several companies uses a lot of tokens.

## Privacy

Agents record people only in their company roles: name, role, appointment dates, and ownership share, as filed. They leave out home addresses, family, and personal social media. Claims are attributed to their source, and allegations are kept separate from established findings.
