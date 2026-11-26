"""Offline tests for mr.py parsers, run with: python -m unittest muckraker/scripts/test_mr.py"""

import contextlib
import datetime as dt
import gzip
import io
import json
import os
import pathlib
import re
import struct
import sys
import tempfile
import unittest
import urllib.parse
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mr  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class IxbrlHoldings(unittest.TestCase):
    def setUp(self):
        self.doc = fixture("bdc_schedule.htm")

    def test_loan_values_scale_and_mark(self):
        rows = mr.parse_ixbrl_holdings(self.doc, ["veracode"])
        latest = next(r for r in rows if r["as_of"] == "2026-09-30")
        self.assertEqual(latest["principal"], 8448000)
        self.assertEqual(latest["fair_value"], 1812096)
        self.assertEqual(latest["mark"], 21.4)
        self.assertEqual(latest["interest_rate"], 8.67)
        self.assertEqual(latest["spread"], 4.75)
        self.assertEqual(latest["maturity"], "5/2/2029")
        earlier = next(r for r in rows if r["as_of"] == "2025-12-31")
        self.assertEqual(earlier["mark"], 65.4)

    def test_flagged_footnotes_attach_to_their_row_only(self):
        rows = {r["as_of"]: r for r in mr.parse_ixbrl_holdings(self.doc, ["veracode"])}
        self.assertEqual(rows["2026-09-30"]["flagged_footnotes"],
                         ["Loan was on non-accrual status as of September 30, 2026."])
        self.assertNotIn("flagged_footnotes", rows["2025-12-31"])  # footnote is linked to the 2026 fact only

    def test_thousands_scale_and_duration_facts_merge(self):
        rows = mr.parse_ixbrl_holdings(self.doc, ["TA Aggregator"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cost"], 5249000)
        self.assertEqual(rows[0]["fair_value"], 1050000)
        self.assertEqual(rows[0]["maturity"], "n/a")  # from the duration context
        self.assertNotIn("mark", rows[0])  # no principal on an equity stake

    def test_negative_fair_value_gets_note_not_mark(self):
        rows = mr.parse_ixbrl_holdings(self.doc, ["revolving"])
        self.assertEqual(rows[0]["fair_value"], -2031000)
        self.assertNotIn("mark", rows[0])
        self.assertTrue(any("unfunded" in n for n in rows[0]["notes"]))

    def test_revolver_and_joint_venture_notes(self):
        self.assertEqual(mr.holding_notes("Acme | First lien senior secured revolving loan", 61.4), [mr.REVOLVER_NOTE])
        self.assertEqual(mr.holding_notes("Acme Purchaser, Inc. | Emerald JV LP", 21.5), [mr.JV_NOTE])
        self.assertEqual(mr.holding_notes("Acme First Lien Term Loan", 21.4), [])

    def test_other_borrowers_ignored(self):
        names = {r["identifier"] for r in mr.parse_ixbrl_holdings(self.doc, ["veracode", "mitnick"])}
        self.assertFalse(any("Red Planet" in n for n in names))


class NportHoldings(unittest.TestCase):
    def test_matching_holding_with_mark(self):
        rows = mr.parse_nport_holdings(fixture("nport.xml"), ["Mitnick"])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["fund"], "Columbia Floating Rate Fund")
        self.assertEqual(r["as_of"], "2026-07-31")
        self.assertEqual(r["mark"], 30.1)
        self.assertEqual(r["isDefault"], "N")
        self.assertEqual(r["maturityDt"], "2029-05-02")

    def test_quote_keeps_values_as_written(self):
        r = mr.parse_nport_holdings(fixture("nport.xml"), ["Mitnick"])[0]
        self.assertIn("<balance>1162621.57000000</balance> <valUSD>350449.02000000</valUSD>", r["quote"])
        self.assertTrue(r["quote"].startswith("<name>"))
        self.assertNotIn("value_per_share", r)  # a loan (units PA), not shares

    def test_share_holding_gets_value_per_share(self):
        doc = fixture("nport.xml").replace("<units>PA</units>", "<units>NS</units>")
        r = mr.parse_nport_holdings(doc, ["Mitnick"])[0]
        self.assertEqual(r["value_per_share"], round(350449.02 / 1162621.57, 4))


class TableRows(unittest.TestCase):
    def test_keeps_holding_rows_only(self):
        rows = mr.parse_table_rows(fixture("table_rows.htm"), ["mitnick"])
        self.assertEqual(len(rows), 1)
        self.assertIn("5,194,288", rows[0]["row"])
        self.assertNotIn("$", rows[0]["row"].split(" | "))
        self.assertEqual(rows[0]["header"], "Borrower | Rate | Maturity | Principal | Value")


class CompanyFacts(unittest.TestCase):
    def test_full_year_values_latest_filing_wins(self):
        rows = list(mr.parse_companyfacts(json.loads(fixture("companyfacts.json")), years=5))
        by_year = {r["period_end"]: r for r in rows}
        self.assertEqual(by_year["2025-12-31"]["figures"], {"revenue": 1200, "cash": 40})
        # the 2024 revenue restated in the 2026 filing replaces the original, and the
        # quarter-length value filed with the same 10-K is ignored
        self.assertEqual(by_year["2024-12-31"]["figures"]["revenue"], 1010)
        self.assertEqual(rows[0]["period_end"], "2025-12-31")


class Search(unittest.TestCase):
    def test_hits_and_filing_choice(self):
        hits = list(mr.parse_search_hits(json.loads(fixture("search.json"))))
        self.assertEqual(hits[0]["url"], "https://www.sec.gov/Archives/edgar/data/1812554/000181255426000060/ocicslf-09302026.htm")
        chosen, notes = mr.choose_filings(hits, per_filer=2)
        accessions = [h["accession"] for h in chosen]
        # both documents of the latest filing, plus the filing closest to a year earlier
        self.assertEqual(accessions.count("0001812554-26-000060"), 2)
        self.assertIn("0001812554-25-000070", accessions)
        self.assertNotIn("0001812554-26-000040", accessions)
        self.assertEqual(notes, [])

    @staticmethod
    def hit(cik, acc, filed, name):
        return {"type": "search_hit", "filer": "Trust", "cik": cik, "form": "NPORT-P", "filed": filed,
                "period_ending": None, "accession": acc, "url": f"https://www.sec.gov/{acc}/{name}"}

    def test_trust_funds_compared_fund_with_fund(self):
        # one trust files a separate N-PORT per fund, a few days apart
        hits = [self.hit("1", "a1", "2026-10-29", "x.xml"), self.hit("1", "a2", "2026-10-27", "y.xml"),
                self.hit("1", "b1", "2025-10-30", "x.xml"), self.hit("1", "b2", "2025-10-28", "y.xml")]
        chosen, notes = mr.choose_filings(hits, per_filer=2)
        self.assertEqual(sorted(h["accession"] for h in chosen), ["a1", "a2", "b1", "b2"])

    def test_no_year_earlier_filing_is_reported_not_substituted(self):
        hits = [self.hit("2", "a", "2026-08-25", "x.xml"), self.hit("2", "b", "2026-05-26", "x.xml")]
        chosen, notes = mr.choose_filings(hits, per_filer=2)
        self.assertEqual([h["accession"] for h in chosen], ["a"])
        self.assertEqual(notes[0]["type"], "no_earlier_filing")

    def test_search_summary_flags_truncation(self):
        data = json.loads(fixture("search.json"))
        original = mr.fetch
        mr.fetch = lambda url, ua: json.dumps(data)
        try:
            hits, summary = mr.edgar_search("x", [], None, None, "ua", 2)
        finally:
            mr.fetch = original
        self.assertEqual(len(hits), 2)
        self.assertEqual(summary["total"], 3)
        self.assertTrue(summary["truncated"])


class QuoteCheck(unittest.TestCase):
    def run_check(self, page, quote):
        original, out = mr.fetch, []
        mr.fetch, emit = (lambda url, ua: page), mr.emit
        mr.emit = out.append
        try:
            mr.quote_check("https://example.test/doc", quote, None, 20)
        finally:
            mr.fetch, mr.emit = original, emit
        return out[0]["found"]

    def test_nport_quote_with_tags_matches(self):
        page = fixture("nport.xml")
        self.assertTrue(self.run_check(page, "<name>MITNICK CORPORATE PURCHASER INC</name> <balance>1162621.57000000</balance>"))
        self.assertFalse(self.run_check(page, "<name>MITNICK CORPORATE PURCHASER INC</name> <balance>999</balance>"))

    def test_table_quote_matches_cell_by_cell(self):
        page = fixture("table_rows.htm")
        self.assertTrue(self.run_check(page, "Mitnick Corporate Purchaser, Inc. (e)(f) | 3M SOFR + 4.75%, 0.50% Floor | 5/3/2029"))


class VerifyReport(unittest.TestCase):
    PAGES = {
        "https://example.test/rating": "<h1>Acme Parent L.P. Downgraded To &#39;CCC&#39; From &#39;CCC+&#39;</h1>",
        "https://example.test/schedule": "<table><tr><td>Acme Purchaser, Inc. (6)</td><td>First Lien</td>"
                                         "<td>8,448,000</td><td>1,812,096</td></tr></table>",
        "https://example.test/nport.xml": "<invstOrSec><name>ACME PURCHASER INC</name><lei>X</lei>"
                                          "<balance>1162621.57</balance></invstOrSec>",
    }

    def fetcher(self, url):
        if url in self.PAGES:
            return self.PAGES[url]
        raise mr.FetchError(f"HTTP 403 for {url}")

    def test_parses_only_red_flags_section(self):
        flags = mr.parse_red_flags(fixture("report.md"))
        self.assertEqual(len(flags), 6)
        self.assertEqual(flags[0]["title"], "Downgrade to CCC.")
        self.assertEqual(flags[1]["urls"], ["https://example.test/schedule"])
        self.assertTrue(flags[2]["quote"].startswith("<name>"))
        self.assertEqual(flags[3]["quote"], "Jane Doe serves as Acme’s Interim Chief Executive Officer.")
        self.assertIsNone(flags[5]["quote"])

    def test_results(self):
        path = str(FIXTURES / "report.md")
        records = list(mr.verify_reports([path], None, fetcher=self.fetcher))
        results = [r["result"] for r in records if r["type"] == "red_flag_check"]
        self.assertEqual(results, ["confirmed", "confirmed", "confirmed", "unreachable", "not_found", "no_quote"])
        summary = records[-1]
        self.assertEqual((summary["confirmed"], summary["not_found"], summary["unreachable"], summary["no_quote"]), (3, 1, 1, 1))

    def test_each_page_fetched_once(self):
        calls = []

        def counting(url):
            calls.append(url)
            return self.fetcher(url)
        list(mr.verify_reports([str(FIXTURES / "report.md")], None, fetcher=counting))
        self.assertEqual(calls.count("https://example.test/schedule"), 1)

    def test_soft_hyphens_ignored(self):
        page = mr.text_of("<p>ter&shy;mi&shy;na&shy;tion: 09/05/2023 · liq­ui­da­tion: voluntaria</p>").lower()
        self.assertGreaterEqual(mr.find_quote(page, "Termination: 09/05/2023 · Liquidation: Voluntaria")[0], 0)


class Gleif(unittest.TestCase):
    @staticmethod
    def record(lei, name, jurisdiction):
        return {"attributes": {"lei": lei, "entity": {"legalName": {"name": name}, "jurisdiction": jurisdiction,
                                                      "legalAddress": {"city": "X", "country": jurisdiction[:2]}},
                               "registration": {"status": "ISSUED"}}}

    def fetcher(self, routes):
        def get(url):
            path = url[len(mr.GLEIF):]
            for prefix, body in routes.items():
                if path.split("?")[0] == prefix:
                    return json.dumps(body)
            raise mr.FetchError(f"HTTP 404 for {url}")
        return get

    def test_chain_offshore_flag_and_children(self):
        child = self.record("CHILD000000000000001", "Acme Ltd", "GB")
        parent = self.record("PARENT00000000000002", "Acme Holdings", "KY")
        sub = self.record("SUB00000000000000003", "Acme GmbH", "DE")
        routes = {
            "/lei-records/CHILD000000000000001": {"data": child},
            "/lei-records/CHILD000000000000001/direct-parent": {"data": parent},
            "/lei-records/PARENT00000000000002/direct-parent-reporting-exception":
                {"data": {"attributes": {"reason": "NATURAL_PERSONS"}}},
            "/lei-records/CHILD000000000000001/direct-children": {"data": [sub], "meta": {"pagination": {"lastPage": 1}}},
            "/lei-records/CHILD000000000000001/ultimate-children": {"data": [sub], "meta": {"pagination": {"lastPage": 1}}},
        }
        out = list(mr.gleif_report("CHILD000000000000001", fetcher=self.fetcher(routes)))
        types = [r["type"] for r in out]
        self.assertEqual(types, ["gleif_entity", "gleif_parent", "gleif_chain_end", "gleif_flag", "gleif_child", "gleif_summary"])
        self.assertEqual(out[2]["exception_reason"], "NATURAL_PERSONS")
        self.assertEqual(out[3]["country_name"], "Cayman Islands")
        self.assertEqual(out[-1]["child_countries_outside_us_uk"], ["DE"])

    def test_no_parent_reports_exception(self):
        routes = {
            "/lei-records/SOLO0000000000000001": {"data": self.record("SOLO0000000000000001", "Solo Inc", "US-DE")},
            "/lei-records/SOLO0000000000000001/direct-parent-reporting-exception":
                {"data": {"attributes": {"reason": "NATURAL_PERSONS"}}},
            "/lei-records/SOLO0000000000000001/ultimate-parent-reporting-exception":
                {"data": {"attributes": {"reason": "NATURAL_PERSONS"}}},
        }
        out = list(mr.gleif_report("SOLO0000000000000001", fetcher=self.fetcher(routes)))
        self.assertIn({"type": "gleif_no_ultimate_parent", "exception_reason": "NATURAL_PERSONS"}, out)
        self.assertEqual(out[-1]["parents"], 0)


class RowQuotes(unittest.TestCase):
    def test_loan_row_carries_page_text_quote_with_figures(self):
        rows = mr.parse_ixbrl_holdings(fixture("bdc_schedule.htm"), ["veracode"])
        latest = next(r for r in rows if r["as_of"] == "2026-09-30")
        self.assertTrue(latest["quote"].startswith("Veracode | 8.67"))
        self.assertTrue(latest["quote"].endswith("8,448,000 | 8,431,553 | 1,812,096"))
        # the quote is found on the page the way verify-report searches it
        page = mr.text_of(fixture("bdc_schedule.htm")).lower()
        self.assertGreaterEqual(mr.find_quote(page, latest["quote"])[0], 0)

    def test_hidden_fact_gets_no_quote(self):
        doc = ('<ix:header><ix:hidden><ix:nonFraction contextRef="C" name="us-gaap:InvestmentOwnedAtFairValue" '
               'decimals="0">5</ix:nonFraction></ix:hidden></ix:header><table><tr><td>Acme</td></tr></table>')
        self.assertIsNone(mr.enclosing_row(doc, doc.find("<ix:nonFraction")))


class TableRowHeaderAndDate(unittest.TestCase):
    DOC = ("<p>Schedule of Investments as of December 31, 2025</p><p>Schedule of Investments as of "
           "September 30, 2026</p><table><tr><td>Interest</td></tr>"
           "<tr><td>Company</td><td>Investment</td><td>Interest</td><td>Par</td><td>Fair Value</td></tr>"
           "<tr><td>Mitnick Corporate Purchaser, Inc.(6)</td><td>First lien senior secured loan</td>"
           "<td>S+ 4.75%</td><td>2,957</td><td>575</td></tr></table>")

    def test_header_skips_one_word_heading_row_and_date_comes_from_heading(self):
        rows = mr.parse_table_rows(self.DOC, ["mitnick"])
        self.assertEqual(rows[0]["header"], "Company | Investment | Interest | Par | Fair Value")
        self.assertEqual(rows[0]["table_date"], "2026-09-30")


class FundTrend(unittest.TestCase):
    @staticmethod
    def row(fund, as_of):
        return {"filer": "SEI Trust", "cik": "939934", "fund": fund, "as_of": as_of}

    def test_fund_without_its_own_earlier_point_is_reported(self):
        holdings = [self.row("SIIT High Yield Bond Fund", "2026-08-31"),
                    self.row("SIIT Opportunistic Income Fund", "2025-08-31"),
                    self.row("SIIT Core Fund", "2026-08-31"), self.row("SIIT Core Fund", "2025-08-31")]
        notes = mr.fund_trend_notes(holdings, per_filer=2)
        self.assertEqual([n["fund"] for n in notes], ["SIIT High Yield Bond Fund"])  # the exited fund is not a gap

    def test_renamed_fund_matched_by_series_id(self):
        holdings = [{**self.row("NYLIM Floating Rate Fund", "2026-07-31"), "series_id": "S1"},
                    {**self.row("NYLI Floating Rate Fund", "2025-07-31"), "series_id": "S1"}]
        self.assertEqual(mr.fund_trend_notes(holdings, per_filer=2), [])

    def test_closed_end_fund_renamed_and_to_ampersand(self):
        # closed-end funds file no series id; BlackRock renamed "and" to "&" between filings
        holdings = [self.row("BlackRock Science & Technology Term Trust", "2026-06-30"),
                    self.row("BlackRock Science and Technology Term Trust", "2025-06-30")]
        self.assertEqual(mr.fund_trend_notes(holdings, per_filer=2), [])

    def test_mark_change_per_share_line(self):
        def line(fund, as_of, shares, value):
            return {**self.row(fund, as_of), "name": "SNYK LIMITED", "balance": shares, "url": as_of,
                    "value_per_share": round(value / shares, 4)}
        holdings = [line("BST & Co", "2026-06-30", 1267643.0, 3422636.1),
                    line("BST & Co", "2026-06-30", 2663936.0, 7192627.2),
                    line("BST and Co", "2025-06-30", 2663936.0, 15397550.08),
                    line("BST and Co", "2025-06-30", 1267643.0, 7326976.54)]
        changes = sorted(mr.fund_mark_changes(holdings), key=lambda c: c["shares"])
        self.assertEqual([(c["shares"], c["from_per_share"], c["to_per_share"], c["change_pct"]) for c in changes],
                         [(1267643.0, 5.78, 2.7, -53.3), (2663936.0, 5.78, 2.7, -53.3)])
        self.assertEqual(changes[0]["from_as_of"], "2025-06-30")


class MarksOutput(unittest.TestCase):
    def test_no_holdings_found_cites_the_searches(self):
        out, saved = [], (mr.edgar_search, mr.emit)
        mr.edgar_search = lambda *a: ([], {"type": "search_summary", "truncated": False, "total": 0})
        mr.emit = out.append
        try:
            mr.marks(["Sanity"], "ua", "2025-08-25", 2, 20)
        finally:
            mr.edgar_search, mr.emit = saved
        none = next(r for r in out if r["type"] == "no_holdings_found")
        self.assertEqual(len(none["urls"]), 2)  # lender forms and fund forms
        self.assertTrue(none["urls"][0].startswith("https://www.sec.gov/edgar/search/#/q=%22Sanity%22"))
        self.assertIn("forms=10-K%2C10-Q", none["urls"][0])

    def test_trend_notes_only_for_holders(self):
        hits = [{"type": "search_hit", "filer": f, "cik": c, "form": "10-Q", "filed": "2026-08-07",
                 "period_ending": "2026-06-30", "accession": c, "url": f"https://www.sec.gov/{c}/doc.htm"}
                for f, c in (("Holder BDC", "1"), ("Customer Co", "2"))]
        docs = {"https://www.sec.gov/1/doc.htm": fixture("table_rows.htm"),
                "https://www.sec.gov/2/doc.htm": "<p>Our customers include Mitnick.</p>"}
        out, saved = [], (mr.edgar_search, mr.fetch, mr.emit)
        mr.edgar_search = lambda *a: (hits if a[1] == ["10-K", "10-Q"] else [],
                                      {"type": "search_summary", "truncated": False})
        mr.fetch, mr.emit = (lambda url, ua: docs[url]), out.append
        try:
            mr.marks(["Mitnick"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.fetch, mr.emit = saved
        no_earlier = [r["filer"] for r in out if r["type"] == "no_earlier_filing"]
        self.assertEqual(no_earlier, ["Holder BDC"])

    def test_skip_seen_end_to_end(self):
        # a second run appending to the first run's file prints nothing it already has
        hits = [{"type": "search_hit", "filer": "Holder BDC", "cik": "1", "form": "10-Q", "filed": "2026-08-07",
                 "period_ending": "2026-06-30", "accession": "1", "url": "https://www.sec.gov/1/doc.htm"}]
        saved = (mr.edgar_search, mr.fetch, mr.emit)
        mr.edgar_search = lambda *a: (hits if a[1] == ["10-K", "10-Q"] else [],
                                      {"type": "search_summary", "truncated": False})
        mr.fetch = lambda url, ua: fixture("table_rows.htm")
        try:
            first, second = [], []
            mr.emit = first.append
            mr.marks(["Mitnick"], "ua", "2025-08-01", 2, 20)
            seen = {mr.record_key(r) for r in first}
            mr.emit = second.append
            mr.marks(["Mitnick"], "ua", "2025-08-01", 2, 20, False, seen)
        finally:
            mr.edgar_search, mr.fetch, mr.emit = saved
        self.assertTrue(any(r["type"] == "table_row" for r in first))
        self.assertFalse(any(r["type"] == "table_row" for r in second))
        self.assertEqual(next(r for r in second if r["type"] == "already_seen")["skipped"], 1)

    def test_broader_alias_in_same_run_covers_longer_ones(self):
        searched, out, saved = [], [], (mr.edgar_search, mr.emit)

        def search(alias, forms, *a):
            searched.append(alias)
            return [], {"type": "search_summary", "truncated": alias == "Falcon"}
        mr.edgar_search, mr.emit = search, out.append
        try:
            mr.marks(["Snyk Limited", "Snyk", "Snyk, Inc.", "Falcon Purchaser", "Falcon"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.emit = saved
        # "Falcon" was cut short, so the longer Falcon name still gets its own search
        self.assertEqual(sorted(set(searched)), ["Falcon", "Falcon Purchaser", "Snyk"])
        self.assertEqual(sorted((r["alias"], r["covered_by"]) for r in out if r["type"] == "already_searched"),
                         [("Snyk Limited", "Snyk"), ("Snyk, Inc.", "Snyk")])


    def test_skip_seen_skips_covered_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "marks.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "marks_search", "aliases": ["Veracode", "Mitnick"]}) + chr(10))
            out, saved = [], mr.emit
            mr.emit = out.append
            try:
                left = mr.skip_covered(["Mitnick Corp. Purchaser, Inc.", "Mitnickson Holdings"],
                                       mr.load_searched(path))
            finally:
                mr.emit = saved
        self.assertEqual(left, ["Mitnickson Holdings"])
        self.assertEqual([(r["alias"], r["covered_by"]) for r in out],
                         [("Mitnick Corp. Purchaser, Inc.", "Mitnick")])


class GleifNoMatch(unittest.TestCase):
    def test_no_candidate_is_reported(self):
        out = list(mr.gleif_search("Mitnick Parent", 10, fetcher=lambda url: json.dumps({"data": []})))
        self.assertEqual([r["type"] for r in out], ["gleif_no_match"])
        self.assertEqual(out[0]["query"], "Mitnick Parent")


class VerifyWarnings(unittest.TestCase):
    def test_short_and_repeated_quotes_warn(self):
        page = "veracode first lien 8.69% veracode first lien 8.67%"
        self.assertEqual(len(mr.quote_warnings(page, "Veracode", "veracode")), 2)
        self.assertEqual(mr.quote_warnings(page, "Veracode first lien 8.67%", "veracode first lien 8.67%"), [])

    def test_missing_url_counted_as_no_url(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write('## Red flags\n\n1. **Fund mark.** Quote: "<name>ACME</name> <balance>1</balance>"\n')
        try:
            records = list(mr.verify_reports([f.name], None, fetcher=lambda u: ""))
        finally:
            pathlib.Path(f.name).unlink()
        self.assertEqual(records[0]["result"], "no_url")
        self.assertEqual((records[-1]["no_url"], records[-1]["no_quote"]), (1, 0))


class CompaniesHouseLateFilings(unittest.TestCase):
    def test_officer_psc_and_confirmation_windows(self):
        tm01 = {"type": "TM01", "date": "2026-11-17", "action_date": "2026-10-15"}
        self.assertEqual(mr.late_filing(tm01, "ltd")["days_late"], 19)
        on_time = {"type": "AP01", "date": "2026-01-10", "action_date": "2025-12-29"}
        self.assertIsNone(mr.late_filing(on_time, "ltd"))
        psc = {"type": "PSC01", "date": "2024-05-09", "action_date": "2024-04-12"}  # 27 days: within 28
        self.assertIsNone(mr.late_filing(psc, "ltd"))
        cs = {"type": "CS01", "date": "2026-04-28", "action_date": "2026-04-09"}
        self.assertEqual(mr.late_filing(cs, "ltd")["days_late"], 5)

    def test_accounts_deadline_by_company_type(self):
        aa = {"type": "AA", "date": "2024-10-31", "description_values": {"made_up_date": "2023-12-31"}}
        self.assertEqual(mr.late_filing(aa, "ltd")["due"], "2024-09-30")
        self.assertEqual(mr.late_filing(aa, "plc")["due"], "2024-06-30")
        early = {"type": "AA", "date": "2024-09-15", "description_values": {"made_up_date": "2023-12-31"}}
        self.assertIsNone(mr.late_filing(early, "ltd"))
        amended = {"type": "AAMD", "date": "2022-02-04", "description_values": {"made_up_date": "2020-12-31"}}
        self.assertIsNone(mr.late_filing(amended, "ltd"))

    def test_report_from_api(self):
        api = {
            "/company/01234567": {"company_name": "ACME LTD", "company_status": "active", "type": "ltd",
                                  "accounts": {"overdue": True}, "confirmation_statement": {"overdue": False},
                                  "has_charges": False, "has_insolvency_history": False},
            "/company/01234567/officers": {"items": [
                {"name": "DOE, Jane", "officer_role": "director", "appointed_on": "2026-01-02",
                 "date_of_birth": {"month": 1, "year": 1970}, "address": {"premises": "1"}}]},
            "/company/01234567/persons-with-significant-control": {"items": []},
            "/company/01234567/persons-with-significant-control-statements": {"items": [
                {"statement": "no-individual-or-entity-with-signficant-control", "notified_on": "2020-01-01"}]},
            "/company/01234567/filing-history": {"total_count": 3, "items": [
                {"type": "GAZ1", "date": "2026-10-01", "category": "gazette", "transaction_id": "t1",
                 "description": "gazette-notice-compulsory"},
                {"type": "TM01", "date": "2026-09-30", "action_date": "2026-08-01", "transaction_id": "t2",
                 "description": "termination-director"},
                {"type": "AP01", "date": "2026-01-05", "action_date": "2026-01-02", "transaction_id": "t3",
                 "description": "appoint-director"}]},
        }

        def fake(url, accept=None):
            path = url[len(mr.CH_API):].split("?")[0]
            if path in api:
                return json.dumps(api[path])
            raise mr.FetchError(f"HTTP 404 for {url}")
        api["/company/01234567/persons-with-significant-control-statements"]["items"].append(
            dict(api["/company/01234567/persons-with-significant-control-statements"]["items"][0]))  # duplicate
        api["/company/01234567/filing-history"]["items"].append(  # details change dated on the appointment day
            {"type": "CH01", "date": "2026-06-01", "action_date": "2026-01-02", "transaction_id": "t4",
             "description": "change-person-director"})
        api["/company/01234567/filing-history"]["total_count"] = 4
        out = list(mr.ch_report("01234567", mr.CompaniesHouse(None, fetcher=fake),
                                today=dt.date(2026, 11, 22), list_filings=2))
        self.assertEqual(sum(1 for r in out if r["type"] == "ch_psc_statement"), 1)
        gazette = next(r for r in out if r.get("flag") == "gazette notice")
        self.assertEqual(gazette["quote"], "01 Oct 2026 GAZ1")
        self.assertTrue(gazette["url"].endswith("/filing-history?page=1"))
        flags = [r["flag"] for r in out if r["type"] == "ch_flag"]
        self.assertEqual(flags, ["accounts overdue", "gazette notice", "late filing"])
        officer = next(r for r in out if r["type"] == "ch_officer")
        self.assertNotIn("date_of_birth", officer)  # people only in their company roles
        self.assertNotIn("address", officer)
        self.assertEqual(sum(1 for r in out if r["type"] == "ch_filing"), 2)  # listed, though all 4 were checked
        self.assertEqual(out[-1]["filings_read"], 4)

    def test_charges_read_even_when_profile_says_none(self):
        api = {
            "/company/09677925": {"company_name": "S LTD", "type": "ltd", "accounts": {}, "confirmation_statement": {},
                                  "has_charges": False},
            "/company/09677925/charges": {"items": [
                {"status": "outstanding", "created_on": "2026-04-14", "charge_code": "096779250007",
                 "persons_entitled": [{"name": "HSBC Bank USA, National Association"}]}]},
        }

        def fake(url, accept=None):
            path = url[len(mr.CH_API):].split("?")[0]
            if path in api:
                return json.dumps(api[path])
            raise mr.FetchError(f"HTTP 404 for {url}")
        charges = [r for r in mr.ch_report("09677925", mr.CompaniesHouse(None, fetcher=fake)) if r["type"] == "ch_charge"]
        self.assertEqual([c["persons_entitled"] for c in charges], [["HSBC Bank USA, National Association"]])

    def test_late_accounts_note_possible_extension(self):
        api = {
            "/company/07654321": {"company_name": "B LTD", "type": "ltd", "accounts": {}, "confirmation_statement": {}},
            "/company/07654321/filing-history": {"total_count": 2, "items": [
                {"type": "AA", "date": "2024-12-20", "transaction_id": "a", "description_values": {"made_up_date": "2023-12-31"}},
                {"type": "AA01", "date": "2024-03-01", "transaction_id": "b", "description": "change-account-reference-date"}]},
        }

        def fake(url, accept=None):
            path = url[len(mr.CH_API):].split("?")[0]
            if path in api:
                return json.dumps(api[path])
            raise mr.FetchError(f"HTTP 404 for {url}")
        flag = next(r for r in mr.ch_report("07654321", mr.CompaniesHouse(None, fetcher=fake)) if r.get("flag") == "late accounts")
        self.assertIn("2024-03-01", flag["possible_extension"])
        self.assertNotIn("COVID", flag["possible_extension"])

    def test_covid_extension_hint(self):
        self.assertIn("automatic", mr.covid_extension(dt.date(2020, 9, 30)))
        self.assertIn("on application", mr.covid_extension(dt.date(2021, 9, 30)))
        self.assertIsNone(mr.covid_extension(dt.date(2022, 9, 30)))
        self.assertIsNone(mr.covid_extension(dt.date(2019, 9, 30)))


def g4(bits):
    """Bytes from a string of CCITT bits, padded to whole bytes."""
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


# 8 pixels wide: row 1 is horizontal mode (white 2, black 3) then V0; row 2 copies it with V0 x3;
# row 3 is pass mode then V0, so all white; then EOFB.
G4_SAMPLE = g4("001" + "0111" + "10" + "1" + "111" + "0001" + "1" + "000000000001" * 2)


class PageImages(unittest.TestCase):
    def test_g4_decode(self):
        self.assertEqual(list(mr.g4_rows(G4_SAMPLE, 8, 3)), [[2, 5, 8], [2, 5, 8], [8]])
        with self.assertRaises(ValueError):
            list(mr.g4_rows(G4_SAMPLE, 8, 4))  # EOFB before the fourth row

    def test_png_rows(self):
        png = mr.png_1bit(mr.g4_rows(G4_SAMPLE, 8, 3), 8, 3)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat), b"\x00\xc7\x00\xc7\x00\xff")  # 1 is white

    def test_scanned_pdf_pages(self):
        pdf = (b"%PDF-1.1\n4 0 obj\n<< /Type /XObject /Subtype /Image /Width 8 /Height 3 /Length 5 0 R "
               b"/Filter /CCITTFaxDecode /DecodeParms << /K -1 /Columns 8 /Rows 3 >> >>\nstream\n" + G4_SAMPLE +
               b"\nendstream\nendobj\n5 0 obj\n%d\nendobj\n6 0 obj\n<< /Subtype /Image /Width 1 /Height 1 "
               b"/Filter /JPXDecode /Length 1 >>\nstream\nx\nendstream\nendobj\n" % len(G4_SAMPLE))
        with tempfile.TemporaryDirectory() as tmp:
            out = list(mr.page_images(pdf, tmp))
            self.assertEqual([r["type"] for r in out],
                             ["uk_accounts_page", "uk_accounts_page_unsupported", "uk_accounts_pages"])
            with open(out[0]["path"], "rb") as f:
                self.assertTrue(f.read().startswith(b"\x89PNG"))
            self.assertEqual(out[-1]["images"], 2)
            self.assertEqual((out[0]["width"], out[0]["height"]), (8, 3))
            self.assertEqual(len(list(mr.page_images(pdf, tmp, mr.parse_pages("2")))), 2)
            halved = next(mr.page_images(pdf, tmp, scale=2))  # the record gives the saved size
            with open(halved["path"], "rb") as f:
                saved = struct.unpack(">II", f.read(24)[16:24])
            self.assertEqual((halved["width"], halved["height"]), saved)
            self.assertEqual(saved, (4, 2))
        self.assertEqual(mr.parse_pages("1-3, 7"), {1, 2, 3, 7})

    def test_oversized_image_is_refused(self):
        # A few bytes of "V0" codes claiming 100000 x 100000 pixels must not build a 1.25 GB bitmap.
        with self.assertRaises(ValueError):
            mr.png_1bit(mr.g4_rows(g4("1" * 64), 100000, 100000), 100000, 100000)
        pdf = (b"1 0 obj\n<< /Subtype /Image /Width 100000 /Height 100000 /Length 8 /Filter /CCITTFaxDecode "
               b"/DecodeParms << /K -1 >> >>\nstream\n" + g4("1" * 64) + b"\nendstream\nendobj\n")
        with tempfile.TemporaryDirectory() as tmp:
            out = list(mr.page_images(pdf, tmp))
        self.assertEqual([r["type"] for r in out], ["error", "uk_accounts_pages"])

    def test_flate_1bit_pages(self):
        # Brønnøysund's accounts copies: 1-bit DeviceGray bitmaps under FlateDecode, 0 is black
        bitmap = bytes([0b00111000, 0xFF, 0b11000111])  # 8 x 3: one black run per row except the middle
        data = zlib.compress(bitmap)
        pdf = (b"%%PDF-1.4\n1 0 obj\n<< /Type /XObject /Subtype /Image /Filter /FlateDecode /BitsPerComponent 1 "
               b"/Width 8 /Height 3 /ColorSpace /DeviceGray /Length %d >>\nstream\n" % len(data) + data
               + b"\nendstream\nendobj\n")
        with tempfile.TemporaryDirectory() as tmp:
            [page, summary] = list(mr.page_images(pdf, tmp))
            self.assertEqual((page["type"], summary["written"]), ("uk_accounts_page", 1))
            with open(page["path"], "rb") as f:
                png = f.read()
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat), b"\x00" + bitmap[:1] + b"\x00\xff\x00" + bitmap[2:])  # PNG: 1 is white
        with self.assertRaises(ValueError):  # data shorter than the claimed size
            list(mr.flate_1bit_rows(b"\x00", 8, 3))


class UkAccounts(unittest.TestCase):
    def test_entity_totals_texts_and_signs(self):
        figures, texts = mr.parse_uk_ixbrl(fixture("uk_accounts.xhtml"))
        y25 = figures["2025-12-31"]
        self.assertEqual(y25["turnover"], 10578415)  # not the US segment's 999
        self.assertEqual(y25["employees"], 53)  # after a self-closing text fact
        self.assertEqual(y25["cash"], 1435903)
        # printed 613,886 but tagged sign="-": the printed sign wins and the mismatch is reported
        self.assertEqual(y25["operating_cash_flow"], 613886)
        self.assertEqual(y25["sign_mismatch"], ["operating_cash_flow"])
        self.assertEqual(y25["director_remuneration"], 0)  # a dash for zero is not a mismatch
        y24 = figures["2024-12-31"]
        self.assertEqual(y24["operating_cash_flow"], -92485)  # printed in brackets, tagged positive
        self.assertEqual(y24["sign_mismatch"], ["operating_cash_flow"])
        self.assertEqual(y24["employees"], 63)
        self.assertEqual(texts["going_concern_basis"], "true")
        self.assertEqual(texts["auditor"], "Zome (Statutory Auditor)")
        self.assertNotIn("audited", texts)  # the self-closing fact has no value

    def test_notes_sentences(self):
        notes = mr.extract_notes(fixture("uk_accounts.xhtml"))
        parent = " ".join(notes["parent_and_control"])
        self.assertIn("Mitnick Corporate Holdco, Inc", parent)
        self.assertIn("Mitnick Parent LP", parent)
        self.assertIn("confirmed its support", notes["going_concern"][0])
        self.assertIn("no subsequent events", " ".join(notes["events_after_year_end"]))

    def test_older_accounts_fill_gaps_newer_ones_lack(self):
        newer = '<xbrli:context id="a"><xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period></xbrli:context>' \
                '<ix:nonFraction contextRef="a" name="c:NetAssetsLiabilities" decimals="0">3,359,475</ix:nonFraction>'
        older = fixture("uk_accounts.xhtml").replace("2025", "2023").replace("2024", "2022")
        docs = {"m1": newer, "m2": older}
        filings = {"items": [
            {"type": "AA", "date": "2025-09-12", "transaction_id": "t1", "links": {"document_metadata": "m1"},
             "description_values": {"made_up_date": "2024-12-31"}},
            {"type": "AA", "date": "2024-10-31", "transaction_id": "t2", "links": {"document_metadata": "m2"},
             "description_values": {"made_up_date": "2023-12-31"}}]}

        class FakeCH:
            def get(self, path):
                return filings

            def metadata(self, url):
                return {"resources": {"application/xhtml+xml": {}}}

            def document(self, url, accept):
                return docs[url]
        out = list(mr.uk_accounts("07217991", FakeCH(), sets=2))
        y23 = next(r for r in out if r["type"] == "uk_accounts_year" and r["period_end"] == "2023-12-31")
        self.assertEqual(y23["figures"]["net_assets"], 3359475)  # from the newer filing
        self.assertEqual(y23["figures"]["turnover"], 10578415)  # filled from the older filing
        self.assertEqual(len(y23["sources"]), 2)

    def test_scanned_latest_accounts_are_reported(self):
        filings = {"items": [
            {"type": "AA", "date": "2026-09-30", "transaction_id": "t0", "links": {"document_metadata": "m0"},
             "description_values": {"made_up_date": "2025-12-31"}},
            {"type": "AA", "date": "2019-09-30", "transaction_id": "t1", "links": {"document_metadata": "m1"},
             "description_values": {"made_up_date": "2018-12-31"}}]}

        class FakeCH:
            def get(self, path):
                return filings

            def metadata(self, url):
                return {"resources": {"application/pdf": {}} if url == "m0" else {"application/xhtml+xml": {}}}

            def document(self, url, accept):
                return fixture("uk_accounts.xhtml")
        out = list(mr.uk_accounts("09677925", FakeCH()))
        types = [r["type"] for r in out]
        self.assertLess(types.index("uk_accounts_latest_scanned"), types.index("uk_accounts_notes"))
        r = next(r for r in out if r["type"] == "uk_accounts_latest_scanned")
        self.assertEqual((r["scanned_made_up_dates"], r["notes_from"]), (["2025-12-31"], "2018-12-31"))

    def test_reference_date_change_is_not_accounts(self):
        # AA01 sits in the accounts category but changes the accounting reference date
        filings = {"items": [
            {"type": "AA01", "date": "2026-05-12", "transaction_id": "t0", "links": {"document_metadata": "m0"},
             "description_values": {"made_up_date": "2027-04-30", "new_date": "2027-01-31"}}]}

        class FakeCH:
            def get(self, path):
                return filings

            def metadata(self, url):
                return {"resources": {"application/pdf": {}}, "pages": 1}
        out = list(mr.uk_accounts("17147597", FakeCH()))
        self.assertEqual([r["type"] for r in out], ["uk_accounts_none"])


class RunSixFixes(unittest.TestCase):
    def test_severity_on_flags(self):
        officer = mr.late_filing({"type": "TM01", "date": "2026-11-17", "action_date": "2026-10-15"}, "ltd")
        accounts = mr.late_filing({"type": "AA", "date": "2024-10-31", "description_values": {"made_up_date": "2023-12-31"}}, "ltd")
        self.assertEqual((officer["severity"], accounts["severity"]), ("minor", "major"))

    def test_auditor_and_type_changes(self):
        used = [  # newest first, as uk_accounts collects them
            {"made_up_date": "2025-12-31", "auditor": "Zome (Statutory Auditor)", "accounts_type": "medium", "url": "u3"},
            {"made_up_date": "2024-12-31", "auditor": "Zome Audit Limited (Statutory Auditor)", "accounts_type": "medium", "url": "u2"},
            {"made_up_date": "2023-12-31", "auditor": "WD Audit Limited (Statutory Auditor)", "accounts_type": "full", "url": "u1"},
        ]
        changes = [(c["change"], c["from"], c["to"]) for c in mr.accounts_changes(used)]
        self.assertEqual(changes, [("auditor", "WD Audit Limited (Statutory Auditor)", "Zome Audit Limited (Statutory Auditor)"),
                                   ("accounts type", "full", "medium")])  # Zome -> Zome is the same firm

    def test_group_balances_note(self):
        doc = "<p>Amounts owed by group undertakings are interest free, unsecured and repayable on demand.</p>"
        self.assertIn("interest free", mr.extract_notes(doc)["group_balances"][0])

    def test_skip_seen_key(self):
        r = {"url": "u", "identifier": "Acme loan", "as_of": "2026-09-30", "mark": 21.4}
        self.assertEqual(mr.record_key(r), mr.record_key(dict(r, mark=99)))  # same holding, same period

    def test_pdf_page_is_no_text_layer(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write('## Red flags\n\n1. **Revoked.** https://example.test/scan.pdf CHECKED: opened\n   Quote: "revoked"\n')
        out = list(mr.verify_reports([f.name], None, fetcher=lambda u: "%PDF-1.4 binary"))
        os.unlink(f.name)
        self.assertEqual(out[0]["result"], "no_text_layer")
        self.assertEqual(out[-1]["no_text_layer"], 1)



class RunSevenFixes(unittest.TestCase):
    @staticmethod
    def loan(fund, as_of, principal, mark, cusip="C1"):
        return {"filer": "UBS Trust", "cik": "946110", "fund": fund, "as_of": as_of, "name": "Mitnick Corporate Purchaser",
                "title": "Term Loan", "cusip": cusip, "balance": principal, "mark": mark, "url": as_of}

    def test_loan_mark_change(self):
        # the fund more than doubled its holding, so principal changes; CUSIP pairs the loan
        holdings = [self.loan("Floating Rate High Income", "2025-07-31", 1000.0, 70.5),
                    self.loan("Floating Rate High Income", "2026-07-31", 2500.0, 31.6)]
        [c] = mr.fund_mark_changes(holdings)
        self.assertEqual((c["from_mark"], c["to_mark"], c["change_points"], c["principal"], c["from_principal"]),
                         (70.5, 31.6, -38.9, 2500.0, 1000.0))

    def test_two_loans_paired_by_cusip(self):
        holdings = [self.loan("F", "2025-07-31", 10.0, 90.0, "TL"), self.loan("F", "2025-07-31", 5.0, 95.0, "RV"),
                    self.loan("F", "2026-07-31", 10.0, 30.0, "TL"), self.loan("F", "2026-07-31", 5.0, 60.0, "RV")]
        got = sorted((c["from_mark"], c["to_mark"]) for c in mr.fund_mark_changes(holdings))
        self.assertEqual(got, [(90.0, 30.0), (95.0, 60.0)])

    def test_nport_distress_flags(self):
        doc = fixture("nport.xml").replace("<isPaidKind>N</isPaidKind>", "<isPaidKind>Y</isPaidKind>", 1)
        rows = mr.parse_nport_holdings(doc, ["Mitnick"])
        self.assertEqual(rows[0]["fund_flags"], ["paid in kind"])
        self.assertNotIn("fund_flags", mr.parse_nport_holdings(fixture("nport.xml"), ["Mitnick"])[0])

    def test_covered_alias_note_names_the_phrase(self):
        out, saved = [], mr.emit
        mr.emit = out.append
        try:
            mr.skip_covered(["Mitnick Corp"], ["Mitnick"])
        finally:
            mr.emit = saved
        self.assertIn('"Mitnick"', out[0]["note"])

    def test_none_then_bullets_is_no_red_flags(self):
        md = "## Red flags\n\nNone.\n\n- No crowdfunding round failed, because none was found.\n\n## Facts\n"
        self.assertEqual(mr.parse_red_flags(md), [])

    def test_bad_form_name_falls_back_to_each_form(self):
        calls, saved = [], mr.fetch

        def fake(url, ua):
            forms = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("forms", [""])[0]
            calls.append(forms)
            total = 38 if forms == "DEF 14A" else 0
            hits = [{"_id": "0001-26-000001:p.htm", "_source": {"ciks": ["876167"], "form": "DEF 14A",
                                                                 "file_date": "2026-03-01"}}] if total else []
            return json.dumps({"hits": {"total": {"value": total}, "hits": hits}})
        mr.fetch = fake
        try:
            hits, summary = mr.edgar_search("Veracode", ["DEF 14A", "SC 13D"], None, None, "ua", 1)
        finally:
            mr.fetch = saved
        self.assertEqual(calls, ["DEF 14A,SC 13D", "DEF 14A", "SC 13D"])
        self.assertEqual((len(hits), summary["total"], summary["forms_with_no_hits"]), (1, 38, ["SC 13D"]))

    def test_cik_rejects_names(self):
        self.assertEqual(mr.cik10("CIK1358559"), "0001358559")
        with self.assertRaisesRegex(mr.FetchError, "edgar-search"):
            mr.cik10("3M Company")

    def test_no_charges_is_reported(self):
        profile = {"company_name": "X LTD", "company_number": "07217991", "type": "ltd", "links": {}}

        class FakeCH:
            def get(self, path):
                return profile if path == "/company/07217991" else None
        out = list(mr.ch_report("07217991", FakeCH(), today=mr.dt.date(2026, 11, 22)))
        self.assertEqual([r["count"] for r in out if r["type"] == "ch_charges"], [0])

    def test_owed_by_named_parent_is_a_group_balance(self):
        doc = "<p>At the year end, £3,240,355 (2024 - £2,572,241) was owed to the Company by Veracode Inc.</p>"
        self.assertIn("3,240,355", mr.extract_notes(doc)["group_balances"][0])


class SnykRunTwoFixes(unittest.TestCase):
    def test_scale_halves_page_and_keeps_thin_strokes(self):
        # 4x2 page: one black pixel at (1, 1) survives a 2x shrink as pixel (0, 0)
        png = mr.png_1bit([[], [1, 2]], 4, 2, scale=2)
        w, h = mr.struct.unpack(">II", png[16:24])
        self.assertEqual((w, h), (2, 1))
        rows = mr.zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
        self.assertEqual(rows, b"\x00\x7f")  # filter byte, then 0 (black) and 1 (white) in the top two bits

    def test_scanned_accounts_record_and_dates(self):
        filings = {"items": [
            {"type": "AAMD", "date": "2022-02-04", "transaction_id": "t0", "links": {"document_metadata": "m0"},
             "description_values": {"made_up_date": "2020-12-31"}},
            {"type": "AA", "date": "2022-01-10", "transaction_id": "t1", "links": {"document_metadata": "m1"},
             "description_values": {"made_up_date": "2020-12-31"}},
            {"type": "AA", "date": "2019-09-30", "transaction_id": "t2", "links": {"document_metadata": "m2"},
             "description_values": {"made_up_date": "2018-12-31"}}]}

        class FakeCH:
            def get(self, path):
                return filings

            def metadata(self, url):
                return {"pages": 63, "resources": {"application/pdf": {}}} if url != "m2" \
                    else {"resources": {"application/xhtml+xml": {}}}

            def document(self, url, accept):
                return fixture("uk_accounts.xhtml")
        out = list(mr.uk_accounts("09677925", FakeCH()))
        scans = [r for r in out if r["type"] == "uk_accounts_scanned"]
        self.assertEqual([r["pages"] for r in scans], [63, 63])
        self.assertIn("uk-pages", scans[0]["note"])
        latest = next(r for r in out if r["type"] == "uk_accounts_latest_scanned")
        self.assertEqual(latest["scanned_made_up_dates"], ["2020-12-31"])

    def test_gleif_drops_loose_matches(self):
        def rec(lei, name):
            return {"id": lei, "attributes": {"lei": lei, "entity": {"legalName": {"name": name}, "jurisdiction": "US",
                                                                       "legalAddress": {}, "status": "ACTIVE"},
                                              "registration": {"status": "ISSUED"}}}
        data = {"data": [rec("A" * 20, "SNYK LIMITED"), rec("B" * 20, "PotNetwork Holdings, Inc."),
                         rec("C" * 20, "Rafferty Subaru Inc")]}
        out = list(mr.gleif_search("Snyk, Inc.", 10, fetcher=lambda path: json.dumps(data)))
        self.assertEqual([r["legal_name"] for r in out], ["SNYK LIMITED"])
        none = list(mr.gleif_search("Snyk Switzerland AG", 10, fetcher=lambda path: json.dumps({"data": data["data"][1:]})))
        self.assertEqual(none[0]["type"], "gleif_no_match")
        self.assertIn("2 loose matches", none[0]["note"])

    def test_gleif_search_by_registration_number(self):
        seen = []
        rec = {"id": "D" * 20, "attributes": {"lei": "D" * 20, "entity": {
            "legalName": {"name": "Van Luijt Holding B.V."}, "jurisdiction": "NL", "registeredAs": "60994800",
            "legalAddress": {}, "status": "ACTIVE"}, "registration": {"status": "ISSUED"}}}

        def fetcher(path):
            seen.append(path)
            return json.dumps({"data": [rec]})
        out = list(mr.gleif_search(None, 10, fetcher=fetcher, registered_as="60994800"))
        self.assertIn("filter%5Bentity.registeredAs%5D=60994800", seen[0])
        self.assertEqual(out[0]["registered_as"], "60994800")
        none = list(mr.gleif_search(None, 10, fetcher=lambda path: json.dumps({"data": []}), registered_as="75231824"))
        self.assertEqual(none[0]["type"], "gleif_no_match")
        self.assertEqual(none[0]["query"], "75231824")

    def test_profile_charges_mismatch(self):
        profile = {"company_name": "X LTD", "company_number": "09677925", "type": "ltd", "has_charges": False,
                   "links": {}}
        charges = {"items": [{"status": "outstanding", "persons_entitled": [{"name": "J.P. Morgan"}]}]}

        class FakeCH:
            def get(self, path):
                return profile if path == "/company/09677925" else charges if "/charges" in path else None
        out = list(mr.ch_report("09677925", FakeCH(), today=mr.dt.date(2026, 11, 22)))
        mismatch = [r for r in out if r["type"] == "ch_profile_mismatch"]
        self.assertEqual([(r["field"], r["register_count"]) for r in mismatch], [("has_charges", 1)])

    def test_run_folder_skips_files_without_source_line(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("press.md", "SOURCE: Press\nSTATUS: FOUND\n"), ("entity.md", "# Entity\n"),
                               ("dossier.md", "SOURCE: x\n")):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(text)
            self.assertEqual([os.path.basename(x) for x in mr.report_paths([d])], ["press.md"])

    def test_mark_change_says_how_lines_were_paired(self):
        def line(as_of, shares, value):
            return {"filer": "T", "cik": "1", "fund": "F", "as_of": as_of, "name": "SNYK", "balance": shares,
                    "url": as_of, "value_per_share": value}
        [c] = mr.fund_mark_changes([line("2025-06-30", 10.0, 5.0), line("2026-06-30", 10.0, 2.0)])
        self.assertEqual(c["paired_by"], "share_count")
        [c] = mr.fund_mark_changes([line("2025-06-30", 10.0, 5.0), line("2026-06-30", 12.0, 2.0)])
        self.assertEqual(c["paired_by"], "only_line")

    def test_mark_change_lists_the_quarters_between(self):
        def line(as_of, value):
            return {"filer": "T", "cik": "1", "fund": "F", "as_of": as_of, "name": "AIVEN", "balance": 10.0,
                    "url": as_of, "value_per_share": value}
        [c] = mr.fund_mark_changes([line("2025-06-30", 50.65), line("2026-03-31", 50.0), line("2026-06-30", 12.2)])
        self.assertEqual([p["value"] for p in c["path"]], [50.65, 50.0, 12.2])
        [c] = mr.fund_mark_changes([line("2025-06-30", 50.65), line("2026-06-30", 12.2)])
        self.assertNotIn("path", c)


def tiny_text_pdf():
    """A one-page PDF like Companies House's electronic forms: a subset font whose
    two-byte glyph codes only make sense through its ToUnicode map, one glyph per Td."""
    cmap = (b"begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange "
            b"2 beginbfchar <0001> <0053> <0002> <0048> endbfchar "
            b"1 beginbfrange <0003> <0004> <0030> endbfrange endcmap")
    content = mr.zlib.compress(b"BT /F1 12 Tf 0 0 Td <0001> Tj 8 0 Td <0002> Tj 8 0 Td [<0003> -500 <0004>] TJ "
                               b"0 -14 Td <0002> Tj ET")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type0 /ToUnicode 6 0 R >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream"]
    return b"%PDF-1.7\n" + b"".join(b"%d 0 obj\n" % (i + 1) + o + b"\nendobj\n" for i, o in enumerate(objs))


class AikidoRunFixes(unittest.TestCase):
    def test_pdf_text_through_tounicode(self):
        blocks = mr.pdf_text(tiny_text_pdf())
        self.assertEqual(blocks, ["SH0 1\nH"])

    def test_pdf_text_records_and_scan(self):
        [r] = mr.pdf_text_records(tiny_text_pdf(), "f.pdf")
        self.assertEqual(r["type"], "pdf_text")
        [r] = mr.pdf_text_records(b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj", "scan.pdf")
        self.assertEqual(r["type"], "pdf_no_text")

    def test_pdf_decompression_total_is_capped(self):
        # many small streams that each inflate well under the per-stream cap
        bomb = mr.zlib.compress(b"\0" * 1_000_000)
        objs = b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % i + bomb + b"\nendstream\nendobj\n"
                        for i in range(1, 30))
        saved = mr.MAX_PDF_DECODED
        mr.MAX_PDF_DECODED = 10_000_000
        try:
            with self.assertRaises(ValueError):
                mr.pdf_text(b"%PDF-1.7\n" + objs)
        finally:
            mr.MAX_PDF_DECODED = saved

    def test_long_digit_run_tokenizes_quickly(self):
        start = mr.time.monotonic()
        mr.pdf_content_text(b"BT " + b"1" * 200000 + b" ET")
        self.assertLess(mr.time.monotonic() - start, 2)

    def test_uk_pages_points_to_pdf_text(self):
        with tempfile.TemporaryDirectory() as d:
            out = list(mr.page_images(tiny_text_pdf(), d))
        self.assertIn("pdf-text", out[-1]["note"])

    def test_skip_seen_covers_only_from_searched_aliases(self):
        # round 1 skipped "Aikido Security" (covered by "Aikido"), so round 2 must name "Aikido"
        out, saved = [], (mr.edgar_search, mr.emit)
        mr.edgar_search = lambda *a: ([], {"type": "search_summary", "truncated": False})
        mr.emit = out.append
        try:
            mr.marks(["Aikido Security", "Aikido"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.emit = saved
        search = next(r for r in out if r["type"] == "marks_search")
        self.assertEqual(search["searched"], ["Aikido"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "marks.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(search) + chr(10))
            self.assertEqual(mr.covering_alias("Aikido Security Corp", mr.load_searched(path)), "Aikido")

def bodacc_notice(family, date, **fields):
    return {"id": "X" + date, "dateparution": date, "familleavis": family,
            **{k: json.dumps(v) if isinstance(v, dict) else v for k, v in fields.items()}}


def capital_person(amount, administration=None):
    p = {"personne": {"capital": {"montantCapital": amount, "devise": "EUR"}}}
    if administration:
        p["personne"]["administration"] = administration
    return p


class FranceRunFixes(unittest.TestCase):
    def fr(self, notices, finances=None, today=dt.date(2026, 11, 22)):
        company = {"siren": "123456789", "nom_complet": "ACME", "etat_administratif": "A",
                   "date_creation": "2017-11-20", "finances": finances,
                   "dirigeants": [{"nom": "DUPONT", "prenoms": "JEAN", "qualite": "Président de SAS"}]}

        def fetcher(url):
            if url.startswith(mr.FR_SEARCH):
                return json.dumps({"results": [company]})
            return json.dumps({"total_count": len(notices), "results": notices})
        return list(mr.fr_report("123456789", fetcher, today))

    def test_missing_accounts_years_are_flagged(self):
        dpc = {"dateCloture": "2019-12-31", "typeDepot": "Comptes annuels et rapports",
               "descriptif": "déclaration de confidentialité ... article L. 232-25."}
        out = self.fr([bodacc_notice("dpc", "2020-10-01", depot=dpc)])
        filed = next(r for r in out if r["type"] == "fr_accounts_filed")
        self.assertTrue(filed["confidential"])
        gaps = [r["year_end"] for r in out if r["type"] == "fr_flag"]
        self.assertEqual(gaps, ["2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"])

    def test_year_not_yet_due_is_not_flagged(self):
        dpc = {"dateCloture": "2024-12-31", "typeDepot": "Comptes annuels"}
        out = self.fr([bodacc_notice("dpc", "2025-07-01", depot=dpc)], today=dt.date(2026, 8, 1))
        self.assertFalse([r for r in out if r["type"] == "fr_flag"])

    def test_unpublished_finances_said_explicitly(self):
        out = self.fr([])
        fin = next(r for r in out if r["type"] == "fr_finances")
        self.assertFalse(fin["published"])
        self.assertIn("L. 232-25", fin["note"])
        self.assertEqual(next(r for r in out if r["type"] == "fr_officer")["name"], "JEAN DUPONT")

    def test_capital_and_officer_changes(self):
        out = self.fr([
            bodacc_notice("modification", "2022-04-28", modificationsgenerales={"descriptif": "modification survenue sur le capital (augmentation)"},
                          listepersonnes=capital_person("2523.61")),
            bodacc_notice("modification", "2023-03-30", modificationsgenerales={"descriptif": "modification survenue sur le capital (diminution)"},
                          listepersonnes=capital_person("2389.51")),
            # filed the same day, still showing the old capital
            bodacc_notice("modification", "2023-03-30", modificationsgenerales={"descriptif": "modification survenue sur l'administration"},
                          listepersonnes=capital_person("2523.61", "Directeur général partant : Thomas")),
            bodacc_notice("modification", "2024-04-14", modificationsgenerales={"descriptif": "modification survenue sur le capital (augmentation)"},
                          listepersonnes=capital_person("2391.39")),
        ])
        caps = [(r["direction"], r["previous_capital_eur"], r["capital_eur"]) for r in out if r["type"] == "fr_capital"]
        self.assertEqual(caps, [("increase", None, 2523.61), ("reduction", 2523.61, 2389.51), ("increase", 2389.51, 2391.39)])
        self.assertEqual(next(r for r in out if r["type"] == "fr_officer_change")["quote"], "Directeur général partant : Thomas")

    def test_insolvency_notice(self):
        j = {"nature": "Jugement d'ouverture de liquidation judiciaire", "date": "2026-11-05", "complementJugement": "..."}
        out = self.fr([bodacc_notice("collective", "2026-11-20", jugement=j, tribunal="Greffe de Sedan")])
        r = next(r for r in out if r["type"] == "fr_insolvency")
        self.assertEqual((r["nature"], r["judgment_date"]), (j["nature"], "2026-11-05"))

    def test_quote_check_matches_escaped_json(self):
        inner = json.dumps({"personne": {"administration": "Directeur général partant : Thomas"}})
        body = json.dumps({"results": [{"listepersonnes": inner}]})  # ensure_ascii: \\u00e9 twice over
        self.assertIn("\\\\u00e9", body)
        page = mr.searchable_text(body).lower()
        self.assertGreaterEqual(mr.find_quote(page, "Directeur général partant : Thomas")[0], 0)



def fake_ch(api):
    def fake(url, accept=None):
        path = url[len(mr.CH_API):].split("?")[0]
        if path in api:
            return json.dumps(api[path])
        raise mr.FetchError(f"HTTP 404 for {url}")
    return mr.CompaniesHouse(None, fetcher=fake)


OVERSEAS = {"company_name": "N8N GMBH", "company_status": "active", "type": "oversea-company",
            "date_of_creation": "2025-05-01", "accounts": {"next_made_up_to": "2026-05-31"},
            "foreign_company_details": {"accounting_requirement": {
                "foreign_account_type": "accounting-requirements-of-originating-country-do-not-apply"}}}


class GermanyRunFixes(unittest.TestCase):
    def test_overseas_establishment_and_late_registration(self):
        ch = fake_ch({"/company/FC043684": OVERSEAS,
                      "/company/FC043684/uk-establishments": {"items": [
                          {"company_number": "BR028805", "company_name": "N8N GMBH - UK ESTABLISHMENT",
                           "company_status": "open", "locality": "London"}]},
                      "/company/FC043684/filing-history": {"total_count": 1, "items": [
                          {"type": "OSIN01", "date": "2026-10-29", "transaction_id": "t1",
                           "description": "register-overseas-company"}]}})
        out = list(mr.ch_report("FC043684", ch, today=dt.date(2026, 11, 22)))
        self.assertEqual(next(r for r in out if r["type"] == "ch_uk_establishment")["branch_number"], "BR028805")
        flag = next(r for r in out if r.get("flag") == "late overseas registration")
        self.assertEqual((flag["severity"], flag["days_late"]), ("minor", 515))
        self.assertEqual(out[-1]["minor_late_filings"], 1)

    def test_overseas_registered_in_time_is_not_flagged(self):
        ch = fake_ch({"/company/FC043684": OVERSEAS, "/company/FC043684/filing-history": {"total_count": 1, "items": [
            {"type": "OSIN01", "date": "2025-05-20", "transaction_id": "t1"}]}})
        out = list(mr.ch_report("FC043684", ch, today=dt.date(2026, 11, 22)))
        self.assertFalse([r for r in out if r["type"] == "ch_flag"])

    def test_overseas_no_accounts_note(self):
        ch = fake_ch({"/company/FC043684": OVERSEAS, "/company/FC043684/filing-history": {"items": []}})
        [r] = mr.uk_accounts("FC043684", ch)
        self.assertIn("13 months", r["note"])
        self.assertNotIn("21 months", r["note"])
        published = dict(OVERSEAS, foreign_company_details={"accounting_requirement": {
            "foreign_account_type": "accounting-requirements-of-originating-country-apply"}})
        self.assertIn("3 months of their publication", mr.uk_no_accounts_note(published))
        self.assertIn("21 months", mr.uk_no_accounts_note({"type": "ltd"}))

    def test_ch_search(self):
        ch = fake_ch({"/search/companies": {"items": [
            {"company_number": "FC043684", "title": "N8N GMBH", "company_type": "oversea-company"}]}})
        out = list(mr.ch_search("n8n", ch))
        self.assertEqual((out[0]["company_number"], out[0]["company_type"]), ("FC043684", "oversea-company"))
        self.assertEqual(out[-1]["results"], 1)


class IrelandRunFixes(unittest.TestCase):
    def ie(self, company, filings, today=dt.date(2026, 11, 22)):
        def fetcher(url):
            if "package_show" in url:
                return json.dumps({"result": {"resources": [
                    {"id": "fs2024", "name": "Financial Statements 2024", "datastore_active": True}]}})
            params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            records = [company] if params["resource_id"][0] == mr.CRO_COMPANIES else filings
            return json.dumps({"result": {"records": records}})
        return list(mr.ie_report("621010", fetcher, today))

    COMPANY = {"company_num": 621010, "company_name": "Tines LIMITED", "company_status": "Normal ",
               "last_ar_date": "2025-09-30T00:00:00", "nard": "2026-09-30T00:00:00"}

    def test_late_return_is_flagged(self):
        late = {"submission_rec_date": "2026-05-28T00:00:00", "submission_eff_date": "2025-09-30T00:00:00",
                "submissions_accounts_to_date": "2025-01-31T00:00:00"}
        on_time = {"submission_rec_date": "2024-11-19T00:00:00", "submission_eff_date": "2024-09-30T00:00:00",
                   "submissions_accounts_to_date": "2024-01-31T00:00:00"}
        out = self.ie(self.COMPANY, [on_time, late])
        flags = [r for r in out if r["type"] == "ie_flag"]
        self.assertEqual([(f["flag"], f["accounts_to"], f["days_late"]) for f in flags],
                         [("late annual return", "2025-01-31", 184)])
        self.assertEqual(out[0]["status"], "Normal")

    def test_overdue_return_and_stale_dataset_note(self):
        overdue = dict(self.COMPANY, last_ar_date="2024-09-30T00:00:00", nard="2025-09-30T00:00:00")
        out = self.ie(overdue, [])
        self.assertEqual(next(r for r in out if r["type"] == "ie_flag")["flag"], "annual return overdue")
        self.assertIn("newer than the latest filing", out[-1]["note"])
        not_yet = self.ie(self.COMPANY, [])  # next return date 2026-09-30, due 2026-11-25
        self.assertFalse([r for r in not_yet if r["type"] == "ie_flag"])

    def test_name_search_escapes_quotes(self):
        seen = []

        def fetcher(url):
            seen.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["sql"][0])
            return json.dumps({"result": {"records": [{"company_num": "1", "company_name": "O'BRIEN LTD"}]}})
        out = list(mr.ie_report("O'Brien%", fetcher))
        self.assertIn("ILIKE 'O''Brien%'", seen[0])
        self.assertEqual(out[0]["type"], "ie_candidate")

    def test_read_timeout_becomes_fetch_error(self):
        def urlopen(request, timeout):
            raise TimeoutError("The read operation timed out")
        original, mr.urllib.request.urlopen = mr.urllib.request.urlopen, urlopen
        out, saved, sleep = [], mr.emit, mr.time.sleep
        mr.emit, mr.time.sleep = out.append, lambda s: None
        try:
            with self.assertRaises(mr.FetchError):
                mr.fetch("https://www.businesswire.com/x", None, retries=0)
            mr.quote_check("https://www.businesswire.com/x", "anything", None, 50)
        finally:
            mr.urllib.request.urlopen, mr.emit, mr.time.sleep = original, saved, sleep
        self.assertIsNone(out[0]["found"])
        self.assertIn("TimeoutError", out[0]["unreachable"])

    def test_lapsed_lei_is_noted(self):
        rec = {"attributes": {"lei": "L1", "entity": {"legalName": {"name": "OLD NAME LTD"}, "jurisdiction": "IE"},
                              "registration": {"status": "LAPSED", "lastUpdateDate": "2026-10-26"}}}

        def get(url):
            path = url[len(mr.GLEIF):].split("?")[0]
            if path == "/lei-records/L1":
                return json.dumps({"data": rec})
            raise mr.FetchError(f"HTTP 404 for {url}")
        out = list(mr.gleif_report("L1", fetcher=get))
        self.assertEqual(next(r for r in out if r["type"] == "gleif_lapsed")["legal_name"], "OLD NAME LTD")

    def test_psc_statement_against_named_parent(self):
        ch = fake_ch({"/company/16441456/persons-with-significant-control-statements": {"items": [
            {"statement": "no-individual-or-entity-with-signficant-control", "notified_on": "2025-05-08"}]}})
        [r] = mr.psc_parent_mismatch("16441456", ch, ["The immediate parent undertaking is Tines Limited."])
        self.assertEqual(r["severity"], "minor")
        ceased = fake_ch({"/company/1/persons-with-significant-control-statements": {"items": [
            {"statement": "no-individual-or-entity-with-signficant-control", "ceased_on": "2025-06-01"}]}})
        self.assertEqual(list(mr.psc_parent_mismatch("1", ceased, ["parent"])), [])


def tiny_xlsx(rows):
    """An .xlsx with one sheet of inline-number and shared-string cells."""
    import zipfile
    strings, sheet = [], []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in zip("ABCDEFGH", row):
            if isinstance(value, int):
                cells.append(f'<c r="{c}{r}"><v>{value}</v></c>')
            else:
                strings.append(value)
                cells.append(f'<c r="{c}{r}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{x}</t></si>" for x in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(sheet)}</sheetData></worksheet>")
    return buf.getvalue()


class OfficersLayoffsHiring(unittest.TestCase):
    def officers_api(self, appointments, disqualified=()):
        return {
            "/company/01234567/officers": {"items": [
                {"name": "DOE, Jane", "officer_role": "director", "date_of_birth": {"month": 6, "year": 1980},
                 "links": {"officer": {"appointments": "/officers/abc/appointments"}}},
                {"name": "ACME SECRETARIES LTD", "officer_role": "corporate-secretary",
                 "links": {"officer": {"appointments": "/officers/sec/appointments"}}}]},
            "/officers/abc/appointments": {"total_results": len(appointments), "items": appointments},
            "/company/09999999": {"has_insolvency_history": True},
            "/company/09999999/insolvency": {"cases": [{"type": "compulsory-liquidation"}]},
            "/company/02222222/insolvency": {"cases": [{"type": "creditors-voluntary-liquidation"}]},
            "/company/04444444": {"has_insolvency_history": True},
            "/company/04444444/insolvency": {"cases": [{"type": "members-voluntary-liquidation"}]},
            "/search/disqualified-officers": {"items": list(disqualified)},
        }

    @staticmethod
    def appt(number, status):
        return {"appointed_to": {"company_number": number, "company_name": f"CO {number}", "company_status": status},
                "officer_role": "director", "appointed_on": "2015-01-01"}

    def test_phoenix_pattern_and_privacy(self):
        api = self.officers_api([self.appt("01234567", "active"), self.appt("02222222", "liquidation"),
                                 self.appt("09999999", "dissolved"), self.appt("03333333", "active"),
                                 self.appt("04444444", "dissolved")])  # a solvent members' liquidation
        out = list(mr.ch_officers("01234567", fake_ch(api)))
        bad = [r["company_number"] for r in out if r["type"] == "ch_officer_insolvent_company"]
        self.assertEqual(bad, ["02222222", "09999999"])  # the dissolved one had an insolvency
        flag = next(r for r in out if r["type"] == "ch_flag")
        self.assertEqual((flag["flag"], flag["severity"]), ("director of insolvent companies", "major"))
        self.assertEqual(out[-1]["directors"], 1)  # the corporate secretary is skipped
        self.assertNotIn("date_of_birth", json.dumps(out))

    def test_one_insolvency_is_minor_and_disqualification_needs_birth_month(self):
        same = {"title": "Jane DOE", "date_of_birth": "1980-06-03T00:00:00", "description": "Born on 3 June 1980 - Disqualified",
                "links": {"self": "/disqualified-officers/natural/x"}}
        other = dict(same, date_of_birth="1975-02-01T00:00:00")
        api = self.officers_api([self.appt("02222222", "administration")], [other, same])
        flags = [r for r in mr.ch_officers("01234567", fake_ch(api)) if r["type"] == "ch_flag"]
        self.assertEqual([(f["flag"], f["severity"]) for f in flags],
                         [("director of an insolvent company", "minor"), ("disqualified director", "major")])

    def test_warn_california_and_texas(self):
        xlsx = tiny_xlsx([["WARN REPORT"],
                          ["County/Parish", "Notice\nDate", "Processed\nDate", "Effective \nDate", "Company",
                           "Layoff/\nClosure", "No. Of\nEmployees", "Address"],
                          ["San Mateo County", 46199, 46204, 46232, "Acme Robotics, Inc.", "Layoff Permanent", "103", "1 Way"],
                          ["Los Angeles County", 46203, 46204, 46266, "Acme Bakery", "Closure Permanent", "2", "2 St"]])
        tx = [{"job_site_name": "ACME ROBOTICS INC", "notice_date": "2026-06-23T00:00:00.000",
               "layoff_date": "2026-08-21T00:00:00.000", "total_layoff_number": "40", "city_name": "Austin"}]
        out = list(mr.warn_report("Acme Robotics Inc", lambda u: xlsx if u == mr.CA_WARN else json.dumps(tx).encode()))
        notices = [(r["state"], r["company"], r["notice_date"], r["employees"]) for r in out if r["type"] == "warn_notice"]
        self.assertEqual(notices, [("CA", "Acme Robotics, Inc.", "2026-06-26", 103), ("TX", "ACME ROBOTICS INC", "2026-06-23", 40)])
        self.assertEqual(len(out[-1]["states_searched"]), 2)

    def test_us_states_open_registers(self):
        rows = {
            "colorado": [{"entityid": "2021", "entityname": "Acme Robotics, Inc., Delinquent June 1, 2024", "entitystatus": "Delinquent",
                          "jurisdictonofformation": "DE", "entityformdate": "2021-09-15T00:00:00.000"}],
            "texas": [{"taxpayer_name": "ACME ROBOTICS INC", "taxpayer_number": "32", "right_to_transact_business_code": "U"}],
            "oregon": [{"registry_number": "187", "business_name": "ACME ROBOTICS INC", "jurisdiction": "DE",
                        "associated_name_type": "PRINCIPAL PLACE OF BUSINESS", "city": "BOSTON", "state": "MA"},
                       {"registry_number": "187", "business_name": "ACME ROBOTICS INC",
                        "associated_name_type": "REGISTERED AGENT", "entity_of_record_name": "CSC"}],
            "ct": [],
        }
        urls = []

        def get(url):
            urls.append(url)
            if "data.ny.gov" in url:
                raise mr.FetchError("HTTP 503")
            return json.dumps(next(v for k, v in rows.items() if k in url)).encode()
        out = list(mr.us_states_report(["Acme Robotics", "O'Neil Labs"], fetcher=get))
        ents = {r["state"]: r for r in out if r["type"] == "us_state_entity"}
        self.assertEqual((ents["CO"]["name"], ents["CO"]["status"]), ("Acme Robotics, Inc.", "Delinquent"))
        self.assertEqual(ents["CO"]["formed_in"], "DE")
        self.assertEqual(ents["TX"]["status"], "not established")
        self.assertEqual([(r["state"], r["severity"]) for r in out if r["type"] == "us_state_flag"], [("CO", "minor")])
        self.assertEqual((ents["OR"]["address"], ents["OR"]["agent"]), ("BOSTON, MA", "CSC"))
        self.assertEqual(sum(r["type"] == "us_state_entity" and r["state"] == "OR" for r in out), 1)
        self.assertEqual([r["state"] for r in out if r["type"] == "us_state_unavailable"], ["NY"])
        self.assertIn("O%27%27NEIL+LABS%25", urls[0])
        self.assertEqual([s["state"] for s in out[-1]["searched"]], ["CO", "TX", "OR", "CT"])

    def test_usaspending_filters_loose_matches_and_totals_by_uei(self):
        calls = []

        def post(path, body):
            calls.append((path, body))
            if path == "/search/spending_over_time/":
                return {"results": [{"time_period": {"fiscal_year": "2025"}, "aggregated_amount": 900.0,
                                     "Contract_Obligations": 800.0, "Grant_Obligations": 100.0, "Loan_Obligations": 0},
                                    {"time_period": {"fiscal_year": "2026"}, "aggregated_amount": -300.0}]}
            if body["filters"]["award_type_codes"] == mr.USA_IDV_CODES:
                return {"results": [{"Award ID": "IDIQ1", "Recipient Name": "ACME ROBOTICS INC", "Start Date": "2025-12-29",
                                     "Awarding Sub Agency": "Missile Defense Agency", "generated_internal_id": "CONT_IDV_1"}]}
            group = body["filters"]["award_type_codes"]
            if group == ["A", "B", "C", "D"]:
                return {"results": [
                    {"Award ID": "W1", "Recipient Name": "ACME ROBOTICS INC", "Recipient UEI": "U1", "Award Amount": 750.0,
                     "Awarding Agency": "Department of Defense", "generated_internal_id": "CONT_AWD_W1", "recipient_id": "r1-C"},
                    {"Award ID": "W2", "Recipient Name": "ACMEROBOT HOLDINGS", "Recipient UEI": "U9", "Award Amount": 5.0,
                     "generated_internal_id": "CONT_AWD_W2"}],
                    "page_metadata": {"hasNext": True}}
            if group == ["07", "08"]:
                return {"results": [{"Award ID": "L1", "Recipient Name": "Acme Robotics, Inc.", "Recipient UEI": None,
                                     "Loan Value": 150000.0, "Subsidy Cost": 1000.0, "Issued Date": "2020-05-01",
                                     "Awarding Agency": "Small Business Administration",
                                     "generated_internal_id": "ASST_NON_L1"}]}
            if group == ["02", "03", "04", "05"]:
                raise mr.FetchError("HTTP 503")
            return {"results": []}
        out = list(mr.usaspending_report(["Acme Robotics"], poster=post, today=dt.date(2026, 11, 24)))
        loan_call = next(b for p, b in calls if b.get("filters", {}).get("award_type_codes") == ["07", "08"])
        self.assertEqual(loan_call["filters"]["time_period"][0]["start_date"], "2020-04-01")
        self.assertEqual(out[-1]["no_uei"], ["Acme Robotics, Inc."])
        self.assertIn("Other Transaction", out[-1]["note"])
        awards = [r for r in out if r["type"] == "usa_award"]
        self.assertEqual([a["award_id"] for a in awards], ["W1", "L1"])
        self.assertEqual(awards[0]["url"], "https://www.usaspending.gov/award/CONT_AWD_W1")
        self.assertEqual((awards[1]["group"], awards[1]["amount"], awards[1]["issued"]), ("loans", 150000.0, "2020-05-01"))
        self.assertEqual([r["group"] for r in out if r["type"] == "usa_unavailable"], ["grants"])
        self.assertEqual(calls[-1][1]["filters"]["recipient_search_text"], ["U1"])
        self.assertEqual(calls[0][1]["filters"]["time_period"][0]["start_date"], "2021-11-25")
        year = next(r for r in out if r["type"] == "usa_year")
        self.assertEqual((year["fiscal_year"], year["contract"], year["grant"]), (2025, 800.0, 100.0))
        summary = out[-1]
        self.assertEqual(summary["agencies"], [{"agency": "Department of Defense", "share": 1.0}])
        self.assertEqual(summary["other_recipients"], ["ACMEROBOT HOLDINGS"])
        self.assertEqual(summary["truncated"], [{"query": "Acme Robotics", "group": "contracts", "pages_read": 1}])
        self.assertEqual(summary["recipients"][0]["page"], "https://www.usaspending.gov/recipient/r1-C/latest")
        self.assertEqual(next(r for r in out if r["type"] == "usa_vehicles")["vehicles"][0]["award_id"], "IDIQ1")
        self.assertEqual(next(r for r in out if r["type"] == "usa_flag")["fiscal_year"], 2026)

    def test_csl_matches_names_and_aliases(self):
        rows = [
            {"source": "Entity List (EL) - Bureau of Industry and Security", "name": "Acme Robotics Co., Ltd.",
             "type": "Entity", "addresses": "Shenzhen, CN", "alt_names": "", "start_date": "2024-05-01"},
            {"source": "Specially Designated Nationals (SDN) - Treasury Department", "name": "Volga Trading LLC",
             "type": "Entity", "alt_names": "ACME ROBOTICS FZE; Volga Trade", "programs": "RUSSIA-EO14024"},
            {"source": "Specially Designated Nationals (SDN) - Treasury Department", "name": "Acme Shipping",
             "type": "Entity", "alt_names": ""},
            {"source": "Non-SDN Chinese Military-Industrial Complex Companies List (CMIC) - Treasury Department",
             "name": "Acme Robotics Holdings", "type": "Entity", "alt_names": "",
             "ids": "Target Type, Private Company; Listing Date (CMIC), 2021-06-03; Effective Date (CMIC), 2021-08-02"},
        ]
        buf = io.StringIO()
        import csv
        w = csv.DictWriter(buf, fieldnames=["source", "name", "type", "programs", "addresses", "alt_names", "start_date", "ids"])
        w.writeheader()
        w.writerows(rows)
        out = list(mr.csl_report(["Acme Robotics Inc"], fetcher=lambda u: buf.getvalue().encode()))
        matches = [r for r in out if r["type"] == "csl_match"]
        self.assertEqual([m["name"] for m in matches], ["Acme Robotics Co., Ltd.", "Volga Trading LLC", "Acme Robotics Holdings"])
        self.assertEqual(matches[2]["start_date"], "2021-06-03")
        self.assertEqual((matches[0]["entity_type"], matches[0]["start_date"]), ("Entity", "2024-05-01"))
        self.assertEqual(matches[1]["alt_names"], ["ACME ROBOTICS FZE", "Volga Trade"])
        self.assertEqual((out[-1]["entries_searched"], out[-1]["matches"]), (4, 3))

    FORM_D = """<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/formd">
  <primaryIssuer>
    <cik>0001900001</cik><entityName>Acme Robotics, Inc.</entityName>
    <issuerAddress><street1>1 Main St</street1><city>Boston</city><stateOrCountry>MA</stateOrCountry></issuerAddress>
    <jurisdictionOfInc>DELAWARE</jurisdictionOfInc>
    <issuerPreviousNameList><value>Acme Labs Inc.</value></issuerPreviousNameList>
    <edgarPreviousNameList><value>None</value></edgarPreviousNameList>
    <entityType>Corporation</entityType>
    <yearOfInc><withinFiveYears>true</withinFiveYears><value>2021</value></yearOfInc>
  </primaryIssuer>
  <relatedPersonsList>
    <relatedPersonInfo>
      <relatedPersonName><firstName>Jane</firstName><lastName>Doe</lastName></relatedPersonName>
      <relatedPersonAddress><street1>2 Home Rd</street1></relatedPersonAddress>
      <relatedPersonRelationshipList><relationship>Executive Officer</relationship><relationship>Director</relationship></relatedPersonRelationshipList>
      <relationshipClarification>CEO</relationshipClarification>
    </relatedPersonInfo>
  </relatedPersonsList>
  <offeringData>
    <industryGroup><industryGroupType>Other Technology</industryGroupType></industryGroup>
    <issuerSize><revenueRange>Decline to Disclose</revenueRange></issuerSize>
    <federalExemptionsExclusions><item>06b</item></federalExemptionsExclusions>
    <typeOfFiling><newOrAmendment><isAmendment>true</isAmendment></newOrAmendment><dateOfFirstSale><value>2023-03-01</value></dateOfFirstSale></typeOfFiling>
    <typesOfSecuritiesOffered><isEquityType>true</isEquityType><isOptionToAcquireType>false</isOptionToAcquireType></typesOfSecuritiesOffered>
    <offeringSalesAmounts><totalOfferingAmount>Indefinite</totalOfferingAmount><totalAmountSold>25000000</totalAmountSold><totalRemaining>Indefinite</totalRemaining><clarificationOfResponse>Includes $9.6m of SAFEs converted and cancelled.</clarificationOfResponse></offeringSalesAmounts>
    <investors><hasNonAccreditedInvestors>false</hasNonAccreditedInvestors><totalNumberAlreadyInvested>12</totalNumberAlreadyInvested></investors>
  </offeringData>
</edgarSubmission>"""

    def test_footprint_sets_aside_an_earlier_owners_captures(self):
        def get(url):
            if url == mr.RDAP_BOOTSTRAP:
                return json.dumps({"services": [[["com"], ["https://rdap.example/"]]]}).encode()
            if "rdap.example" in url:
                return json.dumps({"events": [{"eventAction": "registration", "eventDate": "2018-10-13T00:00:00Z"}]}).encode()
            return json.dumps([["timestamp", "statuscode"], ["20130601000000", "200"], ["20161007000000", "200"],
                               ["20190525000000", "200"]]).encode()
        out = {r["type"]: r for r in mr.footprint_report("acme.com", founded=2012, fetcher=get)}
        w = out["footprint_wayback"]
        self.assertEqual((w["first_capture"], w["prior_owner_captures"]["first"], w["prior_owner_captures"]["months"]),
                         ("2019-05-25", "2013-06-01", 2))
        self.assertEqual(out["footprint_flag"]["first_capture"], 2019)  # the 2013 captures no longer hide a padded claim

    def test_formd_parses_issuer_people_and_amounts(self):
        hits = [{"accession": "0001900001-24-000001", "cik": "0001900001", "form": "D/A", "filed": "2024-02-01",
                 "url": "https://www.sec.gov/Archives/edgar/data/1900001/000190000124000001/primary_doc.xml"},
                {"accession": "0001900001-24-000001", "form": "D/A", "filed": "2024-02-01",
                 "url": "https://www.sec.gov/Archives/edgar/data/1900001/000190000124000001/primary_doc.xml"},
                {"accession": "0001900001-23-000009", "cik": "0001900001", "form": "D", "filed": "2023-03-10",
                 "url": "https://www.sec.gov/Archives/edgar/data/1900001/000190000123000009/xslFormDX01/primary_doc.htm"}]
        got = []

        def get(url):
            got.append(url)
            return self.FORM_D
        out = list(mr.formd_report(["Jane Doe"], None, search=lambda q: (hits, {"total": 2, "truncated": False}), get=get))
        filings = [r for r in out if r["type"] == "formd_filing"]
        self.assertEqual(len(filings), 2)
        self.assertEqual(got[1], "https://www.sec.gov/Archives/edgar/data/1900001/000190000123000009/primary_doc.xml")
        f = filings[0]
        self.assertEqual((f["issuer"], f["jurisdiction"], f["year_of_inc"], f["address"]),
                         ("Acme Robotics, Inc.", "DELAWARE", "2021", "Boston, MA"))
        self.assertEqual(f["previous_names"], ["Acme Labs Inc."])
        self.assertEqual(f["related_persons"], [{"name": "Jane Doe", "relationships": ["Executive Officer", "Director"],
                                                 "clarification": "CEO"}])
        self.assertNotIn("Home Rd", json.dumps(f))
        self.assertEqual((f["total_sold"], f["total_offering"], f["investors"]), (25000000.0, "Indefinite", 12))
        self.assertEqual(f["sales_clarification"], "Includes $9.6m of SAFEs converted and cancelled.")
        self.assertEqual((f["amendment"], f["first_sale"], f["securities"], f["pooled_fund"]),
                         (True, "2023-03-01", ["Equity"], False))
        issuer = out[-1]["issuers"][0]
        self.assertEqual((issuer["filings"], issuer["first_filed"], issuer["last_filed"], issuer["people"]),
                         (2, "2023-03-10", "2024-02-01", ["Jane Doe"]))

    def test_formd_searches_form_d_family_and_names_vehicles(self):
        asked = []
        saved = mr.edgar_search
        mr.edgar_search = lambda q, forms, *a: asked.append(forms) or ([], {"total": 0, "truncated": False})
        try:
            out = list(mr.formd_report(["Hermeus"], "ua", get=lambda u: ""))
        finally:
            mr.edgar_search = saved
        self.assertEqual(asked, [["D"]])  # "D,D/A" returns only amendments
        self.assertIn("forms=D&", out[-1]["searched"][0]["url"] + "&")
        doc = self.FORM_D.replace("<entityName>Acme Robotics, Inc.</entityName>",
                                  "<entityName>Acme C a Series of What If Ventures Master LLC</entityName>").replace(
            "<relatedPersonName><firstName>Jane</firstName><lastName>Doe</lastName></relatedPersonName>",
            "<relatedPersonName><firstName>LLC</firstName><lastName>Sydecar</lastName></relatedPersonName>")
        d = mr.parse_form_d(doc)
        self.assertEqual((d["investor_vehicle"], d["pooled_fund"]), (True, False))
        self.assertEqual(d["related_persons"][0]["name"], "Sydecar, LLC")
        d = mr.parse_form_d(self.FORM_D.replace(
            "<firstName>Jane</firstName><lastName>Doe</lastName>",
            "<firstName>-</firstName><lastName>Fundamental Ventures Fund I GP, LLC</lastName>"))
        self.assertEqual(d["related_persons"][0]["name"], "Fundamental Ventures Fund I GP, LLC")
        self.assertFalse(mr.parse_form_d(self.FORM_D)["investor_vehicle"])

    def test_icij_keeps_name_matches_with_node_details(self):
        reply = {"q0": {"result": [
            {"id": "1", "name": "ACME ROBOTICS LIMITED", "description": "Entity node extracted from the Panama Papers data.",
             "types": [{"name": "Entity"}]},
            {"id": "2", "name": "ACME GARDENS, NASSAU", "types": [{"name": "Address"}]},
            {"id": "3", "name": "ROBOTICS HOLDINGS", "types": [{"name": "Entity"}]}]},
            "q1": {"result": [{"id": "1", "name": "ACME ROBOTICS LIMITED", "types": [{"name": "Entity"}]}]}}
        bodies = []
        out = list(mr.icij_report(["Acme Robotics", "Acme Robotics Ltd"], poster=lambda b: bodies.append(b) or reply,
                                  fetcher=lambda u: json.dumps({"properties": {"data_source": "Panama Papers",
                                                                               "country_codes": ["PA"],
                                                                               "incorporation_date": "2009-01-02"}}).encode()))
        nodes = [r for r in out if r["type"] == "icij_node"]
        self.assertEqual([(n["id"], n["query"]) for n in nodes], [("1", ["Acme Robotics", "Acme Robotics Ltd"])])
        self.assertEqual((nodes[0]["leak"], nodes[0]["countries"], nodes[0]["incorporated"]), ("Panama Papers", ["PA"], "2009-01-02"))
        self.assertEqual(out[-1]["loose_results_dropped"], 2)
        self.assertEqual(bodies[0]["queries"]["q1"]["query"], "Acme Robotics Ltd")
        self.assertNotIn("extra_words", nodes[0])
        out = list(mr.icij_report(["Sameer Rao"], poster=lambda b: {"q0": {"result": [
            {"id": "9", "name": "Vuppala Rao - Sameer", "types": [{"name": "Officer"}]}]}},
            fetcher=lambda u: b"{}"))
        self.assertEqual(out[0]["extra_words"], ["vuppala"])

    def test_footprint_rdap_wayback_github_and_whois_fallback(self):
        boot = {"services": [[["com"], ["https://rdap.example/com/v1/"]]]}

        def get(url):
            if url == mr.RDAP_BOOTSTRAP:
                return json.dumps(boot).encode()
            if url.startswith("https://rdap.example/com/v1/domain/acme.com"):
                return json.dumps({"events": [{"eventAction": "registration", "eventDate": "2019-04-01T00:00:00Z"}],
                                   "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Gandi"]]]}]}).encode()
            if "web.archive.org" in url:
                return json.dumps([["timestamp", "statuscode"], ["20190501000000", "200"], ["20190601000000", "301"],
                                   ["20240101000000", "200"]]).encode()
            if url.endswith("/orgs/acme"):
                return json.dumps({"name": "Acme", "created_at": "2019-05-01T00:00:00Z", "public_repos": 3}).encode()
            if "/orgs/acme/repos" in url:
                return json.dumps([{"name": "sdk", "pushed_at": "2026-10-01T00:00:00Z", "stargazers_count": 40},
                                   {"name": "old", "pushed_at": "2022-01-01T00:00:00Z", "stargazers_count": 5},
                                   {"name": "fork", "fork": True, "pushed_at": "2026-11-01T00:00:00Z", "stargazers_count": 900}]).encode()
            raise AssertionError(url)
        out = list(mr.footprint_report("https://www.acme.com/about", github="acme", founded=2010, fetcher=get,
                                       today=dt.date(2026, 11, 24)))
        by = {r["type"]: r for r in out}
        self.assertEqual((by["footprint_domain"]["registered"], by["footprint_domain"]["registrar"]), ("2019-04-01", "Gandi"))
        self.assertEqual(by["footprint_wayback"]["first_capture"], "2019-05-01")
        self.assertEqual(by["footprint_wayback"]["by_year"]["2019"], {"months": 2, "months_ok": 1})
        self.assertEqual((by["footprint_github"]["last_push"], by["footprint_github"]["repos_pushed_last_6_months"],
                          by["footprint_github"]["stars"]), ("2026-10-01", 1, 45))
        self.assertEqual(by["footprint_flag"]["founded"], 2010)
        self.assertNotIn("prior_owner_captures", by["footprint_wayback"])

        def whois(server, q):
            return {"whois.iana.org": "refer: whois.nic.io\nwhois:        whois.nic.io\n",
                    "whois.nic.io": "Domain Name: acme.io\nCreation Date: 2015-10-07T12:43:38Z\nRegistrar: Gandi SAS\n"}[server]
        out = list(mr.footprint_report("acme.io", founded=2014, fetcher=lambda u: json.dumps(boot).encode()
                                       if u == mr.RDAP_BOOTSTRAP else b"", whois=whois))
        d = next(r for r in out if r["type"] == "footprint_domain")
        self.assertEqual((d["registered"], d["registrar"], d["url"]), ("2015-10-07", "Gandi SAS", "whois://whois.nic.io/acme.io"))
        self.assertFalse(any(r["type"] == "footprint_flag" for r in out))

    def fi_fetcher(self, notices, situations=(), periods=()):
        company = {"companies": [{"businessId": {"value": "1234567-8", "registrationDate": "2016-11-18"},
                                  "names": [{"name": "Acme Oy", "type": "1"}, {"name": "Acme Ltd", "type": "2"}],
                                  "companyForms": [{"descriptions": [{"languageCode": "3", "description": "Limited company"}]}],
                                  "companySituations": list(situations), "status": "2",
                                  "registeredEntries": [{"register": "1", "type": "1",
                                                         "descriptions": [{"languageCode": "3", "description": "Registered"}]}]}]}

        def get(url):
            if "description?code=EC" in url:
                return b"TASE\t\tFINANCIAL STATEMENTS\nKOROI\t\tCAPITAL INCREASE\nHAL\t\tBOARD OF DIRECTORS\n"
            if "description?code=NRT" in url:
                return b"M\t\tAmendment notification\nTA\t\tFinancial statements\n"
            if "opendata-ytj-api" in url:
                return json.dumps(company).encode()
            if "opendata-xbrl-api" in url:
                return json.dumps({"financials": [{"financialDate": p} for p in periods]}).encode()
            return json.dumps({"publicNotices": notices}).encode()
        return get

    def test_fi_notices_deduplicated_and_late_accounts(self):
        tase = lambda d, n: {"registrationDate": d, "recordNumber": n, "typeOfRegistration": "TA", "entryCodes": ["TASE"]}
        notices = [tase("2018-08-09", "1"), tase("2019-09-19", "2"), tase("2021-01-15", "3"), tase("2022-08-10", "4"),
                   {"registrationDate": "2026-09-09", "recordNumber": "5", "typeOfRegistration": "M", "entryCodes": ["KOROI", "HAL"]},
                   {"registrationDate": "2026-09-09", "recordNumber": "5", "typeOfRegistration": "M", "entryCodes": ["KOROI", "HAL"]}]
        out = list(mr.fi_report("1234567-8", fy_end="03-31", fetcher=self.fi_fetcher(notices), today=dt.date(2024, 1, 10)))
        self.assertEqual(out[0]["other_names"], ["Acme Ltd"])
        kor = [r for r in out if r["type"] == "fi_notice" and r["record"] == "5"]
        self.assertEqual(len(kor), 1)
        self.assertEqual(kor[0]["entries"], ["KOROI (capital increase)", "HAL (board of directors)"])
        self.assertEqual(kor[0]["kind"], "Amendment notification")
        flags = [(r["flag"], r["period_end"]) for r in out if r["type"] == "fi_flag"]
        # FY 2020 registered 2021-01-15, after its 2020-11-30 deadline; nothing for FY 2021; FY 2023 was due 2023-11-30
        self.assertEqual(flags, [("late accounts", "2020-03-31"), ("accounts not registered", "2021-03-31"),
                                 ("accounts not registered", "2023-03-31")])
        self.assertEqual(out[-1]["capital_events"], ["2026-09-09"])

    def test_fi_situation_flag_and_year_end_from_digital_accounts(self):
        get = self.fi_fetcher([], situations=[{"type": "KONK", "registrationDate": "2025-02-01"}],
                              periods=["2023-12-31", "2024-12-31"])
        out = list(mr.fi_report("1234567-8", fetcher=get, today=dt.date(2025, 3, 1)))
        self.assertEqual([r["flag"] for r in out if r["type"] == "fi_flag"][0], "bankruptcy")
        self.assertTrue(out[-1]["financial_year_end"].startswith("12-31 (from the periods"))
        self.assertEqual(len([r for r in out if r["type"] == "fi_accounts_digital"]), 2)

    def test_job_board_found_on_page_and_counted(self):
        page = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
        api = {"departments": [{"name": "Engineering", "jobs": [{"title": "SRE", "location": {"name": "Dublin"}}] * 2},
                               {"name": "Sales", "jobs": [{"title": "AE", "location": {"name": "Boston"}}]}]}

        def get(url):
            return json.dumps(api) if "boards-api.greenhouse.io/v1/boards/acme" in url else page
        [r] = list(mr.jobs_report("https://acme.example/careers", fetcher=get))
        self.assertEqual((r["board"], r["open_roles"]), ("acme", 3))
        self.assertEqual(r["by_department"], {"Engineering": 2, "Sales": 1})

    def test_board_guessed_from_domain(self):
        def get(url):
            if "api.ashbyhq.com/posting-api/job-board/acme" in url:
                return json.dumps({"jobs": [{"title": "PM", "department": "Product", "location": "Paris"}]})
            if "greenhouse" in url:
                raise mr.FetchError("HTTP 404")
            return "<html>jobs load here</html>"
        out = list(mr.jobs_report("https://www.acme.com/careers", fetcher=get))
        self.assertEqual([r["type"] for r in out], ["jobs_board_guessed", "jobs_openings"])

    def test_board_found_from_api_url_in_script(self):
        page = '<script>fetch("https://api.lever.co/v0/postings/hermeus?mode=json")</script>'
        self.assertEqual(mr.find_job_board(page), ("lever", "hermeus"))
        self.assertEqual(mr.find_job_board('x="https://boards-api.greenhouse.io/v1/boards/acme/jobs"'), ("greenhouse", "acme"))
        self.assertEqual(mr.find_job_board('u="https://api.ashbyhq.com/posting-api/job-board/acme"'), ("ashby", "acme"))

    def test_single_guessed_board_shows_office_matches(self):
        def get(url):
            if "api.ashbyhq.com/posting-api/job-board/acme" in url:
                return json.dumps({"jobs": [{"title": "PM", "department": "Product", "location": "Paris"}]})
            if "greenhouse" in url or "lever" in url:
                raise mr.FetchError("HTTP 404")
            return "<html>jobs load here</html>"
        guess = list(mr.jobs_report("https://www.acme.com/careers", fetcher=get, offices=["Boston"]))[0]
        self.assertEqual((guess["type"], guess["office_matches"]), ("jobs_board_guessed", 0))
        self.assertIn("another company", guess["note"])

    def test_board_guess_picks_the_board_with_the_offices(self):
        def get(url):
            if "boards-api.greenhouse.io/v1/boards/acme" in url:
                return json.dumps({"departments": [{"name": "Negozi", "jobs": [{"title": "Commessa", "location": {"name": "Milano"}}] * 3}]})
            if "api.ashbyhq.com/posting-api/job-board/acme" in url:
                return json.dumps({"jobs": [{"title": "Engineer", "department": "Eng", "location": "Stockholm, Sweden"}] * 2})
            if "lever" in url:
                raise mr.FetchError("HTTP 404")
            return "<html>jobs load here</html>"
        out = list(mr.jobs_report("https://acme.dev/careers", fetcher=get, offices=["Stockholm", "Boston"]))
        self.assertEqual([r["type"] for r in out], ["jobs_board_candidates", "jobs_board_guessed", "jobs_openings"])
        self.assertEqual([(c["provider"], c["office_matches"]) for c in out[0]["candidates"]], [("greenhouse", 0), ("ashby", 2)])
        self.assertEqual((out[-1]["provider"], out[-1]["open_roles"]), ("ashby", 2))
        out = list(mr.jobs_report("https://acme.dev/careers", fetcher=get))
        self.assertEqual([r["type"] for r in out], ["jobs_board_candidates", "jobs_board_ambiguous"])

    def test_job_history_counts_archived_links(self):
        cdx = [["urlkey", "timestamp", "original"], ["k", "20250101000000", "https://job-boards.greenhouse.io/acme"],
               ["k", "20250201000000", "https://job-boards.greenhouse.io/acme"]]
        snaps = {"20250101000000": '<a href="/acme/jobs/1">a</a><a href="/acme/jobs/2">b</a><a href="/acme/jobs/2">b</a>',
                 "20250201000000": '<a href="/acme/jobs/3">c</a><a href="/other/jobs/9">x</a>'}

        def get(url):
            if "/cdx/" in url:
                return json.dumps(cdx)
            return snaps[re.search(r"/web/(\d+)id_/", url).group(1)]
        out = list(mr.job_history("greenhouse", "acme", get, pause=0))
        self.assertEqual([(r["date"], r["open_roles"]) for r in out], [("2025-01-01", 2), ("2025-02-01", 1)])
        self.assertEqual(next(mr.job_history("ashby", "acme", get))["type"], "jobs_history_unavailable")


def cdb_block(rcs, end, deposited, fields, form="CA_BILANABR"):
    rows = "".join(f'<Field id="x"><Label>{label}</Label><Data>{value}</Data><PreviousData>0</PreviousData>'
                   f'<Reference xsi:nil="true"/>' for label, value in fields)
    return (f"<Declarer><RcsNumber>{rcs}</RcsNumber><LegalUnitName>Acme S.A.</LegalUnitName>"
            f'<Declaration language="FR" model="2" type="{form}"><StartDate>{end[:4]}-01-01</StartDate>'
            f"<EndDate>{end}</EndDate><YearRef>{end[:4]}</YearRef><RCSDepositDate>{deposited}T09:00:00Z</RCSDepositDate>"
            f"<ID_Doc>{end}{form}</ID_Doc><Currency>EUR</Currency><FormData>{rows}</FormData></Declaration></Declarer>")


class LuxembourgRunFixes(unittest.TestCase):
    def lu(self, blocks_by_url, today=dt.date(2026, 11, 22)):
        dataset = {"resources": [{"title": "deposit-2026q3.xml", "url": "u/2026q3"},
                                 {"title": "deposit-2025q3.xml", "url": "u/2025q3"},
                                 {"title": "notes.pdf", "url": "u/x"}]}
        return list(mr.lu_report("b 165616", quarters=12, fetcher=lambda u: json.dumps(dataset),
                                 streamer=lambda url, rcs: blocks_by_url.get(url, []), today=today))

    def test_figures_late_filing_and_negative_equity(self):
        fy24 = cdb_block("B165616", "2024-12-31", "2025-11-30", [
            ("TOTAL DU BILAN (ACTIF)", "2500000.00"), ("Capitaux propres", "-5670000.00"),
            ("Capital souscrit", "100000.00"), ("Avoirs en banques, avoirs en compte de chèques postaux", "113000.00"),
            ("Dettes", "8000000.00"), ("Emprunts convertibles", "6300000.00")])
        fy24_pl = cdb_block("B165616", "2024-12-31", "2025-11-30", [
            ("Chiffre d&apos;affaires net", "4000000.00"), ("Résultat de l&apos;exercice", "-9600000.00")], form="CA_COMPABR")
        fy25 = cdb_block("B165616", "2025-12-31", "2026-07-15", [("Capitaux propres", "-1270000.00")])
        out = self.lu({"u/2025q3": [fy24, fy24_pl], "u/2026q3": [fy25]})
        years = {r["year_end"]: r for r in out if r["type"] == "lu_accounts_year"}
        self.assertEqual((years["2024-12-31"]["equity"], years["2024-12-31"]["cash"], years["2024-12-31"]["turnover"],
                          years["2024-12-31"]["net_result"], years["2024-12-31"]["convertible_loans"]),
                         (-5670000.0, 113000.0, 4000000.0, -9600000.0, 6300000.0))
        self.assertNotIn("debts", {k for k, v in years["2024-12-31"].items() if v == 100000.0})  # capital is not equity
        flags = [(r["flag"], r["year_end"]) for r in out if r["type"] == "lu_flag"]
        self.assertEqual(flags, [("late accounts", "2024-12-31"), ("negative equity", "2025-12-31")])
        late = next(r for r in out if r.get("flag") == "late accounts")
        self.assertEqual((late["due"], late["days_late"], late["recent"]), ("2025-07-31", 122, True))
        self.assertEqual(out[-1]["quarters_searched"], ["2026q3", "2025q3"])

    def test_unreadable_quarter_is_reported(self):
        def streamer(url, rcs):
            raise mr.FetchError("HTTP 503")
        dataset = {"resources": [{"title": "deposit-2026q3.xml", "url": "u/2026q3"}]}
        out = list(mr.lu_report("B1", fetcher=lambda u: json.dumps(dataset), streamer=streamer))
        self.assertEqual(out[0]["type"], "lu_quarter_unreadable")

    def test_gleif_fund_is_labelled(self):
        rec = {"attributes": {"lei": "F1", "entity": {"legalName": {"name": "TADAWEB"}, "jurisdiction": "LU",
                                                       "category": "FUND", "legalForm": {"id": "9999", "other": "SUB-FUND"}},
                              "registration": {"status": "ISSUED"}}}
        umbrella = {"attributes": {"lei": "U1", "entity": {"legalName": {"name": "Expansion 17 S.C.A., FIAR"}},
                                   "registration": {"status": "ISSUED"}}}

        def get(url):
            path = url[len(mr.GLEIF):].split("?")[0]
            if path == "/lei-records/F1":
                return json.dumps({"data": rec})
            if path == "/lei-records/F1/umbrella-fund":
                return json.dumps({"data": umbrella})
            raise mr.FetchError(f"HTTP 404 for {url}")
        out = list(mr.gleif_report("F1", fetcher=get))
        fund = next(r for r in out if r["type"] == "gleif_fund")
        self.assertEqual((fund["legal_form_other"], fund["umbrella_fund"]), ("SUB-FUND", "Expansion 17 S.C.A., FIAR"))

    def test_psc_mismatch_when_corporate_psc_ceased(self):
        ch = fake_ch({"/company/11574511/persons-with-significant-control": {"items": [
            {"name": "Tadaweb S.A.", "kind": "corporate-entity-person-with-significant-control",
             "notified_on": "2018-09-13", "ceased_on": "2018-09-13"},
            {"name": "Jane Doe", "kind": "individual-person-with-significant-control"}]}})
        [r] = mr.psc_parent_mismatch("11574511", ch, ["The parent undertaking is Tadaweb S.A."])
        self.assertEqual((r["statement"], r["last_corporate_psc"]), ("no current corporate PSC", "Tadaweb S.A."))
        current = fake_ch({"/company/1/persons-with-significant-control": {"items": [
            {"name": "Parent Ltd", "kind": "corporate-entity-person-with-significant-control"}]}})
        self.assertEqual(list(mr.psc_parent_mismatch("1", current, ["parent"])), [])

    def test_psc_mismatch_quotes_the_sentence_naming_the_parent(self):
        ch = fake_ch({"/company/13812276/persons-with-significant-control-statements": {"items": [
            {"statement": "no-individual-or-entity-with-signficant-control", "notified_on": "2021-12-21"}]}})
        sentences = ["Related party transactions The company has taken advantage of the exemption available under "
                     "paragraph 33.1A of FRS 102 for transactions with the ultimate parent company.",
                     "Controlling party The immediate parent undertaking is Sanity Inc, a company incorporate in "
                     "United States of America."]
        [r] = mr.psc_parent_mismatch("13812276", ch, sentences)
        self.assertIn("immediate parent undertaking is Sanity Inc", r["accounts_say"])

    def test_too_large_page_and_local_quote_check(self):
        with tempfile.TemporaryDirectory() as d:
            report = os.path.join(d, "financials.md")
            with open(report, "w", encoding="utf-8") as f:
                f.write("## Red flags\n1. **Negative equity** https://data.public.lu/big.xml Quote: \"Capitaux propres -5670000.00\"\n")
            def fetcher(url):
                raise mr.FetchError("response larger than 104857600 bytes")
            records = list(mr.verify_reports([report], None, fetcher=fetcher))
            self.assertEqual(records[0]["result"], "too_large")
            extract = os.path.join(d, "cdb.xml")
            with open(extract, "w", encoding="utf-8") as f:
                f.write("<Field><Label>Capitaux propres</Label><Data>-5670000.00</Data></Field>")
            out, saved = [], mr.emit
            mr.emit = out.append
            try:
                mr.quote_check(extract, "Capitaux propres -5670000.00", None, 20)
            finally:
                mr.emit = saved
            self.assertTrue(out[0]["found"])


class SnykAfterRunFixes(unittest.TestCase):
    def test_common_word_alias_is_dropped(self):
        # "Fugue" (an acquired product) matched 1,274 unrelated fund filings; "Snyk" about 40
        hit = lambda cik: {"cik": cik, "form": "NPORT-P", "filed": "2026-06-30", "filer": "F", "accession": cik,
                           "url": f"https://www.sec.gov/{cik}.xml", "period_ending": "2026-06-30"}
        totals = {"Snyk": 40, "Fugue": 1274}

        def search(alias, forms, *a):
            n = totals[alias] if forms == ["NPORT-P"] else 0
            found = [hit(f"{alias}{i}") for i in range(min(n, 3))]
            return found, {"type": "search_summary", "total": n, "truncated": False}
        fetched, out, saved = [], [], (mr.edgar_search, mr.emit, mr.fetch_nport_holdings)
        mr.edgar_search, mr.emit = search, out.append
        mr.fetch_nport_holdings = lambda url, ua, aliases: fetched.append(url) or []
        try:
            mr.marks(["Snyk", "Fugue"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.emit, mr.fetch_nport_holdings = saved
        dropped = [r for r in out if r["type"] == "generic_alias" and r.get("dropped")]
        self.assertEqual([r["alias"] for r in dropped], ["Fugue"])
        self.assertEqual(next(r for r in out if r["type"] == "marks_search")["searched"], ["Snyk"])
        self.assertFalse([u for u in fetched if "Fugue" in u])
        self.assertTrue([u for u in fetched if "Snyk" in u])

    def test_alias_skips_loan_codes_and_longer_words(self):
        self.assertTrue(mr.alias_in("Pleo", "Pleo Technologies A/S Term Loan"))
        self.assertTrue(mr.alias_in("Acme", "ACME-HOLDINGS LLC First Lien"))
        self.assertFalse(mr.alias_in("Pleo", "Affirm loan PLEO-MZHJ"))
        self.assertFalse(mr.alias_in("Pleo", "PLEO-7K2Q consumer receivable"))
        self.assertFalse(mr.alias_in("Pleo", "Pleorama Inc"))
        self.assertTrue(mr.alias_in("Falcon Purchaser", "FALCON PURCHASER-XYZ"))  # long aliases keep codes
        doc = ("<edgarSubmission><formData><genInfo><regName>Trust</regName><repPdDate>2026-06-30</repPdDate></genInfo>"
               "<invstOrSecs><invstOrSec><name>PLEO-MZHJ</name><title>Affirm loan</title><balance>12</balance></invstOrSec>"
               "<invstOrSec><name>Pleo Technologies A/S</name><title>Term loan</title><balance>1000</balance>"
               "<valUSD>950</valUSD><units>PA</units></invstOrSec></invstOrSecs></formData></edgarSubmission>")
        rows = mr.parse_nport_holdings(doc, ["Pleo"])
        self.assertEqual([(r["name"], r["mark"], r["fund"]) for r in rows], [("Pleo Technologies A/S", 95.0, "Trust")])

    def test_nport_streamed_in_pieces(self):
        doc = ("<edgarSubmission xmlns='http://www.sec.gov/edgar/nport'><formData><genInfo><seriesName>Fund A</seriesName>"
               "<repPdDate>2026-06-30</repPdDate></genInfo><invstOrSecs>"
               + "<invstOrSec><name>Other Co</name><balance>1</balance></invstOrSec>" * 500
               + "<invstOrSec><name>Acme Robotics Inc</name><balance>10</balance><valUSD>5</valUSD><units>NS</units>"
                 "</invstOrSec></invstOrSecs></formData></edgarSubmission>").encode()
        scan = mr.NportScan(["Acme Robotics"])
        for i in range(0, len(doc), 1000):
            scan.feed(doc[i:i + 1000])
        [row] = scan.close()
        self.assertEqual((row["fund"], row["value_per_share"]), ("Fund A", 0.5))

    def test_no_holdings_found_is_partial_when_a_filing_failed(self):
        hit = {"cik": "1", "form": "NPORT-P", "filed": "2026-06-30", "filer": "Stone Ridge", "accession": "a",
               "url": "https://www.sec.gov/big.xml", "period_ending": "2026-06-30"}
        out, saved = [], (mr.edgar_search, mr.emit, mr.fetch_nport_holdings)
        mr.edgar_search = lambda alias, forms, *a: (([hit], {"total": 1, "truncated": False}) if forms == ["NPORT-P"]
                                                     else ([], {"total": 0, "truncated": False}))
        mr.emit = out.append

        def fail(url, ua, aliases):
            raise mr.FetchError("decompressed response larger than 2147483648 bytes")
        mr.fetch_nport_holdings = fail
        try:
            mr.marks(["Pleo"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.emit, mr.fetch_nport_holdings = saved
        last = next(r for r in out if r["type"] == "no_holdings_found")
        self.assertTrue(last["partial"])
        self.assertEqual(last["unread"], ["https://www.sec.gov/big.xml"])
        self.assertNotIn("nothing failed", last["note"])

    def test_tagged_xbrl_fact_quote_needs_no_extra_words(self):
        self.assertEqual(mr.quote_warnings("x", "<fsa:Equity>-760000000</fsa:Equity>", "760000000"), [])
        self.assertTrue(mr.quote_warnings("x", "equity was", "equity was"))

    def test_single_alias_is_never_dropped(self):
        def search(alias, forms, *a):
            return [], {"type": "search_summary", "total": 900, "truncated": False}
        out, saved = [], (mr.edgar_search, mr.emit)
        mr.edgar_search, mr.emit = search, out.append
        try:
            mr.marks(["SpaceX"], "ua", "2025-08-01", 2, 20)
        finally:
            mr.edgar_search, mr.emit = saved
        self.assertFalse([r for r in out if r.get("dropped")])

class Fetch(unittest.TestCase):
    def test_gzip_body_round_trips(self):
        body = b"<html>schedule</html>" * 100
        self.assertEqual(mr.read_body(io.BytesIO(gzip.compress(body)), True, limit=10_000), body)

    def test_gzip_bomb_is_refused(self):
        bomb = gzip.compress(b"\0" * 5_000_000)  # ~5 KB compressed, 5 MB expanded
        with self.assertRaises(mr.FetchError):
            mr.read_body(io.BytesIO(bomb), True, limit=1_000_000)

    def test_oversized_plain_body_is_refused(self):
        with self.assertRaises(mr.FetchError):
            mr.read_body(io.BytesIO(b"x" * 200_000), False, limit=100_000)

    def test_sec_requires_user_agent(self):
        with self.assertRaises(mr.FetchError):
            mr.fetch("https://data.sec.gov/submissions/CIK0000000001.json", None)

    def test_sec_contact_format(self):
        for good in ("Jane Smith jane@example.com", "Acme Research Ltd ops@acme.co.uk", "  Jane j@x.io  ",
                     '"Jane Smith jane@example.com"'):
            self.assertIsNone(mr.sec_contact_problem(good), good)
        for bad in (None, "", "   ", "jane@example.com", "Jane Smith", "Jane Smith jane@example",
                    "Jane Smith @example.com", "jane@example.com Jane Smith"):
            self.assertIn("needs --user-agent", mr.sec_contact_problem(bad), repr(bad))

    def test_quoted_contact_sent_without_quotes(self):
        # PowerShell's .env loader in the README keeps the quotes as part of the value
        self.assertEqual(mr.clean_sec_contact('"Jane Smith jane@example.com"'), "Jane Smith jane@example.com")

    def test_malformed_contact_refused_without_echoing_it(self):
        with self.assertRaises(mr.FetchError) as caught:
            mr.fetch("https://data.sec.gov/submissions/CIK0000000001.json", "secretname")
        self.assertIn("Name email", str(caught.exception))
        self.assertNotIn("secretname", str(caught.exception))

    def test_sec_command_stops_before_any_request(self):
        out = io.StringIO()
        original, mr.fetch = mr.fetch, lambda *a, **k: self.fail("fetched with a malformed contact")
        try:
            with contextlib.redirect_stdout(out):
                code = mr.main(["--user-agent", "jane@example.com", "edgar-filings", "1"])
        finally:
            mr.fetch = original
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["type"], "error")

    def test_sec_contact_goes_to_sec_gov_only(self):
        sent = {}

        class Response(io.BytesIO):
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(request, timeout):
            # urllib's merge order differs by version (3.15+ lets ordinary headers win), so
            # the request must give the same User-Agent under either order
            older = {**request.headers, **request.unredirected_hdrs}
            newer = {**request.unredirected_hdrs, **request.headers}
            self.assertEqual(older.get("User-agent"), newer.get("User-agent"))
            sent[urllib.parse.urlparse(request.full_url).hostname] = newer.get("User-agent")
            return Response(b"ok")
        contact = "Jane Doe jane@example.com"
        original, mr.urllib.request.urlopen = mr.urllib.request.urlopen, urlopen
        try:
            for url in ("https://www.sec.gov/x", "https://efts.sec.gov/x",
                        "https://find-and-update.company-information.service.gov.uk/x",
                        "https://tech.eu/x", "https://notsec.gov/x"):
                mr.fetch(url, contact, retries=0)
        finally:
            mr.urllib.request.urlopen = original
        self.assertEqual(sent["www.sec.gov"], contact)
        self.assertEqual(sent["efts.sec.gov"], contact)
        for host in ("find-and-update.company-information.service.gov.uk", "tech.eu", "notsec.gov"):
            self.assertEqual(sent[host], "muckraker")

    def test_sec_contact_dropped_on_redirect(self):
        captured = []

        class Response(io.BytesIO):
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(request, timeout):
            captured.append(request)
            return Response(b"ok")
        original, mr.urllib.request.urlopen = mr.urllib.request.urlopen, urlopen
        try:
            mr.fetch("https://www.sec.gov/x", "Jane Doe jane@example.com", retries=0)
        finally:
            mr.urllib.request.urlopen = original
        # urllib's own redirect handling builds the next request from the ordinary headers only
        followed = urllib.request.HTTPRedirectHandler().redirect_request(
            captured[0], None, 302, "Found", {}, "https://elsewhere.example/y")
        self.assertNotIn("Jane", str(followed.header_items()))

    def test_missing_contact_explained(self):
        def fetcher(url):
            raise mr.FetchError("sec.gov needs --user-agent or MUCKRAKER_SEC_UA")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sec.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("SOURCE: SEC\n## Red flags\n1. **X** https://www.sec.gov/a QUOTE: \"one two three four five\"\n")
            out = list(mr.verify_reports([path], None, fetcher=fetcher))
        self.assertIn("--user-agent", out[0]["note"])


class DecodeBody(unittest.TestCase):
    def test_latin1_page_keeps_norwegian_letters(self):
        # w2.brreg.no serves windows-1252; decoding it as UTF-8 lost every å, so quotes with it never matched
        raw = '<meta charset="windows-1252"><p>mottatt komplett\xa0årsregnskap</p>'.encode("cp1252")
        self.assertIn("komplett\xa0årsregnskap", mr.decode_body(raw))
        self.assertGreaterEqual(mr.find_quote(mr.searchable_text(mr.decode_body(raw)).lower(),
                                              "mottatt komplett årsregnskap")[0], 0)

    def test_utf8_and_undeclared_bodies(self):
        self.assertEqual(mr.decode_body("årsregnskap".encode("utf-8")), "årsregnskap")
        self.assertEqual(mr.decode_body("årsregnskap".encode("cp1252")), "årsregnskap")  # no charset: cp1252
        self.assertEqual(mr.decode_body(b"charset=nonsense \xe5"), "charset=nonsense å")  # unknown charset



NO_ORG = "918714529"
NO_NOTICES = "https://w2.brreg.no/kunngjoring"


def no_notice_row(date, kind, kid):
    return (f"<tr><td>{date}</td><td>&nbsp;</td><td><a href=\"hent_en.jsp?kid={kid}&amp;sokeverdi={NO_ORG}&amp;spraak=nb\">"
            f"{kind}</a></td></tr>")


def no_notice_page(body, register="Foretaksregisteret", date="01.01.2024"):
    # the real pages put a style block and the search form before the notice
    return (f"<html><head><style>.altova{{filter: x}}</style></head><body><p>Kunngj&oslash;ring for:</p>"
            f"<p><strong>Organisasjonsnummer</strong> <strong>918 714 529</strong> (SANITY AS)</p>"
            f"<h3>Notice</h3>{body}<br><span>{register} {date}</span><p>Kontakt oss</p></body></html>")


def no_accounts_notice(received, start, end):
    return no_notice_page(f"Regnskapsregisteret har den {received} mottatt komplett &aring;rsregnskap for "
                          f"regnskaps&aring;ret 2024 fra: <table><tr><td>&Aring;rsregnskapet omfatter perioden fra "
                          f"{start} til {end}.</td></tr></table> Foretaket er i denne perioden ikke registrert som "
                          "morselskap i konsern.", "Regnskapsregisteret")


def no_fetcher(pages):
    def get(url):
        if url not in pages:
            raise mr.FetchError(f"HTTP 404 for {url}")
        return pages[url]
    return get


def no_pages(equity=1124934.0, konkurs=False, notices=None, extra=None):
    api = mr.BRREG_API
    entity = {"organisasjonsnummer": NO_ORG, "navn": "SANITY AS", "organisasjonsform": {"kode": "AS"},
              "stiftelsesdato": "2017-02-14", "registreringsdatoEnhetsregisteret": "2017-03-16",
              "forretningsadresse": {"adresse": ["Trondheimsveien 2K"], "postnummer": "0560", "poststed": "OSLO"},
              "kapital": {"belop": 1000000.0, "antallAksjer": 1, "innfortDato": "2025-07-15"},
              "konkurs": konkurs, "underAvvikling": False, "underTvangsavviklingEllerTvangsopplosning": False}
    if konkurs:
        entity["konkursdato"] = "2025-09-12"
    roles = {"rollegrupper": [{"sistEndret": "2023-03-30", "roller": [
        {"type": {"beskrivelse": "Styrets leder"}, "person": {"navn": {"fornavn": "Magnus", "mellomnavn": "Kongsli",
                                                                        "etternavn": "Hillestad"},
                                                         "fodselsdato": "1981-04-15"}, "fratraadt": False},
        {"type": {"beskrivelse": "Revisor"}, "enhet": {"organisasjonsnummer": "935416779", "navn": ["CEDRA NORGE AS"]}}]}]}
    accounts = [{"regnskapsperiode": {"fraDato": "2023-02-01", "tilDato": "2024-01-31"}, "valuta": "NOK",
                 "revisjon": {"ikkeRevidertAarsregnskap": False, "fravalgRevisjon": False},
                 "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": equity},
                                      "gjeldOversikt": {"sumGjeld": 154503912.0, "langsiktigGjeld": {"sumLangsiktigGjeld": 117807682.0}}},
                 "eiendeler": {"sumBankinnskuddOgKontanter": 29268173.0, "sumEiendeler": 155628846.0},
                 "resultatregnskapResultat": {"aarsresultat": -16696663.0, "driftsresultat": {
                     "driftsresultat": -20699999.0, "driftsinntekter": {"sumDriftsinntekter": 56297466.0}},
                     "finansresultat": {"finanskostnad": {"rentekostnadSammeKonsern": 2600574.0}}}}]
    rows = notices if notices is not None else [
        ("23.09.2024", "Godkjente årsregnskap", "1"),
        ("16.08.2024", "Nedsettelse av kapital", "2"),
        ("29.04.2024", "Meldepliktig avtale", "3"),
        ("", "Vedtektsdato", "4"),
        ("03.03.2018", "Styre", "5")]
    pages = {
        f"{api}/enheter/{NO_ORG}": json.dumps(entity),
        f"{api}/enheter/{NO_ORG}/roller": json.dumps(roles),
        f"{api}/underenheter?overordnetEnhet={NO_ORG}": json.dumps({"_embedded": {"underenheter": [
            {"organisasjonsnummer": "818817452", "navn": "SANITY AS", "antallAnsatte": 39}]}}),
        f"{mr.BRREG_ACCOUNTS}/{NO_ORG}": json.dumps(accounts),
        f"{NO_NOTICES}/hent_nr.jsp?orgnr={NO_ORG}": "<table>" + "".join(no_notice_row(*r) for r in rows) + "</table>",
        f"{NO_NOTICES}/hent_en.jsp?kid=1&sokeverdi={NO_ORG}&spraak=nb": no_accounts_notice("23.09.2024", "01.02.2023", "31.01.2024"),
        f"{NO_NOTICES}/hent_en.jsp?kid=2&sokeverdi={NO_ORG}&spraak=nb": no_notice_page(
            "Kreditorvarsel Kapitalnedsettelse I generalforsamling 05.06.2024 ble aksjekapitalen besluttet nedsatt fra "
            "NOK 40.169.417,50 til NOK 1.000.000,00. Nedsettelsesbel&oslash;pet skal anvendes til: Avsetning til fond."),
        f"{NO_NOTICES}/hent_en.jsp?kid=3&sokeverdi={NO_ORG}&spraak=nb": no_notice_page(
            "Foretaksregisteret har mottatt redegj&oslash;relse datert 24.01.2024 for inng&aring;else av avtale etter "
            "aksjeloven &sect; 3-8 mellom selskapet og Sanity, Inc. N&aelig;rmere opplysninger finnes i dokumentet."),
    }
    pages.update(extra or {})
    return pages


class Norway(unittest.TestCase):
    TODAY = dt.date(2026, 11, 23)

    def run_no(self, pages, query=NO_ORG, today=None):
        return list(mr.no_report(query, fetcher=no_fetcher(pages), today=today or self.TODAY))

    def test_profile_officers_accounts_and_notices(self):
        out = self.run_no(no_pages())
        company = next(r for r in out if r["type"] == "no_company")
        self.assertEqual((company["name"], company["shares"], company["bankrupt"]), ("SANITY AS", 1, False))
        self.assertTrue(any(r["type"] == "no_note" and "single shareholder" in r["note"] for r in out))
        officers = {r["name"]: r for r in out if r["type"] == "no_officer"}
        self.assertEqual(officers["Magnus Kongsli Hillestad"]["role"], "Styrets leder")
        self.assertEqual(officers["Magnus Kongsli Hillestad"]["born"], "1981-04")  # month and year only
        self.assertEqual((officers["CEDRA NORGE AS"]["orgnr"], officers["CEDRA NORGE AS"]["born"]), ("935416779", None))
        [year] = [r for r in out if r["type"] == "no_accounts_year"]
        self.assertEqual((year["revenue"], year["equity"], year["group_interest"]), (56297466.0, 1124934.0, 2600574.0))
        self.assertTrue(year["pdf"].endswith(f"/aarsregnskap/kopi/{NO_ORG}/2024"))
        [reduction] = [r for r in out if r["type"] == "no_capital"]
        self.assertEqual((reduction["change"], reduction["from"], reduction["to"]), ("reduction", 40169417.5, 1000000.0))
        [agreement] = [r for r in out if r["type"] == "no_agreement"]
        self.assertEqual(agreement["counterparty"], "Sanity, Inc")
        # a row with no date shares the row above's; an old board notice is listed, not opened
        notices = {r["notice"]: r for r in out if r["type"] == "no_notice"}
        self.assertEqual(notices["Vedtektsdato"]["date"], "2024-04-29")
        self.assertNotIn("text", notices["Styre"])
        self.assertEqual(out[-1]["type"], "no_summary")

    def test_late_accounts(self):
        out = self.run_no(no_pages())
        [filed] = [r for r in out if r["type"] == "no_accounts_filed"]
        self.assertEqual((filed["received"], filed["due"], filed["days_late"]), ("2024-09-23", "2024-08-31", 23))
        [late] = [r for r in out if r.get("flag") == "late accounts"]
        self.assertEqual((late["severity"], late["recent"]), ("major", True))
        self.assertEqual(late["quote"], "Regnskapsregisteret har den 23.09.2024 mottatt komplett")
        # the same filing seen four years on is old: minor, for Facts
        old = self.run_no(no_pages(), today=dt.date(2028, 6, 1))
        self.assertEqual(next(r for r in old if r.get("flag") == "late accounts")["severity"], "minor")
        self.assertEqual(mr._add_months_end(dt.date(2025, 12, 31), 7), dt.date(2026, 7, 31))
        self.assertEqual(mr._add_months_end(dt.date(2024, 1, 31), 7), dt.date(2024, 8, 31))
        # Brreg sometimes lists one filing under two notices: report and flag it once
        twice = no_pages(notices=[("23.09.2024", "Godkjente årsregnskap", "1"), ("", "Godkjente årsregnskap", "1b")],
                         extra={f"{NO_NOTICES}/hent_en.jsp?kid=1b&sokeverdi={NO_ORG}&spraak=nb":
                                no_accounts_notice("23.09.2024", "01.02.2023", "31.01.2024")})
        out = self.run_no(twice)
        self.assertEqual(len([r for r in out if r["type"] == "no_accounts_filed"]), 1)
        self.assertEqual(len([r for r in out if r.get("flag") == "late accounts"]), 1)

    def test_missing_accounts_and_negative_equity(self):
        # latest filed year ends 31.01.2024; the next (to 31.01.2025) was due 31.08.2025 and is absent
        out = self.run_no(no_pages(equity=-5.0))
        flags = {r["flag"]: r for r in out if r["type"] == "no_flag"}
        self.assertEqual(flags["negative equity"]["equity"], -5.0)
        self.assertEqual((flags["accounts not filed"]["period_end"], flags["accounts not filed"]["due"]),
                         ("2025-01-31", "2025-08-31"))
        on_time = self.run_no(no_pages(), today=dt.date(2025, 8, 1))
        self.assertFalse(any(r.get("flag") == "accounts not filed" for r in on_time))

    def test_bankruptcy(self):
        konkurs = no_notice_page("Konkurs - &aring;pning Ved VESTFOLD TINGRETT er det &aring;pnet konkurs i boet til: "
                                 "SANITY AS", "Konkursregisteret", "12.09.2025")
        pages = no_pages(konkurs=True, notices=[("12.09.2025", "Konkursåpning", "9")],
                         extra={f"{NO_NOTICES}/hent_en.jsp?kid=9&sokeverdi={NO_ORG}&spraak=nb": konkurs})
        out = self.run_no(pages)
        flags = [r for r in out if r["type"] == "no_flag"]
        self.assertEqual(flags[0]["flag"], "bankruptcy proceedings opened (konkurs)")
        self.assertEqual(flags[0]["since"], "2025-09-12")
        notice = next(r for r in flags if r["flag"] == "announcement: Konkursåpning")
        self.assertEqual(notice["severity"], "major")
        self.assertTrue(notice["quote"].startswith("Notice Konkurs - åpning Ved VESTFOLD TINGRETT"))
        self.assertNotIn("filter", notice["quote"])  # the style block is not text
        self.assertFalse(any(r.get("flag") == "accounts not filed" for r in out))  # a bankrupt company files none

    def test_name_search_and_missing_unit(self):
        url = f"{mr.BRREG_API}/enheter?navn=sanity&size=20"
        out = self.run_no({url: json.dumps({"_embedded": {"enheter": [
            {"organisasjonsnummer": NO_ORG, "navn": "SANITY AS", "organisasjonsform": {"kode": "AS"}}]}})}, query="sanity")
        self.assertEqual([(r["type"], r.get("orgnr")) for r in out], [("no_candidate", NO_ORG), ("no_note", None)])
        gone = self.run_no({}, query="918 714 529")
        self.assertEqual([r["type"] for r in gone], ["no_note"])


DK_GAAP_XML = """<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:e="http://xbrl.dcca.dk/fsa"
 xmlns:d="http://xbrl.dcca.dk/cmn" xmlns:g="http://xbrl.dcca.dk/arr" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
<context id="d"><entity><identifier scheme="http://www.dcca.dk/cvr">12345678</identifier></entity>
 <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>
<context id="i"><entity><identifier scheme="http://www.dcca.dk/cvr">12345678</identifier></entity>
 <period><instant>2025-12-31</instant></period></context>
<context id="p"><entity><identifier scheme="http://www.dcca.dk/cvr">12345678</identifier></entity>
 <period><instant>2024-12-31</instant></period></context>
<context id="b1"><entity><identifier scheme="http://www.dcca.dk/cvr">12345678</identifier></entity>
 <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period>
 <scenario><xbrldi:typedMember dimension="d:IdentificationOfMemberOfExecutiveBoardDimension"><d:id>1</d:id></xbrldi:typedMember></scenario></context>
<unit id="DKK"><measure>iso4217:DKK</measure></unit>
<e:Revenue contextRef="d" unitRef="DKK" decimals="-3">553621000</e:Revenue>
<e:ProfitLoss contextRef="d" unitRef="DKK" decimals="-3">-537956000</e:ProfitLoss>
<e:Equity contextRef="i" unitRef="DKK" decimals="-3">-760211000</e:Equity>
<e:Equity contextRef="p" unitRef="DKK" decimals="-3">-222255000</e:Equity>
<e:ClassOfReportingEntity contextRef="d">Reporting class C, large enterprise</e:ClassOfReportingEntity>
<e:DisclosureOfUncertaintiesRelatingToGoingConcern contextRef="d">&lt;p&gt;Going concern: the parent has issued a letter of support of up to EUR 85m.&lt;/p&gt;</e:DisclosureOfUncertaintiesRelatingToGoingConcern>
<g:SupplementaryInformationOnAudit contextRef="d">The Company has lost more than half of its share capital, contrary to the Danish Companies Act.</g:SupplementaryInformationOnAudit>
<g:TypeOfModifiedOpinionOnAuditedFinancialStatements contextRef="d">Opinion</g:TypeOfModifiedOpinionOnAuditedFinancialStatements>
<d:NameAndSurnameOfMemberOfExecutiveBoard contextRef="b1">Jane Doe</d:NameAndSurnameOfMemberOfExecutiveBoard>
<d:TitleOfMemberOfExecutiveBoard contextRef="b1">CEO</d:TitleOfMemberOfExecutiveBoard>
</xbrl>"""

DK_COVER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:fsa="http://xbrl.dcca.dk/fsa"
 xmlns:cmn="http://xbrl.dcca.dk/cmn" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
<xbrli:context id="g"><xbrli:entity><xbrli:identifier scheme="http://www.dcca.dk/cvr">87654321</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
 <xbrli:scenario><xbrldi:explicitMember dimension="cmn:ConsolidatedSoloDimension">cmn:ConsolidatedMember</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
<xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
<fsa:AverageNumberOfEmployees contextRef="g" unitRef="pure" decimals="0">856</fsa:AverageNumberOfEmployees>
<cmn:NameAndSurnameOfMemberOfSupervisoryBoard contextRef="g">Ann Chair</cmn:NameAndSurnameOfMemberOfSupervisoryBoard>
</xbrli:xbrl>"""

DK_IFRS_XHTML = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"><body>
<ix:header><ix:resources>
<xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="x">87654321</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c2"><xbrli:entity><xbrli:identifier scheme="x">87654321</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<p>Revenue <ix:nonFraction name="ifrs-full:Revenue" contextRef="c1" unitRef="EUR" scale="3" decimals="-3" format="ixt:num-dot-decimal">129,904</ix:nonFraction></p>
<p>Loss (<ix:nonFraction name="ifrs-full:ProfitLoss" contextRef="c1" unitRef="EUR" scale="3" sign="-" decimals="-3">45,765</ix:nonFraction>)</p>
<p>Equity <ix:nonFraction name="ifrs-full:Equity" contextRef="c2" unitRef="EUR" scale="3" format="ixt:num-comma-decimal">105.139</ix:nonFraction></p>
<p><ix:nonNumeric name="ifrs-full:NameOfParentEntity" contextRef="c1">Top <span>Holding</span> <ix:nonNumeric name="ifrs-full:NameOfUltimateParentOfGroup" contextRef="c1">Ultimate ApS</ix:nonNumeric></ix:nonNumeric></p>
</body></html>"""


class Denmark(unittest.TestCase):
    def filings(self, cvr, hits):
        return json.dumps({"hits": {"hits": [{"_source": {"cvrNummer": cvr, **h}} for h in hits]}}).encode()

    @staticmethod
    def filing(start, end, published, docs):
        return {"offentliggoerelsestype": "regnskab", "offentliggoerelsesTidspunkt": published + "T10:00:00Z",
                "omgoerelse": False, "regnskab": {"regnskabsperiode": {"startDato": start, "slutDato": end}},
                "dokumenter": [{"dokumentType": t, "dokumentMimeType": m, "dokumentUrl": u} for t, m, u in docs]}

    def test_deadlines(self):
        # 6 months from the year end, moved off a weekend (30 June 2024 was a Sunday); 4 for class D;
        # 2019 years had 5 months plus the COVID-19 extension of 3
        self.assertEqual(mr.dk_deadline(dt.date(2024, 12, 31))[0], dt.date(2025, 6, 30))
        self.assertEqual(mr.dk_deadline(dt.date(2023, 12, 31))[0], dt.date(2024, 7, 1))
        self.assertEqual(mr.dk_deadline(dt.date(2025, 12, 31), "Reporting class D")[0], dt.date(2026, 4, 30))
        self.assertEqual(mr.dk_deadline(dt.date(2019, 12, 31))[0], dt.date(2020, 8, 31))
        self.assertEqual(mr.dk_deadline(dt.date(2018, 12, 31))[0], dt.date(2019, 5, 31))

    def test_danish_gaap_report_filings_and_flags(self):
        hits = [self.filing("2023-01-01", "2023-12-31", "2024-07-30", [("AARSRAPPORT", "application/pdf", "http://regnskaber.virk.dk/23.pdf")]),
                self.filing("2025-01-01", "2025-12-31", "2026-03-30",
                            [("AARSRAPPORT", "application/xml", "http://regnskaber.virk.dk/25.xml"), ("AARSRAPPORT", "application/pdf", "http://regnskaber.virk.dk/25.pdf"),
                             ("KONCERNREGNSKAB_FOR_OVERLIGGENDE_MODER", "application/xhtml+xml", "http://regnskaber.virk.dk/parent.xhtml")])]

        def get(url):
            return self.filings(12345678, hits) if "offentliggoerelser" in url else DK_GAAP_XML.encode()
        out = list(mr.dk_report("12345678", fetcher=get, today=dt.date(2026, 11, 24)))
        filed = [r for r in out if r["type"] == "dk_accounts_filed"]
        self.assertEqual(filed[1]["parent_group_accounts"], "http://regnskaber.virk.dk/parent.xhtml")
        self.assertEqual(filed[1]["report"], "http://regnskaber.virk.dk/25.pdf")
        flags = {r["flag"]: r for r in out if r["type"] == "dk_flag"}
        self.assertEqual((flags["late accounts"]["days_late"], flags["late accounts"]["severity"]), (29, "major"))
        self.assertIn("gap between filed periods", flags)  # FY2024 is missing
        self.assertEqual(flags["negative equity"]["equity"], -760211000.0)
        self.assertIn("letter of support", flags["going-concern note"]["quote"])
        self.assertNotIn("<p>", flags["going-concern note"]["quote"])
        self.assertIn("share capital", flags["auditor remark"]["quote"])
        self.assertNotIn("modified audit opinion", flags)  # "Opinion" is the section heading, not a modification
        self.assertNotIn("accounts not published", flags)  # FY2026 is not due yet
        [year] = [r for r in out if r["type"] == "dk_accounts_year"]
        self.assertEqual((year["scope"], year["currency"], year["revenue"], year["equity"]),
                         ("entity", "DKK", 553621000.0, -760211000.0))
        [officers] = [r for r in out if r["type"] == "dk_officers"]
        self.assertEqual(officers["executive_board"], [{"name": "Jane Doe", "title": "CEO"}])
        self.assertEqual(out[-1]["reporting_class"], "Reporting class C, large enterprise")
        self.assertTrue(all(r["transport"].startswith("unauthenticated http") for r in out))

    def test_ifrs_group_report_merged_with_danish_cover_file(self):
        hits = [self.filing("2025-01-01", "2025-12-31", "2026-03-27",
                            [("AARSRAPPORT", "application/xml", "http://regnskaber.virk.dk/cover.xml"),
                             ("AARSRAPPORT", "application/xhtml+xml", "http://regnskaber.virk.dk/group.xhtml"),
                             ("AARSRAPPORT_ESEF", "application/xml", "http://regnskaber.virk.dk/esef.xml")])]

        def get(url):
            if "offentliggoerelser" in url:
                return self.filings(87654321, hits)
            return (DK_COVER_XML if url.endswith("cover.xml") else DK_IFRS_XHTML).encode()
        out = list(mr.dk_report("87654321", fetcher=get, today=dt.date(2027, 7, 15)))
        [year] = [r for r in out if r["type"] == "dk_accounts_year"]
        self.assertEqual((year["scope"], year["currency"], year["revenue"], year["net_profit"], year["equity"],
                          year["employees"], year["url"]),
                         ("group", "EUR", 129904000.0, -45765000.0, 105139000.0, 856.0, "http://regnskaber.virk.dk/group.xhtml"))
        self.assertEqual([r["supervisory_board"] for r in out if r["type"] == "dk_officers"], [[{"name": "Ann Chair"}]])
        [notes] = [r for r in out if r["type"] == "dk_notes"]
        self.assertEqual(notes["parent_and_related_parties"], ["Ultimate ApS", "Top Holding Ultimate ApS"])  # inner fact closes first
        self.assertEqual([r["flag"] for r in out if r["type"] == "dk_flag"], ["accounts not published"])

    def test_document_links_off_the_register_host_are_not_followed(self):
        hits = [self.filing("2025-01-01", "2025-12-31", "2026-03-30",
                            [("AARSRAPPORT", "application/xml", "http://attacker.example/25.xml")])]
        fetched = []

        def get(url):
            fetched.append(url)
            return self.filings(12345678, hits) if "offentliggoerelser" in url else DK_GAAP_XML.encode()
        out = list(mr.dk_report("12345678", fetcher=get, today=dt.date(2026, 5, 1)))
        self.assertEqual(len(fetched), 1)
        self.assertIsNone([r for r in out if r["type"] == "dk_accounts_filed"][0]["xbrl"])

    def test_name_lists_danish_lei_candidates(self):
        def get(url):
            rec = lambda lei, name, jur, reg: {"attributes": {"lei": lei, "entity": {
                "legalName": {"name": name}, "jurisdiction": jur, "registeredAs": reg, "status": "ACTIVE"},
                "registration": {}}}
            return json.dumps({"data": [rec("A" * 20, "Acme Holding ApS", "DK", "39114127"),
                                        rec("B" * 20, "Acme AB", "SE", "556")]}).encode()
        out = list(mr.dk_report("Acme", fetcher=get))
        self.assertEqual([(r["type"], r.get("cvr")) for r in out], [("dk_candidate", "39114127"), ("dk_note", None)])


class IsraelRunFixes(unittest.TestCase):
    def il(self, details, number="515433167", today=dt.date(2026, 11, 24), missing=False):
        urls = []

        def get(url):
            urls.append(url)
            if missing:
                raise mr.FetchError(f"HTTP 404 for {url}")
            return json.dumps({"key": "x", "value": {"name": "פאפאיה גלובל בע״מ", "name_en": "PAPAYA GLOBAL LTD",
                                                     "__last_modified_at": "2026-11-22T04:36:15Z", "details": details}})
        return list(mr.il_report(number, get, today)), urls

    ACTIVE = {"status": "פעילה", "sub_status": None, "is_mafera": None, "last_report_year": 2025,
              "registration_date": "2016-04-04", "address_lines": ["המדע 14, הרצליה"], "type": "ישראלית חברה פרטית"}

    def test_active_company_has_no_flags(self):
        out, urls = self.il(self.ACTIVE)
        self.assertEqual(urls, ["https://next.obudget.org/get/org/company/515433167"])
        self.assertEqual((out[0]["status_en"], out[0]["violating"], out[0]["copy_date"]), ("active", False, "2026-11-22"))
        self.assertEqual([r["type"] for r in out], ["il_company", "il_summary"])

    def test_violating_and_lagging_company(self):
        out, _ = self.il(dict(self.ACTIVE, is_mafera=True, last_report_year=2004))
        flags = [(r["flag"], r["severity"]) for r in out if r["type"] == "il_flag"]
        self.assertEqual(flags, [("violating company", "major"), ("annual report lagging", "minor")])

    def test_status_flags(self):
        out, _ = self.il(dict(self.ACTIVE, status="מחוסלת מרצון", last_report_year=None))
        self.assertEqual([(r["flag"], r["severity"]) for r in out if r["type"] == "il_flag"], [("not active", "minor")])
        out, _ = self.il(dict(self.ACTIVE, status="מחוקה"))
        self.assertEqual([(r["flag"], r["severity"], r["status_en"]) for r in out if r["type"] == "il_flag"],
                         [("not active", "major", "struck off")])

    def test_name_and_unknown_number(self):
        out, urls = self.il(self.ACTIVE, number="Papaya Global")
        self.assertEqual((out[0]["type"], urls), ("il_note", []))
        out, _ = self.il(self.ACTIVE, missing=True)
        self.assertIn("has no company 515433167", out[0]["note"])

    def test_jobs_falls_back_and_names_unsupported_board(self):
        def refused(url):
            raise mr.FetchError(f"HTTP 403 for {url}")
        out = list(mr.jobs_report("https://www.acme.test/careers/", fetcher=refused))
        self.assertEqual([r["type"] for r in out], ["jobs_page_unreadable", "jobs_board_unknown"])

        def comeet(url):
            if "careers" in url:
                return '<script src="https://www.comeet.co/careers-api/api.js"></script>'
            raise mr.FetchError(f"HTTP 404 for {url}")
        out = list(mr.jobs_report("https://www.acme.test/careers/", fetcher=comeet))
        self.assertEqual((out[-1]["type"], out[-1]["provider"]), ("jobs_board_unsupported", "comeet"))

    def test_texas_forfeited_is_a_major_flag(self):
        rows = {"texas": [{"taxpayer_name": "ACME INC", "taxpayer_number": "32", "right_to_transact_business_code": "N"}]}

        def get(url):
            return json.dumps(next((v for k, v in rows.items() if k in url), [])).encode()
        out = list(mr.us_states_report(["Acme"], fetcher=get))
        flag = next(r for r in out if r["type"] == "us_state_flag")
        self.assertEqual((flag["state"], flag["status"], flag["severity"]), ("TX", "forfeited", "major"))

    def test_quote_label_in_brackets(self):
        md = ("## Red flags\n- **Runway.** URL: https://example.test/a\n"
              "  Quote (table row): \"Net cash from operating activities (129) 1,243\"\n"
              "2. **Allegation.** https://example.test/b Quote (statement to N12): \"לא מכירים קשר\"\n## Gaps\n")
        self.assertEqual([f["quote"] for f in mr.parse_red_flags(md)],
                         ["Net cash from operating activities (129) 1,243", "לא מכירים קשר"])

    def test_javascript_page_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "national-registers.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("## Red flags\n- **Missing accounts.** https://kvk.test/app Quote: \"2023 - Jaarrekening\"\n")
            shell = "<html><head><script src='app.js'></script></head><body>Even geduld alsjeblieft</body></html>"
            out = list(mr.verify_reports([path], None, fetcher=lambda u: shell))
        self.assertEqual((out[0]["result"], out[-1]["js_page"]), ("js_page", 1))

    def test_bot_check_page_is_unreachable(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "press.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("## Red flags\n1. **Allegation.** https://news.test/a Quote: \"no such instructions were given\"\n")
            block = "<html><head><title>Radware Block Page</title></head><body>" + "x " * 400 + "</body></html>"
            out = list(mr.verify_reports([path], None, fetcher=lambda u: block))
        self.assertEqual(out[0]["result"], "unreachable")
        self.assertIn("bot check", out[0]["errors"][0])

    def test_one_word_alias_on_another_company_is_marked(self):
        aliases = ["Papaya Global", "Papaya", "Azimo"]
        self.assertEqual(mr.name_mismatch({"name": "Papaya Growth Opportunity Corp I"}, aliases), ["Papaya Global"])
        self.assertEqual(mr.name_mismatch({"name": "Papaya Global Ltd"}, aliases), [])
        self.assertEqual(mr.name_mismatch({"identifier": "Azimo Ltd, term loan"}, aliases), [])

    def test_usaspending_reads_past_a_page_of_other_recipients(self):
        def post(path, body):
            if path == "/search/spending_over_time/":
                return {"results": []}
            if body["filters"]["award_type_codes"] != ["A", "B", "C", "D"]:
                return {"results": []}
            if body["page"] == 1:
                return {"results": [{"Recipient Name": "AARON AZIMOV", "generated_internal_id": "x1"}],
                        "page_metadata": {"hasNext": True}}
            return {"results": [{"Award ID": "C9", "Recipient Name": "AZIMO INC", "Recipient UEI": "U", "Award Amount": 9.0,
                                 "generated_internal_id": "c9"}], "page_metadata": {"hasNext": False}}
        out = list(mr.usaspending_report(["Azimo"], poster=post, today=dt.date(2026, 11, 24)))
        self.assertEqual([r["award_id"] for r in out if r["type"] == "usa_award"], ["C9"])
        self.assertNotIn("truncated", out[-1])


class SpainRunFixes(unittest.TestCase):
    # text as mr.pdf_text gives it for a BORME section A PDF, with a page header in the middle of an entry and
    # the words the text layer runs together ("ResultanteSuscrito", "Datosregistrales")
    PAGE1 = ("BOLETÍN OFICIAL DEL REGISTRO MERCANTIL\nNúm. 57\nJueves 25 de marzo de 2021\nPág. 1\n"
             "cve: BORME-A-2021-57-08\nVerificable en https://www.boe.es\nSECCIÓN PRIMERA\nEmpresarios\n"
             "Actos inscritos\nBARCELONA\n"
             "138541 - EVERYDAY SOFTWARE SOLUTIONS SL.\nNombramientos. ADM.UNICO: OTRA PERSONA. Datos registrales. "
             "T 1 , F 1, S 8, H B 1, I/A 2 ( 1.03.21).\n"
             "138542 - EVERYDAY SOFTWARE SL.\nRevocaciones. CONSEJERO: SIMON SEBASTIAN SCHMINCKE. Nombramientos. "
             "CONSEJERO: REID MUELLER CHRISTIAN;PETER SPECHT. Ampliación de capital. Capital: 33.310,50 Euros.\n")
    PAGE2 = ("BOLETÍN OFICIAL DEL REGISTRO MERCANTIL\nNúm. 57\nJueves 25 de marzo de 2021\nPág. 2\n"
             "cve: BORME-A-2021-57-08\nVerificable en https://www.boe.es\n"
             "ResultanteSuscrito: 116.314,95 Euros. Datosregistrales. T 46340 , F 75, S 8, H B 493653, I/A 8 (16.03.21).\n"
             "138558 - EVERYDAY SOFTWARE SL.\nReducción de capital. Importe reducción: 9.336,45 Euros. Resultante "
             "Suscrito: 106.978,50 Euros. Datos registrales. T 47437 , F 11,S 8, H B 493653, I/A 10 (16.03.21).\n")
    FIRST = ("75997 - EVERYDAY SOFTWARE SL.\nConstitución. Comienzo de operaciones: 16.09.16. Domicilio: CL ALABA "
             "NUM.61 (BARCELONA). Capital: 15.000,00 Euros. Nombramientos. CONSEJERO: ROMERO VENTURES SL. REPR.143 RRM: "
             "ROMERO DE VILLALONGA JORDI. CONSEJERO: SIMON SEBASTIAN SCHMINCKE. Datos registrales. T 45613 , F 156, S 8, "
             "H B 493653, I/A 1 ( 7.11.16).\n")

    def es(self, pages, **kw):
        texts = {"https://www.boe.es/borme/dias/2016/11/15/pdfs/BORME-A-2016-217-08.pdf": self.FIRST,
                 "https://www.boe.es/borme/dias/2021/03/25/pdfs/BORME-A-2021-57-08.pdf": self.PAGE1 + "\n\n" + self.PAGE2}
        return list(mr.es_report("Everyday Software, S.L.", pages, fetcher=lambda u, accept=None: u.encode(),
                                 pdf_reader=lambda raw: texts[raw.decode()], **kw))

    def test_entries_parsed_across_a_page_break(self):
        out = self.es(["https://www.boe.es/borme/dias/2016/11/15/pdfs/BORME-A-2016-217-08.pdf",
                       "https://www.boe.es/borme/dias/2021/03/25/pdfs/BORME-A-2021-57-08.pdf"])
        entries = [r for r in out if r["type"] == "es_entry"]
        self.assertEqual([e["inscription"] for e in entries], [1, 8, 10])  # SOLUTIONS SL is another company
        self.assertEqual((entries[0]["inscribed"], entries[0]["address"]), ("2016-11-07", "CL ALABA NUM.61 (BARCELONA)"))
        self.assertEqual(entries[1]["capital"], [{"change": 33310.5, "resulting": 116314.95}])
        self.assertEqual(entries[2]["capital"], [{"change": -9336.45, "resulting": 106978.5}])
        self.assertEqual(entries[1]["cve"], "BORME-A-2021-57-08")
        summary = next(r for r in out if r["type"] == "es_summary")
        self.assertEqual(summary["capital"], 106978.5)
        board = {(o["role"], o["name"]) for o in summary["current_officers"]}
        self.assertIn(("CONSEJERO", "PETER SPECHT"), board)
        self.assertNotIn(("CONSEJERO", "SIMON SEBASTIAN SCHMINCKE"), board)  # appointed in 1, removed in 8
        self.assertIn(("REPR.143 RRM", "ROMERO DE VILLALONGA JORDI"), board)
        gap = next(r for r in out if r["type"] == "es_flag")
        self.assertEqual((gap["flag"], gap["missing"][:2]), ("inscriptions missing", [2, 3]))

    def test_dissolution_is_a_major_flag(self):
        body = ("Disolución. Voluntaria. Extinción. Datos registrales. T 1 , F 2, S 8, H B 9, I/A 3 (2.11.21).")
        acts, people, capital, reg = mr.borme_parse(body)
        self.assertEqual((acts[:2], reg["inscription"]), (["Disolución", "Extinción"], 3))
        text = "1 - ACME SL.\n" + body + "\n"
        out = list(mr.es_report("Acme", ["u"], fetcher=lambda u, accept=None: b"", pdf_reader=lambda raw: text))
        self.assertEqual([r["flag"] for r in out if r["type"] == "es_flag"], ["dissolution", "extinction"])

    def test_empresia_pages_and_daily_scan(self):
        pages = {"https://www.empresia.es/empresa/acme/":
                 '<a href="https://www.boe.es/borme/dias/2021/03/25/pdfs/BORME-A-2021-57-08.pdf">x</a>'
                 '<a href="/async/?t=EventosEntidad&amp;te=empresa&amp;x=1&amp;offset=30">more</a>',
                 "https://www.empresia.es/async/?t=EventosEntidad&te=empresa&x=1&offset=30":
                 '<a href="https://www.boe.es/borme/dias/2016/11/15/pdfs/BORME-A-2016-217-08.pdf">y</a>'}
        self.assertEqual(len(mr.empresia_borme_pdfs("https://www.empresia.es/empresa/acme/", pages.get)), 2)
        sumario = {"data": {"sumario": {"diario": [{"seccion": [
            {"codigo": "A", "item": [{"identificador": "BORME-A-2026-1-08", "url_pdf": {"texto": "https://b/a.pdf"}},
                                     {"identificador": "BORME-A-2026-1-28", "url_pdf": {"texto": "https://b/m.pdf"}}]},
            {"codigo": "C", "apartado": [{"nombre": "BALANCES", "item": {"titulo": "ACME, S.L. (EN LIQUIDACIÓN)",
                                                                         "url_pdf": {"texto": "https://b/c.pdf"}}}]}]}]}}}

        def get(url, accept=None):
            if "sumario/20260105" in url:
                return json.dumps(sumario).encode()
            if "sumario" in url:
                raise mr.FetchError(f"HTTP 404 for {url}")
            return b""
        out = list(mr.es_report("Acme SL", scan_from="2026-01-04", scan_to="2026-01-05", fetcher=get,
                                pdf_reader=lambda raw: "", pause=0))
        notice = next(r for r in out if r["type"] == "es_notice")
        self.assertEqual((notice["apartado"], notice["date"]), ("BALANCES", "2026-01-05"))
        self.assertEqual(next(r for r in out if r["type"] == "es_scan")["borme_days"], 1)

    def test_brazil_partners_and_special_situation(self):
        company = {"razao_social": "OI S.A. - EM RECUPERACAO JUDICIAL", "descricao_situacao_cadastral": "ATIVA",
                   "situacao_especial": "RECUPERACAO JUDICIAL", "data_situacao_especial": "2016-06-29",
                   "qsa": [{"nome_socio": "EVERYDAY SOFTWARE, S.L.", "pais": "ESPANHA", "cnpj_cpf_do_socio": "43637458",
                            "qualificacao_socio": "Sócio Pessoa Jurídica Domiciliado no Exterior",
                            "data_entrada_sociedade": "2021-11-16", "faixa_etaria": "Não se aplica",
                            "nome_representante_legal": "JOSE ROGERIO", "cpf_representante_legal": "***976708**",
                            "qualificacao_representante_legal": "Procurador"}]}

        def get(url):
            return json.dumps({"message": "2026-11"} if url.endswith("/updated") else company)
        out = list(mr.br_report("76.535.764/0001-43", get))
        self.assertEqual((out[0]["cnpj"], out[0]["data_month"]), ("76535764000143", "2026-11"))
        partner = out[1]
        self.assertEqual((partner["country"], partner["representative"]), ("ESPANHA", "JOSE ROGERIO"))
        self.assertNotIn("cpf_representante_legal", json.dumps(partner))  # no personal identifiers
        self.assertEqual(out[-1]["flag"], "special situation")
        self.assertEqual(list(mr.br_report("123", get))[0]["type"], "br_note")

    def test_factorial_ats_named_and_us_flag_says_match_first(self):
        page = '<link href="https://assets.factorialhr.com/ats/packs/css/CompanyPages/index.css">'

        def get(url):
            if "careers" in url:
                return page
            raise mr.FetchError(f"HTTP 404 for {url}")
        out = list(mr.jobs_report("https://careers.acme.test/", fetcher=get))
        self.assertEqual((out[-1]["type"], out[-1]["provider"]), ("jobs_board_unsupported", "factorial"))
        flag = mr.us_state_flag("CO", {"name": "Acme ! Inc", "status": "Delinquent"})
        self.assertIn("matched to the company", flag["match_first"])


class ItalyRunFixes(unittest.TestCase):
    def test_closed_company_has_no_overdue_flags(self):
        api = {"/company/09502116": {"company_name": "SATISPAY LIMITED", "company_status": "converted-closed",
                                     "type": "converted-or-closed", "date_of_cessation": "2019-05-17",
                                     "accounts": {"overdue": True}, "confirmation_statement": {"overdue": True}}}

        def fake(url, accept=None):
            path = url[len(mr.CH_API):].split("?")[0]
            if path in api:
                return json.dumps(api[path])
            raise mr.FetchError(f"HTTP 404 for {url}")
        out = list(mr.ch_report("09502116", mr.CompaniesHouse(None, fetcher=fake), today=dt.date(2026, 11, 25)))
        self.assertFalse([r for r in out if r.get("flag") in ("accounts overdue", "confirmation statement overdue")])
        self.assertTrue(out[0]["accounts_overdue"])  # the profile still says so; only the flag is held back

    def test_lu_reads_each_quarter_once_for_several_companies(self):
        def block(rcs, end, equity):
            return (f"<Declarer><RcsNumber>{rcs}</RcsNumber><LegalUnitName>{rcs} SA</LegalUnitName>"
                    f"<Declaration type=\"CA_BILAN\"><StartDate>{end[:4]}-01-01</StartDate><EndDate>{end}</EndDate>"
                    f"<RCSDepositDate>{end[:4]}-05-31</RCSDepositDate><ID_Doc>{rcs}{end}</ID_Doc><Currency>EUR</Currency>"
                    f"<Label>Capitaux propres</Label><Data>{equity}</Data></Declaration></Declarer>")
        calls = []

        def streamer(url, rcs):
            calls.append((url, rcs))
            return [block("B1", "2025-12-31", 10), block("B2", "2025-12-31", -5)]
        dataset = {"resources": [{"title": "deposit-2026q2.xml", "url": "u/2026q2"}]}
        out = list(mr.lu_report(["B1", "b 2"], fetcher=lambda u: json.dumps(dataset), streamer=streamer,
                                today=dt.date(2026, 11, 25)))
        self.assertEqual(calls, [("u/2026q2", ("B1", "B2"))])
        summaries = [r for r in out if r["type"] == "lu_summary"]
        self.assertEqual([(s["rcs"], s["flags"]) for s in summaries], [("B1", 0), ("B2", 1)])
        flag = next(r for r in out if r["type"] == "lu_flag")
        self.assertEqual((flag["rcs"], flag["flag"]), ("B2", "negative equity"))

    def test_ashby_posting_ages(self):
        today = dt.date.today()
        recent, old = (today - dt.timedelta(days=10)).isoformat(), (today - dt.timedelta(days=400)).isoformat()
        board = {"jobs": [{"title": "A", "department": "Tech", "location": "Milan", "publishedAt": recent + "T08:00:00Z"},
                          {"title": "B", "department": "Tech", "location": "Milan", "publishedAt": old + "T08:00:00Z"}]}
        out = list(mr.jobs_report("ashby:acme", fetcher=lambda u: json.dumps(board)))
        ages = next(r for r in out if r["type"] == "jobs_posting_ages")
        self.assertEqual((ages["dated_roles"], ages["oldest"], ages["newest"]), (2, old, recent))
        self.assertEqual(ages["posted_by_month"], {recent[:7]: 1})  # only the last 12 months are tallied

    def test_vat_name_or_hidden(self):
        italy = {"isValid": True, "name": "MOMENTUM S.P.A.", "address": "PIAZZA FIDIA 1 \n20159 MILANO MI\n",
                 "requestDate": "2026-11-25T00:00:00Z"}
        out = list(mr.vat_report("it", "IT 109 2736 0015", fetcher=lambda u: json.dumps(italy)))
        self.assertEqual((out[0]["vat_number"], out[0]["name"], out[0]["address"]),
                         ("IT10927360015", "MOMENTUM S.P.A.", "PIAZZA FIDIA 1, 20159 MILANO MI"))
        spain = {"isValid": True, "name": "---", "address": "---"}
        rec = list(mr.vat_report("ES", "B66854530", fetcher=lambda u: json.dumps(spain)))[0]
        self.assertIsNone(rec["name"])
        self.assertIn("does not disclose", rec["note"])
        self.assertEqual(list(mr.vat_report("US", "1"))[0]["type"], "vat_note")


class RegisterRecordsHelp(unittest.TestCase):
    SECTIONS = {"fr": "France", "lu": "Luxembourg", "ie": "Ireland", "il": "Israel", "es": "Spain",
                "br": "Brazil", "no": "Norway", "fi": "Finland", "dk": "Denmark"}

    def printed_types(self, cc):
        """Record types the country's own section of mr.py prints. Scoped to the section, since a
        file-wide prefix search for no_ also finds no_quote, no_url and other unrelated types."""
        source = pathlib.Path(mr.__file__).read_text(encoding="utf-8")
        start = re.search(r"^# -+ %s -+$" % self.SECTIONS[cc], source, re.M)
        self.assertIsNotNone(start, cc)
        end = re.compile(r"^# -+ ", re.M).search(source, start.end())
        return set(re.findall(r'"type": "(%s_[a-z_]+)"' % cc, source[start.end():end.start()]))

    def test_help_lists_exactly_the_record_types_each_command_prints(self):
        self.assertEqual(set(mr.REGISTER_RECORDS), set(self.SECTIONS))
        for cc in mr.REGISTER_RECORDS:
            own = set(re.findall(r"^  (%s_[a-z_]+)\s" % cc, mr.REGISTER_RECORDS[cc], re.M))
            shared = set(re.findall(r"^  (%s_[a-z_]+)\s" % cc, mr.register_help(cc), re.M)) - own
            printed = self.printed_types(cc)
            self.assertEqual(own - printed, set(), "%s --help lists records mr.py never prints" % cc)
            self.assertEqual(printed - own - shared, set(), "%s prints records its --help leaves out" % cc)

    def test_each_country_command_shows_its_records(self):
        for cc in mr.REGISTER_RECORDS:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                mr.main([cc, "--help"])
            self.assertIn("%s_flag" % cc, out.getvalue())


if __name__ == "__main__":
    unittest.main()
