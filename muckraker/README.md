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
2. **Ask for SEC contact details.** SEC asks automated clients to identify themselves, so Muckraker asks for a name and email to send in the `User-Agent` header. It asks on every run. If you decline, the SEC sources use only web fetch and search tools. You can also ask it to skip SEC entirely, which drops the SEC EDGAR and debt-marks sources.
3. **Send one agent per source, in parallel.** Each agent reads one source, writes its full report to a run folder outside your project, and replies with a single status line, so the main session isn't flooded with output.
4. **Check and write.** The coordinator reads the reports, opens the source behind every red flag to confirm it, compares facts that more than one source covers, and writes the dossier.

## Sources

| Source | What it covers |
| --- | --- |
| Press | Recent coverage, with one search per adverse term (lawsuit, fraud, layoffs, administration, and so on) |
| Company profile | Leadership, newsroom, careers, and product footprint (domain age, site history, GitHub activity) from the company's own site, with LinkedIn as a fallback; for US companies, leaders' other board seats (LittleSis) and US import records (ImportYeti) |
| SEC EDGAR | Filings, Form D private raises, mentions in other companies' filings, and enforcement actions |
| UK Companies House | Officers, persons with significant control, charges, filing health, insolvency, and for young companies share allotments, implied valuations, shareholder lists, and founders' earlier companies (when the company, its parent, or a subsidiary is UK-registered) |
| US state registry | Status (including suspensions), formation, registered agent, officers or managers, foreign registrations, and UCC liens where free (when the company, its parent, or a subsidiary is registered in a US state). Finds every state the company is registered in through OpenCorporates first, and falls back to it when a state register sits behind a CAPTCHA |
| National registers | Profile, officers, filed accounts, and insolvency notices in France, Luxembourg, Germany, the Netherlands, Belgium, Switzerland, Ireland, Norway, Denmark, and Canada (when the company, its parent, or a subsidiary is registered there), with North Data and OpenCorporates as fallbacks |
| GLEIF ownership | The company's Legal Entity Identifier, its parent chain up to the ultimate parent, and its subsidiaries in every country |
| Sanctions and offshore | Sanctions and politically-exposed-person screening (OpenSanctions, OFAC) and the ICIJ Offshore Leaks database, for the company, its group, and its leaders |
| Startup | Funding rounds from free startup databases and funding news, grants (UKRI, CORDIS, SBIR), crowdfunding, and accelerators (when the company is under seven years old or venture-backed) |
| S&P Global | Rating actions and tear sheets from S&P Global Ratings' public search |
| Financials | A multi-year table from filed accounts or SEC data, plus notes on going concern, debt, and events after the year end |
| Debt and valuation marks | How listed lenders (business development companies) and funds value the company's loans and shares, quarter by quarter |
| Courts and insolvency | US federal dockets, US federal and state opinions, UK judgments, and UK Gazette insolvency notices |

The dossier has these sections: Entity, Red flags (each marked as an allegation, a filed claim, or an established finding), Financials, Key facts, Conflicts between sources, Gaps, and Sources. It appears in the chat and is saved as `dossier.md` in the run folder, beside the full source reports.

## Setup

Muckraker works without any setup, but some sources return much more with credentials.

### Credentials

Agents read API keys from environment variables. [`.env.example`](.env.example) lists them, each with where to get it. Copy it to `.env` in this folder and fill in the keys you have. Leave the others blank. `.env` is git-ignored, so keep real keys there and never in `.env.example`.

Nothing loads `.env` automatically, so get the keys into the environment Claude Code runs in. Either:

- add them to the `env` block of `~/.claude/settings.json`, which Claude Code passes to every command it runs:

  ```json
  { "env": { "COMPANIES_HOUSE_API_KEY": "<your key>" } }
  ```

- or load the file in your shell before starting Claude Code:

  ```bash
  set -a; source <(grep -E '^[A-Z_]+=.+' muckraker/.env); set +a
  ```

  ```powershell
  Get-Content muckraker/.env | Where-Object { $_ -match '^\s*[A-Z_]+=\S' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }
  ```

Agents keep key values out of their reports and write `[REDACTED]` for any credential they come across.

### Python (for the fetcher script)

`scripts/mr.py` fetches EDGAR filings and XBRL figures, finds how lenders and funds value a company's loans and shares, reads GLEIF ownership chains and UK Companies House records and accounts (scanned ones as page images, electronic forms as text), and checks red-flag quotes against their sources. It needs Python 3.9 or later and nothing else. Agents use it when it runs and fall back to fetching pages themselves when it doesn't, which is slower and costs far more tokens.

