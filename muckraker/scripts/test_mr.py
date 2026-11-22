"""Offline tests for mr.py parsers, run with: python -m unittest muckraker/scripts/test_mr.py"""

import gzip
import io
import json
import pathlib
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
