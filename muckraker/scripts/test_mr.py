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
