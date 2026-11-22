"""Offline tests for mr.py parsers, run with: python -m unittest muckraker/scripts/test_mr.py"""

import datetime as dt
import gzip
import io
import json
import os
import pathlib
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

    def test_sec_contact_goes_to_sec_gov_only(self):
        sent = {}

        class Response(io.BytesIO):
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(request, timeout):
            # what urllib sends: unredirected headers win over ordinary ones
            sent[urllib.parse.urlparse(request.full_url).hostname] = (
                request.unredirected_hdrs.get("User-agent") or request.get_header("User-agent"))
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


if __name__ == "__main__":
    unittest.main()
