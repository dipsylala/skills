"""Offline tests for mr.py parsers, run with: python -m unittest muckraker/scripts/test_mr.py"""

import datetime as dt
import gzip
import io
import json
import os
import pathlib
import sys
import tempfile
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