With Python, the coordinator also replaces up to three agents and most of its own checking with script calls. On Veracode:

- **UK Companies House** (needs `COMPANIES_HOUSE_API_KEY`): `ch` returned Veracode Ltd's register record in about a second, with 28 filings made after their statutory deadline worked out from the register's own dates, against about 92k tokens for an agent. `uk-accounts` read four sets of iXBRL accounts into a five-year table, with the accounts' notes on the parent chain and going concern, in under 3 seconds. When those UK accounts are the only filed accounts, as for Veracode, the coordinator writes the financials report from them too, instead of sending a roughly 110k-token agent.

- **Lender and fund marks:** `marks` took about 30 seconds and returned about 10k tokens of output, against 144k tokens for an agent using the script and about 167k for one working by hand.
- **GLEIF ownership:** `gleif` takes a few seconds, against about 100k tokens for an agent.
- **Red-flag checks:** `verify-report` checked all 16 red flags in a run's 13 reports in about 6 seconds, against about 30 tool calls when the coordinator opened each page itself. Pages that refuse scripts, such as S&P's, still need a browser.

Run its offline tests with:

```bash
python -m unittest muckraker/scripts/test_mr.py
```

### Companies House API key

Without a key, the Companies House agent reads the public website. With one, it uses the Companies House API. To get a free key, follow the [Companies House developer hub](https://developer.company-information.service.gov.uk/): sign in, create an application, and add a REST API key to it. Set it as `COMPANIES_HOUSE_API_KEY` (see [Credentials](#credentials)).

### CourtListener

The courts agent tries these in order:

1. **The CourtListener MCP server.** Free Law Project hosts it at `https://mcp.courtlistener.com/` ([source and docs](https://github.com/freelawproject/courtlistener-mcp)). Add it to Claude Code with:

   ```bash
   claude mcp add --transport http courtlistener https://mcp.courtlistener.com/
   ```

   The first call opens a browser to sign in with a free CourtListener account. Muckraker uses only its search and read tools, never the ones that create alerts, tags, or subscriptions.
2. **A CourtListener API token** in `COURTLISTENER_API_TOKEN`, from your [CourtListener profile](https://www.courtlistener.com/profile/api/).
3. **Web search** of courtlistener.com. This is the weakest option: CourtListener blocks most direct page fetches, so the agent often works from search snippets.

### OpenCorporates API token

Without a token, the US state registry and national registers agents read OpenCorporates' public pages, which hide officers, dates, and filings behind a login. With a token in `OPENCORPORATES_API_TOKEN`, they use its API for those details and search officers across companies. OpenCorporates data is open under a share-alike licence with attribution; heavier or commercial use needs a paid plan ([licence](https://opencorporates.com/legal/licence), [API accounts](https://opencorporates.com/api_accounts/new)).

### OpenSanctions API key

Without a key, the sanctions agent reads the OpenSanctions website search and the OFAC list. With a key in `OPENSANCTIONS_API_KEY`, it uses the OpenSanctions API. OpenSanctions data is free for non-commercial use; commercial use needs a licence from [OpenSanctions](https://www.opensanctions.org/licensing/).

### Browser tool

S&P Global Ratings' public search only loads in a real browser. If the agent can't open it, the coordinator opens it in its own browser tool. If neither has one, the S&P ratings go under Gaps.

## Limits

- LinkedIn and most of S&P Global sit behind logins or paywalls, so Muckraker reports only what is public and lists the rest under Gaps.
- National registers have direct entries for France, Luxembourg, Germany, the Netherlands, Belgium, Switzerland, Ireland, Norway, Denmark, and Canada. For other countries the agent finds the register through Wikipedia's [list of official business registers](https://en.wikipedia.org/wiki/List_of_official_business_registers) and works out what it shows on each run, which is slower and less reliable. Add a row to `references/sources/national-registers.md` for any country you research often.
- Lenders and funds that don't file with the SEC are invisible, so debt totals from valuation marks are a floor.
- A private company's group accounts are often unpublished. The financial table then covers only subsidiaries that file accounts, such as a UK subsidiary.
- UK accounts are read from their iXBRL version where one exists. Scanned accounts with no text layer are read as page images through `mr.py uk-pages`, which costs more tokens; other countries' scans are listed as `needs OCR` unless the agent has an OCR tool.
- Each run sends one agent per source per company (up to thirteen per company), so research on several companies uses a lot of tokens.

## Privacy

Agents record people only in their company roles: name, role, appointment dates, and ownership share, as filed. They leave out home addresses, family, and personal social media. Claims are attributed to their source, and allegations are kept separate from established findings.
