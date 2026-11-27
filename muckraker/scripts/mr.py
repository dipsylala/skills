#!/usr/bin/env python3
"""Deterministic fetchers for muckraker source agents.

Each command fetches one kind of public record and prints JSON lines, one
record per fact, each with the source URL and, where there is one, the exact
text from the document (`quote`) so the coordinator can confirm it.

sec.gov asks automated clients to identify themselves. Pass the name and email
the user gave with --user-agent "Name email" or the MUCKRAKER_SEC_UA
environment variable, such as "Jane Smith jane@example.com"; commands that
reach sec.gov refuse to run without one, or with a value not in that form.

Standard library only; Python 3.9 or later.
"""

import argparse
import datetime as dt
import json
import os
import sys

# Run as a script, so make its own folder importable even under `python -I`, which leaves it off sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mrlib  # noqa: E402
from mrlib import common, documents, gleif, registers, screening, sec, uk, us, verify, web  # noqa: E402
from mrlib.registers import br, dk, es, fi, fr, ie, il, lu, no, vat  # noqa: E402

MRLIB_VERSION = "1"  # bump with mrlib.VERSION whenever the two change together


def check_mrlib():
    """An error record when mrlib beside this script is from another release, else None."""
    if mrlib.VERSION != MRLIB_VERSION:
        return {"type": "error", "error": f"mr.py expects mrlib version {MRLIB_VERSION} but found {mrlib.VERSION} "
                                          f"in {os.path.dirname(mrlib.__file__)}: the install is a mix of two "
                                          "releases; copy the whole scripts folder again"}
    return None


# ----------------------------------------------------------------- main ----

def main(argv=None):
    mismatch = check_mrlib()
    if mismatch:
        common.emit(mismatch)
        return 1
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user-agent", default=os.environ.get("MUCKRAKER_SEC_UA"),
                   help='"Name email" for sec.gov, such as "Jane Smith jane@example.com" (or set MUCKRAKER_SEC_UA)')
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("edgar-filings", help="filer identity and recent filings")
    s.add_argument("cik")
    s.add_argument("--limit", type=int, default=40)

    s = sub.add_parser("edgar-facts", help="annual financial figures from XBRL (US filers)")
    s.add_argument("cik")
    s.add_argument("--years", type=int, default=5)

    s = sub.add_parser(
        "edgar-search", help="EDGAR full-text search for an exact phrase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="EDGAR full-text search for an exact phrase. The first record is a search_summary "
                    "with EDGAR's total and whether --max-hits cut the list short.",
        epilog='example:\n  mr.py --user-agent "Name email" edgar-search "Acme Corp" '
               '--forms "8-K,10-K,DEF 14A" --since 2024-01-01\n'
               "Quote --forms when a form name has a space (DEF 14A, SC 13D).")
    s.add_argument("phrase")
    s.add_argument("--forms", default="", help='comma-separated, quoted if any has a space, e.g. "10-K,DEF 14A"')
    s.add_argument("--since", help="YYYY-MM-DD")
    s.add_argument("--until", help="YYYY-MM-DD")
    s.add_argument("--max-hits", type=int, default=100)

    s = sub.add_parser("marks", help="lender and fund valuations of a borrower's loans and shares")
    s.add_argument("aliases", nargs="+", help="borrower names: company, parents, acquisition vehicles")
    s.add_argument("--since", default=(dt.date.today() - dt.timedelta(days=455)).isoformat(),
                   help="earliest filing date (default: about 15 months ago)")
    s.add_argument("--per-filer", type=int, default=2, help="filings per holder: latest plus earlier ones")
    s.add_argument("--max-filers", type=int, default=20)
    s.add_argument("--skip-seen", metavar="FILE",
                   help="an earlier marks output you append to: skip aliases its searches already covered "
                        "and records it already has")
    s.add_argument("--verbose", action="store_true",
                   help="also print search summaries and filings with no matching rows")

    s = sub.add_parser("gleif", help="LEI search by name, or an LEI's record, parent chain and subsidiaries")
    s.add_argument("name_or_lei", nargs="?", help="a legal name to search, or a 20-character LEI")
    s.add_argument("--registered-as", help="search by the entity's national register number instead (KVK, SIREN, ...)")
    s.add_argument("--limit", type=int, default=10, help="search candidates to return")
    s.add_argument("--max-children", type=int, default=200)

    s = sub.add_parser("ch", help="UK Companies House: profile, officers, PSCs, charges, filings, late-filing flags")
    s.add_argument("company_number")
    s.add_argument("--max-filings", type=int, default=200, help="filings to read and check for late-filing flags")
    s.add_argument("--list-filings", type=int, default=25, help="latest filings to list in the output")

    s = sub.add_parser("ch-search", help="UK Companies House: companies matching a name, including overseas registrations")
    s.add_argument("name")
    s.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("ch-officers", help="UK Companies House: directors' other companies that went insolvent, and disqualifications")
    s.add_argument("company_number")
    s.add_argument("--max-appointments", type=int, default=100, help="appointments to read per director")

    s = sub.add_parser("warn", help="US WARN layoff notices naming the company (states with open data)")
    s.add_argument("name")

    s = sub.add_parser("us-states", help="US entities in the state registers published as open data (CO, NY, TX, OR, CT)")
    s.add_argument("names", nargs="+", help="name prefixes to search, such as \"Aikido Security\"")

    s = sub.add_parser("usaspending", help="US federal contracts, grants and loans to recipients named like the company")
    s.add_argument("names", nargs="+", help="legal names and former names")
    s.add_argument("--since", help="earliest date as YYYY-MM-DD (default five years ago; 2007-10-01 at the earliest)")
    s = sub.add_parser("csl", help="the US Consolidated Screening List (OFAC, BIS, State Department lists) for these names")
    s.add_argument("names", nargs="+", help="company, group company, and officer names")
    s = sub.add_parser("formd", help="Form D filings naming a company or person, parsed: state and year of "
                                     "incorporation, related persons, amounts raised (sec.gov)")
    s.add_argument("names", nargs="+", help="company names, former names, and founders' or the CEO's names")
    s.add_argument("--max-hits", type=int, default=40, help="filings read per name")
    s = sub.add_parser("icij", help="ICIJ Offshore Leaks nodes matching these names")
    s.add_argument("names", nargs="+", help="company, group company, and officer names")
    s = sub.add_parser("footprint", help="domain registration (RDAP), site history (Wayback Machine), GitHub activity, "
                                         "and LinkedIn's archived company page")
    s.add_argument("domain", help="the company's domain, such as acme.com")
    s.add_argument("--github", help="the GitHub organisation, such as acme-inc, as the company's site links it")
    s.add_argument("--linkedin", help="the LinkedIn company page as the company's site links it, such as "
                                      "https://www.linkedin.com/company/acme/ (takes about two seconds a capture)")
    s.add_argument("--founded", type=int, help="the founding year the company claims, for the history check")
    s = sub.add_parser("jobs", help="open roles from the company's job board, optionally with a monthly trend")
    s.add_argument("target", help="the careers page URL, a job-board URL, or provider:token (greenhouse:acme)")
    s.add_argument("--history", action="store_true", help="also count roles in monthly archived copies (slow)")
    s.add_argument("--offices", nargs="*", default=[], help="the company's office cities or countries, to pick "
                                                            "between boards guessed from the domain name")

    s = sub.add_parser("uk-accounts", help="UK Companies House: multi-year figures from iXBRL accounts")
    s.add_argument("company_number")
    s.add_argument("--sets", type=int, default=3, help="accounts filings to read (each covers two years)")

    s = sub.add_parser("fr", help="France: register profile, officers, and BODACC notices with missing-accounts flags")
    s.add_argument("siren_or_name", help="a 9-digit SIREN, or a name to list candidates")

    s = sub.add_parser("lu", help="Luxembourg: filed accounts from the Centrale des Bilans open data, with late-filing flags")
    s.add_argument("rcs", nargs="+", help="the RCS number, such as B165616, or several (each quarterly file is read once "
                                         "for all of them)")
    s.add_argument("--quarters", type=int, default=12, help="newest quarterly deposit files to search (each 70-820 MB)")
    s.add_argument("--save", metavar="FILE", help="write the company's matching records to this file, for quote-check")

    s = sub.add_parser("ie", help="Ireland: CRO open data profile and annual-return filings with late-filing flags")
    s.add_argument("cro_or_name", help="a CRO company number, or a name to list candidates")

    s = sub.add_parser("il", help="Israel: Corporations Authority profile from a daily register copy, with violating-"
                                  "company, status and late-annual-report flags")
    s.add_argument("company_number", help="a 9-digit company number (find it in the Authority's search in a browser)")

    s = sub.add_parser("es", help="Spain: a company's acts in BORME section A (officers, capital, address, "
                                  "dissolution), with an inscription-sequence check")
    s.add_argument("name", help="the registered name, such as \"Everyday Software SL\" (the legal form is ignored)")
    s.add_argument("--pdf", nargs="*", default=[], help="BORME-A PDF URLs to read")
    s.add_argument("--empresia", help="the company's empresia.es page, whose BORME links give the PDFs to read")
    s.add_argument("--scan-from", help="also scan each day's BORME from this date (YYYY-MM-DD; about 2 requests a day)")
    s.add_argument("--scan-to", help="end of the scan (default today)")
    s.add_argument("--province", default="08", help="INE province code of the registry for --scan-from (08 Barcelona, "
                                                    "28 Madrid, 46 Valencia, 41 Sevilla)")

    s = sub.add_parser("vat", help="EU VAT number in VIES: valid now, and the registered name and address where "
                                   "the country discloses them")
    s.add_argument("country", help="two-letter EU country code (EL or GR for Greece)")
    s.add_argument("number", help="the VAT number, with or without the country prefix (IT 10927360015)")

    s = sub.add_parser("br", help="Brazil: Receita Federal CNPJ open data: status, special situation, capital, "
                                  "partners and administrators")
    s.add_argument("cnpj", help="a 14-digit CNPJ")

    s = sub.add_parser("no", help="Norway: Brønnøysund profile, officers, accounts and announcements, with late-filing "
                                  "and bankruptcy flags")
    s.add_argument("orgnr_or_name", help="a 9-digit organisasjonsnummer, or a name to list candidates")

    s = sub.add_parser("fi", help="Finland: PRH profile, registered-notices timeline and accounts periods, with "
                                  "insolvency and late-accounts flags")
    s.add_argument("business_id_or_name", help="a business ID such as 2795743-5, or a name to list candidates")
    s.add_argument("--fy-end", help="the financial year end as MM-DD (Virre shows it), for the accounts deadline check")

    s = sub.add_parser("dk", help="Denmark: annual reports from the Business Authority's open index and XBRL, with "
                                  "late-filing, negative-equity, going-concern and auditor-remark flags")
    s.add_argument("cvr_or_name", help="an 8-digit CVR number, or a name to list candidates (from GLEIF)")
    s.add_argument("--years", type=int, default=3, help="latest annual reports to read figures and notes from")

    s = sub.add_parser("uk-pages", help="save a scanned accounts PDF's pages as images an agent can read")
    s.add_argument("pdf", help="the uk_accounts_scanned record's url, or a local PDF file")
    s.add_argument("out_dir")
    s.add_argument("--pages", help="pages to save, such as 1-5,33 (default: all)")
    s.add_argument("--scale", type=int, choices=(1, 2, 3, 4), default=2,
                   help="a whole number, 1 to 4: shrink fax-image pages this many times; the default 2 halves each side of a 300 dpi "
                        "scan and stays legible, 1 keeps full size for small print")

    s = sub.add_parser("pdf-text", help="print the text layer of a PDF made by software, such as an electronically filed form")
    s.add_argument("pdf", help="a PDF url (a Companies House document?format=pdf link works) or a local file")

    s = sub.add_parser("verify-report", help="check every red flag's quote in source reports against its cited pages")
    s.add_argument("targets", nargs="+", help="report files, or a run folder (every .md except dossier.md)")

    s = sub.add_parser("quote-check", help="confirm a quote appears on a page, ignoring markup")
    s.add_argument("url", help="a page URL, or a local file such as an mr.py lu --save extract")
    s.add_argument("quote")
    s.add_argument("--context", type=int, default=200)

    for cc in registers.REGISTER_RECORDS:  # each national-register command's --help lists the records it prints
        sub.choices[cc].epilog = registers.register_help(cc)
        sub.choices[cc].formatter_class = argparse.RawDescriptionHelpFormatter

    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    problem = common.sec_contact_problem(a.user_agent) if a.cmd in common.SEC_COMMANDS else None
    if problem:  # these commands only talk to sec.gov, so stop before the first request
        common.emit({"type": "error", "error": problem})
        return 1
    try:
        if a.cmd == "edgar-filings":
            data = json.loads(common.fetch(f"https://data.sec.gov/submissions/CIK{common.cik10(a.cik)}.json", a.user_agent))
            for r in sec.parse_submissions(data, a.limit):
                common.emit(r)
        elif a.cmd == "edgar-facts":
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{common.cik10(a.cik)}.json"
            try:
                data = json.loads(common.fetch(url, a.user_agent))
            except common.FetchError as e:
                if "HTTP 404" not in str(e):
                    raise
                common.emit({"type": "no_xbrl_financials", "url": url,
                      "note": "SEC holds no tagged financial statements for this CIK (it has never filed a 10-K, 10-Q or 20-F with XBRL)"})
                return 0
            for r in sec.parse_companyfacts(data, a.years):
                common.emit(r)
        elif a.cmd == "edgar-search":
            forms = [f.strip() for f in a.forms.split(",") if f.strip()]
            hits, summary = sec.edgar_search(a.phrase, forms, a.since, a.until, a.user_agent, a.max_hits)
            common.emit(summary)
            for r in hits:
                common.emit(r)
        elif a.cmd == "marks":
            aliases = sec.skip_covered(a.aliases, sec.load_searched(a.skip_seen)) if a.skip_seen else a.aliases
            if aliases:
                sec.marks(aliases, a.user_agent, a.since, a.per_filer, a.max_filers, a.verbose, sec.load_seen(a.skip_seen))
        elif a.cmd == "gleif":
            if a.registered_as:
                results = gleif.gleif_search(None, a.limit, registered_as=a.registered_as.strip())
            elif not a.name_or_lei:
                p.error("gleif needs a name, an LEI, or --registered-as")
            else:
                target = a.name_or_lei.strip().upper()
                results = gleif.gleif_report(target, a.max_children) if gleif.LEI_RE.match(target) else gleif.gleif_search(a.name_or_lei, a.limit)
            for r in results:
                common.emit(r)
        elif a.cmd == "ch-search":
            for r in uk.ch_search(a.name, uk.CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY")), a.limit):
                common.emit(r)
        elif a.cmd in ("ch", "uk-accounts"):
            ch = uk.CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY"))
            results = uk.ch_report(a.company_number, ch, a.max_filings, list_filings=a.list_filings) if a.cmd == "ch" \
                else uk.uk_accounts(a.company_number, ch, a.sets)
            for r in results:
                common.emit(r)
        elif a.cmd == "ch-officers":
            ch = uk.CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY"))
            for r in uk.ch_officers(a.company_number, ch, a.max_appointments):
                common.emit(r)
        elif a.cmd == "warn":
            for r in us.warn_report(a.name):
                common.emit(r)
        elif a.cmd == "us-states":
            for r in us.us_states_report(a.names):
                common.emit(r)
        elif a.cmd == "usaspending":
            for r in us.usaspending_report(a.names, a.since):
                common.emit(r)
        elif a.cmd == "csl":
            for r in screening.csl_report(a.names):
                common.emit(r)
        elif a.cmd == "formd":
            for r in sec.formd_report(a.names, a.user_agent, max_hits=a.max_hits):
                common.emit(r)
        elif a.cmd == "icij":
            for r in screening.icij_report(a.names):
                common.emit(r)
        elif a.cmd == "footprint":
            for r in web.footprint_report(a.domain, a.github, a.founded, linkedin=a.linkedin):
                common.emit(r)
        elif a.cmd == "jobs":
            for r in web.jobs_report(a.target, a.history, offices=a.offices):
                common.emit(r)
        elif a.cmd == "lu":
            for r in lu.lu_report(a.rcs[0] if len(a.rcs) == 1 else a.rcs, a.quarters, save=a.save):
                common.emit(r)
        elif a.cmd == "ie":
            for r in ie.ie_report(a.cro_or_name):
                common.emit(r)
        elif a.cmd == "es":
            if not (a.pdf or a.empresia or a.scan_from):
                p.error("es needs --pdf, --empresia, or --scan-from")
            for r in es.es_report(a.name, a.pdf, a.empresia, a.scan_from, a.scan_to, a.province):
                common.emit(r)
        elif a.cmd == "vat":
            for r in vat.vat_report(a.country, a.number):
                common.emit(r)
        elif a.cmd == "br":
            for r in br.br_report(a.cnpj):
                common.emit(r)
        elif a.cmd == "il":
            for r in il.il_report(a.company_number):
                common.emit(r)
        elif a.cmd == "no":
            for r in no.no_report(a.orgnr_or_name):
                common.emit(r)
        elif a.cmd == "dk":
            for r in dk.dk_report(a.cvr_or_name, a.years):
                common.emit(r)
        elif a.cmd == "fi":
            for r in fi.fi_report(a.business_id_or_name, a.fy_end):
                common.emit(r)
        elif a.cmd == "fr":
            for r in fr.fr_report(a.siren_or_name):
                common.emit(r)
        elif a.cmd == "pdf-text":
            if a.pdf.startswith(("http://", "https://")):
                pdf = common.fetch_bytes(a.pdf, None)
            else:
                with open(a.pdf, "rb") as f:
                    pdf = f.read()
            try:
                for r in documents.pdf_text_records(pdf, a.pdf):
                    common.emit(r)
            except ValueError as e:
                common.emit({"type": "error", "source": a.pdf, "error": str(e)})
        elif a.cmd == "uk-pages":
            if a.pdf.startswith(("http://", "https://")):
                pdf = common.fetch_bytes(a.pdf, None)
            else:
                with open(a.pdf, "rb") as f:
                    pdf = f.read()
            for r in documents.page_images(pdf, a.out_dir, documents.parse_pages(a.pages) if a.pages else None, a.scale):
                common.emit(r)
        elif a.cmd == "verify-report":
            for r in verify.verify_reports(verify.report_paths(a.targets), a.user_agent):
                common.emit(r)
        elif a.cmd == "quote-check":
            no.quote_check(a.url, a.quote, a.user_agent, a.context)
    except common.FetchError as e:
        common.emit({"type": "error", "error": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
