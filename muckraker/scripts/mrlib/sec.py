"""SEC EDGAR: filer identity and filings, XBRL facts, full-text search, lender and fund marks, Form D."""

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from . import common, us


# ---------------------------------------------------------------- EDGAR ----

def parse_submissions(data, limit):
    recent = data.get("filings", {}).get("recent", {})
    cik = data.get("cik", "")
    yield {
        "type": "filer",
        "cik": common.cik10(cik),
        "name": data.get("name"),
        "former_names": [f.get("name") for f in data.get("formerNames", [])],
        "state_of_incorporation": data.get("stateOfIncorporation") or None,
        "sic": data.get("sic") or None,
        "sic_description": data.get("sicDescription") or None,
        "tickers": data.get("tickers", []),
        "business_address": data.get("addresses", {}).get("business"),
        "fiscal_year_end": data.get("fiscalYearEnd") or None,
        "url": f"https://data.sec.gov/submissions/CIK{common.cik10(cik)}.json",
    }
    forms = recent.get("form", [])
    for i in range(min(limit, len(forms))):
        acc = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        yield {
            "type": "filing",
            "form": forms[i],
            "filed": recent["filingDate"][i],
            "report_date": recent.get("reportDate", [""] * len(forms))[i] or None,
            "accession": acc,
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
        }


FACT_CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}


def parse_companyfacts(data, years):
    """Annual values per fiscal year for the FACT_CONCEPTS, from 10-K / 20-F."""
    gaap = data.get("facts", {}).get("us-gaap", {})
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{common.cik10(data.get('cik', 0))}.json"
    table = {}
    for field, concepts in FACT_CONCEPTS.items():
        for concept in concepts:
            units = gaap.get(concept, {}).get("units", {})
            values = units.get("USD", [])
            found = False
            for v in values:
                if v.get("fp") != "FY" or v.get("form") not in ("10-K", "20-F", "10-K/A", "20-F/A"):
                    continue
                if "start" in v:  # duration: keep full-year periods only
                    days = (dt.date.fromisoformat(v["end"]) - dt.date.fromisoformat(v["start"])).days
                    if not 350 <= days <= 380:
                        continue
                row = table.setdefault(v["end"], {})
                # later filings restate earlier ones; keep the latest filed value
                if field not in row or v.get("filed", "") > row[field]["filed"]:
                    row[field] = {"value": v["val"], "concept": concept, "accession": v.get("accn"), "filed": v.get("filed")}
                found = True
            if found:
                break
    for period_end in sorted(table, reverse=True)[:years]:
        row = table[period_end]
        yield {
            "type": "annual_figures",
            "period_end": period_end,
            "currency": "USD",
            "figures": {k: v["value"] for k, v in row.items()},
            "concepts": {k: v["concept"] for k, v in row.items()},
            "accessions": sorted({v["accession"] for v in row.values() if v["accession"]}),
            "url": url,
        }


def search_url(query, forms, start, end, offset=0):
    params = {"q": f'"{query}"'}
    if forms:
        params["forms"] = ",".join(forms)
    if start or end:
        params.update({"dateRange": "custom", "startdt": start or "2001-01-01", "enddt": end or dt.date.today().isoformat()})
    if offset:
        params["from"] = str(offset)
    return "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)


def search_web_url(query, forms, start):
    """The EDGAR full-text search page for the same query, for a reader to open."""
    params = {"q": f'"{query}"'}
    if forms:
        params["forms"] = ",".join(forms)
    if start:
        params.update({"dateRange": "custom", "startdt": start, "enddt": dt.date.today().isoformat()})
    return "https://www.sec.gov/edgar/search/#/" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def parse_search_hits(data):
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        adsh, _, filename = hit["_id"].partition(":")
        cik = src["ciks"][0] if src.get("ciks") else ""
        yield {
            "type": "search_hit",
            "filer": (src.get("display_names") or [""])[0],
            "cik": cik,
            "form": src.get("form"),
            "filed": src.get("file_date"),
            "period_ending": src.get("period_ending"),
            "accession": adsh,
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{filename}" if cik else None,
        }


def edgar_search(query, forms, start, end, user_agent, max_hits):
    """Return (hits, summary). The summary says how many filings EDGAR matched
    and whether --max-hits cut the list short."""
    hits, offset, total = [], 0, 0
    while len(hits) < max_hits:
        data = json.loads(common.fetch(search_url(query, forms, start, end, offset), user_agent))
        page = list(parse_search_hits(data))
        hits.extend(page)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        offset += len(page)
        if not page or offset >= total:
            break
    hits = hits[:max_hits]
    summary = {"type": "search_summary", "phrase": query, "forms": forms or None,
               "total": total, "returned": len(hits), "truncated": len(hits) < total}
    if not total and forms and len(forms) > 1:
        # one unknown form name (EDGAR has "SCHEDULE 13D", not "SC 13D") empties the
        # whole list, so search each form on its own and report the ones that found nothing
        hits, summary = [], {"type": "search_summary", "phrase": query, "forms": forms,
                             "total": 0, "returned": 0, "truncated": False, "forms_with_no_hits": []}
        for form in forms:
            found, part = edgar_search(query, [form], start, end, user_agent, max_hits)
            hits += found
            summary["total"] += part["total"]
            if not part["total"]:
                summary["forms_with_no_hits"].append(form)
        hits = hits[:max_hits]
        summary["returned"] = len(hits)
        summary["truncated"] = len(hits) < summary["total"]
        summary["note"] = ("the combined search found nothing, so each form was searched alone; a form with no "
                           "hits may be misspelled (EDGAR uses names like SCHEDULE 13D and DEF 14A)")
    return hits, summary


# -------------------------------------------------------------- marks ------

HOLDING_CONCEPTS = {
    "us-gaap:InvestmentOwnedBalancePrincipalAmount": "principal",
    "us-gaap:InvestmentOwnedUnderlyingFaceAmountAtMarketValue": "principal",
    "us-gaap:InvestmentOwnedAtCost": "cost",
    "us-gaap:InvestmentOwnedAtFairValue": "fair_value",
    "us-gaap:InvestmentInterestRate": "interest_rate",
    "us-gaap:InvestmentBasisSpreadVariableRate": "spread",
    "us-gaap:InvestmentInterestRatePaidInKind": "pik_rate",
    "us-gaap:InvestmentOwnedBalanceShares": "shares",
    "us-gaap:InvestmentMaturityDate": "maturity",
}

_REVOLVER_RE = re.compile(r"revolv|delayed[- ]draw|\bDDTL\b", re.I)
_JV_RE = re.compile(r"\bJV\b|joint venture", re.I)
REVOLVER_NOTE = ("revolving or delayed-draw facility: fair value can include unfunded commitments, "
                 "so its mark is not comparable with a term loan's")
JV_NOTE = "held through a joint venture of the filer; it may duplicate the filer's direct position in the same loan"


def holding_notes(text, fair_value=None):
    notes = []
    if fair_value is not None and fair_value < 0:
        notes.append("negative fair value: the filer nets the funded amount's value against a discount on "
                     "the unfunded commitment, so no mark computed; with the unfunded amount from the "
                     "filer's unfunded-commitments table, implied mark = 100 x (fair value + unfunded) "
                     "/ (principal + unfunded)")
    elif _REVOLVER_RE.search(text):
        notes.append(REVOLVER_NOTE)
    if _JV_RE.search(text):
        notes.append(JV_NOTE)
    return notes


_CONTEXT_RE = re.compile(r"<xbrli:context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.S)
_TYPED_RE = re.compile(r"<xbrldi:typedMember\b[^>]*dimension=\"us-gaap:InvestmentIdentifierAxis\"[^>]*>(.*?)</xbrldi:typedMember>", re.S)
# Numbers and text facts are matched separately, and self-closing tags (<ix:nonNumeric ... />,
# empty facts) are skipped: otherwise a match runs on to the next closing tag and swallows
# the facts in between, such as an employee count inside a text block.
_NUMBER_FACT_RE = re.compile(r"<ix:nonFraction\b([^>]*?)(?<!/)>(.*?)</ix:nonFraction>", re.S)
_TEXT_FACT_RE = re.compile(r"<ix:nonNumeric\b([^>]*?)(?<!/)>(.*?)</ix:nonNumeric>", re.S)


class _Fact:
    __slots__ = ("kind", "attrs", "raw", "pos", "end")

    def __init__(self, kind, m):
        self.kind, self.attrs, self.raw, self.pos, self.end = kind, m.group(1), m.group(2), m.start(), m.end()


def printed_negative(doc, fact):
    """True when the page prints the fact as negative: in brackets, or with a minus
    sign. Markup between the bracket and the number is ignored."""
    shown = common.text_of(fact.raw)
    if re.fullmatch(r"[-−–—]?", shown):  # a dash printed for zero has no sign
        return False
    if re.match(r"[-−]", shown):
        return True
    before = common.text_of(doc[max(0, fact.pos - 300):fact.pos] + "<x>")
    after = common.text_of("<x>" + doc[fact.end:fact.end + 300])
    return before.endswith("(") and after.startswith(")")


def iter_facts(doc):
    """Inline XBRL facts in document order: kind ('nonFraction' or 'nonNumeric'),
    attributes, inner markup, and position."""
    facts = [_Fact("nonFraction", m) for m in _NUMBER_FACT_RE.finditer(doc)]
    facts += [_Fact("nonNumeric", m) for m in _TEXT_FACT_RE.finditer(doc)]
    return sorted(facts, key=lambda f: f.pos)
_TR_OPEN_RE = re.compile(r"<tr\b", re.I)


def row_text(row):
    """A table row's cells in order, ' | '-separated, without lone $ and % cells."""
    cells = [common.text_of(c) for c in re.findall(r"<t[dh]\b.*?</t[dh]>", row, re.S | re.I)]
    return " | ".join(c for c in cells if c and c not in ("$", "%"))


def enclosing_row(doc, pos):
    """Text of the visible table row around position `pos`, or None when `pos`
    is not inside a row (for example a fact in the hidden ix:header)."""
    if doc.rfind("<ix:header", 0, pos) > doc.rfind("</ix:header>", 0, pos):
        return None
    start = -1
    for m in _TR_OPEN_RE.finditer(doc, max(0, pos - 20000), pos):
        start = m.start()
    if start < 0 or doc.find("</tr>", start, pos) >= 0:
        return None
    end = doc.find("</tr>", pos)
    return row_text(doc[start:end]) if end >= 0 else None


def _attr(attrs, name):
    m = re.search(r'\b%s="([^"]*)"' % name, attrs)
    return m.group(1) if m else None


def _number(attrs, raw):
    s = common.text_of(raw).replace(",", "")
    if s in ("", "-", "—"):
        return 0.0
    try:
        value = float(s)
    except ValueError:
        return None
    scale = _attr(attrs, "scale")
    if scale:
        value *= 10 ** int(scale)
    if _attr(attrs, "sign") == "-":
        value = -value
    return value


# "amendment", not "amend": every BDC's Securities Act footnote says "as amended"
_FLAG_WORDS = re.compile(r"non-?accrual|paid[- ]in[- ]kind|\bPIK\b|\bamendment|restructur|\bdefault|forbear|waiver|\bmodification", re.I)


def _flagged_footnotes(doc, fact_ids):
    """Footnotes linked to the given facts (inline XBRL fact-footnote
    relationships) whose text mentions non-accrual, PIK, an amendment, a default
    or a waiver. Returns {row key: {footnote text}}."""
    if not fact_ids:
        return {}
    links = {}
    for attrs in re.findall(r"<ix:relationship\b([^>]*)>", doc):
        from_refs = set((_attr(attrs, "fromRefs") or "").split()) & fact_ids.keys()
        if not from_refs:
            continue
        for to in (_attr(attrs, "toRefs") or "").split():
            links.setdefault(to, set()).update(from_refs)
    if not links:
        return {}
    flagged = {}
    for fn_attrs, body in re.findall(r"<ix:footnote\b([^>]*)>(.*?)</ix:footnote>", doc, re.S):
        fid = _attr(fn_attrs, "id")
        text = common.text_of(body)
        if fid in links and _FLAG_WORDS.search(text):
            for fact in links[fid]:
                flagged.setdefault(fact_ids[fact], set()).add(text)
    return flagged


SHORT_ALIAS = 6  # aliases this short also match loan codes in consumer-loan pools


def alias_in(alias, text):
    """True when `alias` appears in `text` as whole words: not inside a longer word
    ("Pleo" in "Pleorama"), and for a short alias not as the prefix of a loan code
    such as "PLEO-MZHJ" (a hyphenated token with a digit or no vowel), which pools
    of consumer loans list by the thousand."""
    a = alias.lower()
    for m in re.finditer(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text.lower()):
        code = re.match(r"-(\w+)", text[m.end():])
        if code and len(a) <= SHORT_ALIAS and (re.search(r"\d", code.group(1))
                                               or not re.search(r"[aeiouy]", code.group(1), re.I)):
            continue
        return True
    return False


def parse_ixbrl_holdings(doc, aliases):
    """Schedule-of-investments rows whose investment identifier names an alias.

    Uses the inline XBRL tags BDCs attach to each row (InvestmentIdentifierAxis),
    so the values are the filed numbers, already scaled.
    """
    contexts = {}
    for cid, body in _CONTEXT_RE.findall(doc):
        typed = _TYPED_RE.search(body)
        if not typed:
            continue
        ident = common.text_of(typed.group(1))
        if not any(alias_in(a, ident) for a in aliases):
            continue
        instant = re.search(r"<xbrli:instant>([^<]+)", body)
        end = re.search(r"<xbrli:endDate>([^<]+)", body)
        contexts[cid] = (ident, (instant or end).group(1) if (instant or end) else None, bool(instant))
    if not contexts:
        return []
    rows, durations, fact_ids, fv_pos = {}, {}, {}, {}
    for fact in iter_facts(doc):
        attrs, raw = fact.attrs, fact.raw
        cid = _attr(attrs, "contextRef")
        if cid not in contexts:
            continue
        ident, date, is_instant = contexts[cid]
        fid = _attr(attrs, "id")
        if fid:
            fact_ids[fid] = (ident, date) if is_instant else (ident, None)
        field = HOLDING_CONCEPTS.get(_attr(attrs, "name"))
        if not field:
            continue
        value = common.text_of(raw) if field == "maturity" else _number(attrs, raw)
        if value is None:
            continue
        if field in ("interest_rate", "spread", "pik_rate") and _attr(attrs, "scale") == "-2":
            value = round(value * 100, 4)  # back to percent as printed
        if is_instant:
            rows.setdefault((ident, date), {})[field] = value
            if field == "fair_value":
                fv_pos[(ident, date)] = fact.pos
        else:
            durations.setdefault(ident, {})[field] = value
    flagged = _flagged_footnotes(doc, fact_ids)
    out = []
    for (ident, date), fields in rows.items():
        for k, v in durations.get(ident, {}).items():
            fields.setdefault(k, v)
        record = {"identifier": ident, "as_of": date, **fields}
        footnotes = sorted(flagged.get((ident, date), set()) | flagged.get((ident, None), set()))
        if footnotes:
            record["flagged_footnotes"] = footnotes
        if fields.get("principal", 0) > 0 and fields.get("fair_value", -1) >= 0:
            record["mark"] = round(100 * fields["fair_value"] / fields["principal"], 1)
        notes = holding_notes(ident, fields.get("fair_value"))
        if notes:
            record["notes"] = notes
        quote = enclosing_row(doc, fv_pos[(ident, date)]) if (ident, date) in fv_pos else None
        if quote:
            record["quote"] = quote  # the row as the page shows it, for a red flag's quote
        out.append(record)
    return sorted(out, key=lambda r: (r["identifier"], r["as_of"] or ""))


_HOLDING_WORDS = re.compile(r"\b(lien|loan|revolv\w*|term|notes?|bonds?|units|shares|membership|preferred|warrants?|sofr|libor)\b", re.I)


_AMOUNT_RE = re.compile(r"\d[\d,.]{3,}")
_DATE_RE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                      r"\s+\d{1,2},\s+\d{4}\b")


def table_date(doc, table_start, lookback=30000, heading_chars=600):
    """The last full date ("September 30, 2026") in the text just before a table,
    usually its "Schedule of Investments as of ..." heading, as YYYY-MM-DD. Only
    the last `heading_chars` of text count, so a date further up (in a previous
    table or a footnote) is not taken for the heading's."""
    found = _DATE_RE.findall(common.text_of(doc[max(0, table_start - lookback):table_start])[-heading_chars:])
    if not found:
        return None
    try:
        return dt.datetime.strptime(re.sub(r"\s+", " ", found[-1]), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_table_rows(doc, aliases):
    """Fallback for filings without row-level XBRL: table rows that name an alias
    and read like a holding (a loan, notes, units, shares...)."""
    out = []
    for tm in re.finditer(r"<table\b.*?</table>", doc, re.S | re.I):
        header = None
        for row in re.findall(r"<tr\b.*?</tr>", tm.group(0), re.S | re.I):
            line = row_text(row)
            if not line:
                continue
            # column headings: the first row with several cells and no amounts (a
            # schedule's heading often spans rows, the first holding a single word)
            if header is None and line.count(" | ") >= 2 and not _AMOUNT_RE.search(line):
                header = line
            if (any(alias_in(a, line) for a in aliases) and _HOLDING_WORDS.search(line)
                    and _AMOUNT_RE.search(line)):  # a holding row carries an amount
                record = {"row": line}
                if header:
                    record["header"] = header
                date = table_date(doc, tm.start())
                if date:
                    record["table_date"] = date
                notes = holding_notes(line)
                if notes:
                    record["notes"] = notes
                out.append(record)
    return out


NPORT_MAX = 2 * 1024 * 1024 * 1024  # N-PORT files are streamed, so a 400 MB fund file is fine


def _nport_record(sec, info, aliases):
    """One N-PORT holding (an invstOrSec element, namespaces dropped) as a record, or None
    when its name and title name none of the aliases."""
    def find_text(node, path):
        el = node.find(path)
        return el.text.strip() if el is not None and el.text else None

    name, title = find_text(sec, "name") or "", find_text(sec, "title") or ""
    if not any(alias_in(a, name) or alias_in(a, title) for a in aliases):
        return None
    record = {"fund": info.get("seriesName") or info.get("regName"), "as_of": info.get("repPdDate"),
              "name": name, "title": title}
    if info.get("seriesId"):  # stable when a fund is renamed
        record["series_id"] = info["seriesId"]
    raw = {}
    for tag in ("balance", "units", "curCd", "valUSD", "pctVal", "assetCat", "fairValLevel", "cusip", "lei"):
        v = find_text(sec, tag)
        if v is not None:
            raw[tag] = v
            record[tag] = float(v) if tag in ("balance", "valUSD", "pctVal") else v
    # values exactly as the file writes them, ready for a red-flag quote
    record["quote"] = " ".join(f"<{t}>{v}</{t}>" for t, v in
                               [("name", find_text(sec, "name"))] + [(t, raw.get(t)) for t in ("balance", "valUSD")]
                               if v is not None)
    if record.get("units") == "NS" and record.get("balance") and "valUSD" in record:
        record["value_per_share"] = round(record["valUSD"] / record["balance"], 4)
    for tag in ("maturityDt", "couponKind", "annualizedRt", "isDefault", "areIntrstPmntsInArrs", "isPaidKind"):
        v = find_text(sec, f"debtSec/{tag}")
        if v is not None:
            record[tag] = v
    flags = [label for tag, label in (("isDefault", "in default"), ("areIntrstPmntsInArrs", "interest in arrears"),
                                      ("isPaidKind", "paid in kind")) if record.get(tag) == "Y"]
    if flags:  # the fund's own report on the loan, like a BDC's flagged footnotes
        record["fund_flags"] = flags
    if record.get("units") == "PA" and record.get("balance") and record.get("valUSD", -1) >= 0:
        record["mark"] = round(100 * record["valUSD"] / record["balance"], 1)
    notes = holding_notes(f"{name} {title}", record.get("valUSD"))
    if notes:
        record["notes"] = notes
    return record


class NportScan:
    """Reads an N-PORT file piece by piece, keeping only the matching holdings, so a
    fund that lists hundreds of thousands of loans never sits in memory whole."""
    _INFO = ("repPdDate", "seriesName", "regName", "seriesId")

    def __init__(self, aliases):
        self.aliases, self.info, self.out = aliases, {}, []
        self.parser = ET.XMLPullParser(events=("end",))

    def feed(self, data):
        self.parser.feed(data)
        self._drain()

    def close(self):
        self.parser.close()
        self._drain()
        return self.out

    def _drain(self):
        for _, el in self.parser.read_events():
            tag = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
            if tag in self._INFO and el.text and el.text.strip():
                self.info.setdefault(tag, el.text.strip())
            elif tag == "invstOrSec":
                for sub in el.iter():  # drop namespaces so paths stay simple
                    if isinstance(sub.tag, str):
                        sub.tag = sub.tag.rsplit("}", 1)[-1]
                record = _nport_record(el, self.info, self.aliases)
                if record:
                    self.out.append(record)
                el.clear()


def parse_nport_holdings(doc, aliases):
    """N-PORT holdings whose name or title names an alias."""
    scan = NportScan(aliases)
    scan.feed(doc.encode("utf-8") if isinstance(doc, str) else doc)
    return scan.close()


def fetch_nport_holdings(url, user_agent, aliases):
    """Stream an N-PORT file from sec.gov through NportScan, without the usual size cap."""
    scan = NportScan(aliases)
    common.fetch_bytes(url, user_agent, retries=0, limit=NPORT_MAX, sink=scan.feed)  # no retry: the parser has the start
    return scan.close()


SAME_BATCH_DAYS = 10  # filings a filer makes within this many days count as one batch
TARGET_WINDOW_DAYS = 90  # an earlier batch must fall this close to its target date


def choose_filings(hits, per_filer):
    """Per filer: the latest batch of filings, then the batches closest to evenly
    spaced points over the year before it. Returns (documents, notes).

    A batch is every filing the filer made within SAME_BATCH_DAYS of each other, so
    a trust's separate N-PORT filings for each fund are compared fund with fund.
    Every matching document of each filing is returned (a 10-Q can carry the
    schedule in an exhibit as well as the main document). An earlier point with no
    batch within TARGET_WINDOW_DAYS is skipped and reported in the notes, rather
    than replaced by a filing from a different period.
    """
    by_filer = {}
    for h in hits:
        if h["url"] and h["filed"]:
            by_filer.setdefault(h["cik"], {})[h["url"]] = h
    chosen, notes = [], []
    for docs in by_filer.values():
        dates = sorted({dt.date.fromisoformat(h["filed"]) for h in docs.values()}, reverse=True)

        def batch(anchor):
            return {d for d in dates if abs((d - anchor).days) <= SAME_BATCH_DAYS}

        latest = dates[0]
        picked = batch(latest)
        for k in range(1, per_filer):
            target = latest - dt.timedelta(days=365 * k / (per_filer - 1))
            near = [d for d in dates if d not in picked and abs((d - target).days) <= TARGET_WINDOW_DAYS]
            if not near:
                any_doc = next(iter(docs.values()))
                notes.append({"type": "no_earlier_filing", "filer": any_doc["filer"], "cik": any_doc["cik"],
                              "latest_filed": latest.isoformat(), "wanted_around": target.isoformat(),
                              "note": f"no filing within {TARGET_WINDOW_DAYS} days of this date"})
                continue
            picked |= batch(min(near, key=lambda d: abs((d - target).days)))
        chosen.extend(h for h in docs.values() if dt.date.fromisoformat(h["filed"]) in picked)
    return chosen, notes


SEARCH_CAP = 1000  # hits read per alias and form group; EDGAR search ranks by relevance, not date


def fund_trend_notes(holdings, per_filer):
    """A trust files one N-PORT per fund, so a trust-level earlier filing can be a
    different fund's. Report each fund whose latest holding has no earlier point
    from the same fund."""
    if per_filer < 2:
        return []
    by_fund = {}
    for h in holdings:
        by_fund.setdefault(fund_key(h), []).append(h)
    trust_latest = {}
    for h in holdings:
        if h.get("as_of"):
            trust_latest[h["cik"]] = max(trust_latest.get(h["cik"], ""), h["as_of"])
    notes = []
    for (cik, _), rows in by_fund.items():
        dates = {r["as_of"] for r in rows if r.get("as_of")}
        latest = max(rows, key=lambda r: r.get("as_of") or "")
        fund = latest["fund"]
        # one point only, and a current one (a fund seen only in the earlier filing has since sold out)
        if len(dates) == 1 and (dt.date.fromisoformat(trust_latest[cik])
                                - dt.date.fromisoformat(latest["as_of"])).days <= TARGET_WINDOW_DAYS:
            notes.append({"type": "no_earlier_filing", "filer": latest["filer"], "cik": cik, "fund": fund,
                          "latest_as_of": latest.get("as_of"),
                          "note": "no earlier holding from this fund; the trust's other funds' filings are not comparable"})
    return notes


def fund_key(h):
    """A fund's identity across filings: its series id, or for a fund without one
    (a closed-end fund) its name with "&"/"and", case and punctuation evened out,
    since funds rename "Science and Technology" to "Science & Technology"."""
    if h.get("series_id"):
        return (h["cik"], h["series_id"])
    name = re.sub(r"\s*&\s*", " and ", (h.get("fund") or "").lower())
    return (h["cik"], " ".join(re.findall(r"\w+", name)))


def fund_mark_changes(holdings):
    """Per fund holding line, the change from its earliest to its latest point:
    value per share for shares, `mark` (value as a percentage of principal) for
    loans. Share lines are paired by an unchanged share count, loans by the same
    CUSIP or title (a fund often buys or sells part of a loan), and otherwise a
    fund's only line at each date is paired with itself."""
    by_fund = {}
    for h in holdings:
        kind = "shares" if h.get("value_per_share") is not None else "loan" if h.get("mark") is not None else None
        if kind and h.get("as_of"):
            by_fund.setdefault((fund_key(h), kind), {}).setdefault(h["as_of"], []).append(h)
    out = []
    for (_, kind), dates in by_fund.items():
        if len(dates) < 2:
            continue
        first, last = min(dates), max(dates)
        old, new = dates[first], dates[last]
        if kind == "shares":
            pairs = [(o, n, "share_count") for n in new for o in old if o["balance"] == n["balance"]]
        else:
            pairs = [(o, n, "cusip" if o.get("cusip") else "title") for n in new for o in old
                     if (o.get("cusip") and o.get("cusip") == n.get("cusip"))
                     or (not o.get("cusip") and o.get("title") and o.get("title") == n.get("title"))]
            if len(pairs) != len(new):  # titles that repeat across lines cannot tell them apart
                pairs = []
        if not pairs and len(old) == 1 and len(new) == 1:
            pairs = [(old[0], new[0], "only_line")]
        for o, n, paired_by in pairs:
            record = {"type": "fund_mark_change", "filer": n["filer"], "fund": n["fund"], "name": n["name"],
                      "paired_by": paired_by,
                      "from_as_of": first, "to_as_of": last, "from_url": o["url"], "to_url": n["url"]}
            path = []  # every point of the same line in between, so a drop in one quarter shows
            for d in sorted(dates):
                same = [h for h in dates[d] if paired_by == "only_line" and len(dates[d]) == 1
                        or paired_by == "share_count" and h["balance"] == n["balance"]
                        or paired_by == "cusip" and h.get("cusip") == n.get("cusip")
                        or paired_by == "title" and h.get("title") == n.get("title")]
                if same:
                    path.append({"as_of": d, "value": same[0]["value_per_share" if kind == "shares" else "mark"]})
            if len(path) > 2:
                record["path"] = path
            if kind == "shares":
                change = round(100 * (n["value_per_share"] / o["value_per_share"] - 1), 1) if o["value_per_share"] else None
                record.update({"shares": n["balance"], "from_per_share": o["value_per_share"],
                               "to_per_share": n["value_per_share"], "change_pct": change})
            else:
                record.update({"principal": n["balance"], "from_principal": o["balance"], "from_mark": o["mark"],
                               "to_mark": n["mark"], "change_points": round(n["mark"] - o["mark"], 1)})
            out.append(record)
    return out


GENERIC_ALIAS_HITS = 2000  # a borrower name matching more filings than this is probably a common word
OUTLIER_ALIAS_HITS = 500  # with another alias in the run: more hits than this, and
OUTLIER_RATIO = 10        # this many times the most specific alias, is a common word


def record_key(r):
    """Identity of a holding record, to skip ones an earlier run already printed."""
    return (r.get("url"), r.get("identifier") or r.get("name") or r.get("row"), r.get("title"), r.get("as_of"))


def load_seen(path):
    seen = set()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    seen.add(record_key(json.loads(line)))
                except ValueError:
                    continue
    return seen


def load_searched(path):
    """The aliases an earlier marks run searched, from its marks_search records."""
    searched = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type") == "marks_search":  # older files have no "searched" list
                    searched += r.get("searched", r.get("aliases")) or []
    return searched


def covering_alias(alias, searched):
    """The earlier alias whose search already found every filing naming `alias`:
    full-text search matches a phrase anywhere, so "Falcon" covers "Falcon Purchaser, Inc."."""
    for s in searched:
        if re.search(r"(?<!\w)" + re.escape(s.strip()) + r"(?!\w)", alias, re.I):
            return s
    return None


def skip_covered(aliases, searched):
    """Aliases an earlier search did not cover; report the others."""
    left = []
    for alias in aliases:
        by = covering_alias(alias, searched)
        if by:
            common.emit({"type": "already_searched", "alias": alias, "covered_by": by,
                  "note": f'an earlier search for "{by}" already matched every filing naming this alias'})
        else:
            left.append(alias)
    return left


def name_mismatch(record, aliases):
    """The longer aliases a holding fails to match when only a one-word alias found it: "Papaya" finds
    "Papaya Growth Opportunity Corp." while the borrower is "Papaya Global", so the row is probably another
    company. Empty when the row matches a multi-word alias, or no longer alias contains the word."""
    text = " ".join(str(record.get(k) or "") for k in ("identifier", "name", "title", "row", "issuer"))
    matched = [a for a in aliases if alias_in(a, text)]
    if not matched or any(len(a.split()) > 1 for a in matched):
        return []
    return [a for a in aliases if a not in matched
            and any(re.search(r"(?<!\w)" + re.escape(m) + r"(?!\w)", a, re.I) for m in matched)]


def marks(aliases, user_agent, since, per_filer, max_filers, verbose=False, seen=None):
    seen = seen or set()
    complete, by_alias = [], {}  # complete: aliases whose searches returned every hit
    for alias in sorted(aliases, key=len):  # broadest first, so it can cover the longer names
        by = covering_alias(alias, complete)
        if by:
            common.emit({"type": "already_searched", "alias": alias, "covered_by": by,
                  "note": f'a shorter alias in this run, "{by}", already matched every filing naming this alias'})
            continue
        whole, found_all, total = True, [], 0
        # separate searches, so a flood of fund filings cannot push lenders past the cap
        for forms in (["10-K", "10-Q"], ["NPORT-P"]):
            found, summary = edgar_search(alias, forms, since, None, user_agent, SEARCH_CAP)
            whole = whole and not summary["truncated"]
            found_all += found
            total += summary.get("total", 0) or 0
            if summary["truncated"] or verbose:
                common.emit(summary)
            if summary.get("total", 0) > GENERIC_ALIAS_HITS:
                common.emit({"type": "generic_alias", "alias": alias, "forms": forms, "total": summary.get("total"),
                      "note": "this name matches thousands of filings, so it is probably a common word; "
                              "results for it are mostly unrelated and the search was cut short"})
        by_alias[alias] = (found_all, total)
        if whole:
            complete.append(alias)
    hits = []
    for alias, (found, total) in by_alias.items():
        others = [t for a, (_, t) in by_alias.items() if a != alias and t]
        if others and total > OUTLIER_ALIAS_HITS and total > OUTLIER_RATIO * min(others):
            # an acquired product's name ("Fugue") can be an ordinary word in thousands of fund filings
            common.emit({"type": "generic_alias", "alias": alias, "total": total, "dropped": True,
                  "note": f"this name matched {total} filings, over {OUTLIER_RATIO} times the most specific "
                          "alias, so it is probably a common word; its filings were not read. Search it by "
                          "hand with the company name if it matters"})
            if alias in complete:
                complete.remove(alias)
            continue
        hits += found
    # lets --skip-seen skip covered aliases: only those searched in full can cover another
    search_urls = [search_web_url(a, forms, since) for a in by_alias for forms in (["10-K", "10-Q"], ["NPORT-P"])]
    common.emit({"type": "marks_search", "aliases": aliases, "searched": complete, "since": since, "urls": search_urls})
    # lenders (10-K/10-Q schedules) before funds (N-PORT), most recent first, so
    # --max-filers keeps the loan books and the freshest holders
    latest, lender = {}, set()
    for h in hits:
        latest[h["cik"]] = max(latest.get(h["cik"], ""), h["filed"] or "")
        if h["form"] in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
            lender.add(h["cik"])
    ranked = sorted(latest, key=lambda c: (c in lender, latest[c]), reverse=True)
    keep = set(ranked[:max_filers])
    chosen, notes = choose_filings([h for h in hits if h["cik"] in keep], per_filer)
    # an N-PORT filing's HTML exhibit repeats holdings its XML already gives in full
    has_xml = {h["accession"] for h in chosen if h["url"].lower().endswith(".xml")}
    chosen = [h for h in chosen if h["url"].lower().endswith(".xml") or h["accession"] not in has_xml
              or not h["form"].startswith("NPORT")]
    # a trust can attach the same schedule (one large HTML file) to every fund's
    # filing; read one copy per filer, file name, and month
    seen_docs, unique = set(), []
    for h in chosen:
        key = (h["cik"], h["url"].rsplit("/", 1)[-1].lower(), h["filed"][:7])
        if h["url"].lower().endswith(".xml") or key not in seen_docs:
            seen_docs.add(key)
            unique.append(h)
    holders, fund_rows, skipped, unread = set(), [], 0, []
    for filing in unique:
        base = {"filer": filing["filer"], "form": filing["form"], "filed": filing["filed"],
                "period_ending": filing["period_ending"], "url": filing["url"]}
        try:
            if filing["url"].lower().endswith(".xml"):
                rows, kind = fetch_nport_holdings(filing["url"], user_agent, aliases), "fund_holding"
            else:
                doc = common.fetch(filing["url"], user_agent)
                if filing["form"].startswith("NPORT"):  # an HTML exhibit in an N-PORT filing
                    rows, kind = parse_table_rows(doc, aliases), "table_row"
                else:
                    rows, kind = parse_ixbrl_holdings(doc, aliases), "loan_or_equity"
                    if not rows:
                        rows, kind = parse_table_rows(doc, aliases), "table_row"
        except common.FetchError as e:
            common.emit({**base, "type": "error", "error": str(e)})
            unread.append(filing["url"])
            continue
        except ET.ParseError as e:
            common.emit({**base, "type": "error", "error": f"could not parse: {e}"})
            unread.append(filing["url"])
            continue
        if not rows and verbose:  # usually a filer that names the borrower as a customer
            common.emit({**base, "type": "no_matching_rows"})
        if rows:
            holders.add(filing["cik"])
        for row in rows:
            record = {**base, "type": kind, **row}
            if record_key(record) in seen:  # already in the file this run appends to
                skipped += 1
                continue
            longer = name_mismatch(record, aliases)
            if longer:
                record["name_mismatch"] = {"lacks": longer, "note": "only a one-word alias matched this row, and it "
                                           "lacks the rest of the borrower's name: probably another company"}
            common.emit(record)
            if kind == "fund_holding":
                fund_rows.append({**base, **row, "cik": filing["cik"]})
    # trend gaps, only for filers that hold the borrower (a company naming it as a
    # customer has no trend to report)
    trust_level = {n["cik"] for n in notes}
    for note in notes:
        if note["cik"] in holders or verbose:
            common.emit(note)
    for note in fund_trend_notes(fund_rows, per_filer):
        if note["cik"] not in trust_level:  # the trust-level note already says it
            common.emit(note)
    for change in fund_mark_changes(fund_rows):
        common.emit(change)
    if not holders:  # say so, so an empty result is not mistaken for a failure
        if unread:
            common.emit({"type": "no_holdings_found", "aliases": aliases, "searched_since": since,
                  "filings_matched": len(hits), "urls": search_urls, "partial": True, "unread": unread,
                  "note": f"no filing read names these borrowers, but {len(unread)} could not be read (see the "
                          "error records), so this result is partial: open those filings, or say under Gaps that "
                          "they were not read"})
        else:
            common.emit({"type": "no_holdings_found", "aliases": aliases, "searched_since": since,
                  "filings_matched": len(hits), "urls": search_urls,
                  "note": "no lender schedule or fund holding names these borrowers; nothing failed. Cite the "
                          "full-text searches in urls"})
    if skipped:
        common.emit({"type": "already_seen", "skipped": skipped,
              "note": "records already in the --skip-seen file were left out, so appending does not double-count"})


# ---------------------------------------------------------------- Form D ----

def _xml_local(root):
    """Drop namespaces from every tag, so Form D documents with and without one parse alike."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.rsplit("}", 1)[1]
    return root


def _xt(el, path):
    found = el.find(path) if el is not None else None
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _money(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return text  # "Indefinite" and the like


_LEGAL_SUFFIXES = {"llc", "l.l.c", "inc", "lp", "l.p", "llp", "ltd", "corp", "corporation", "co", "plc", "gp"}
# issuers that invest in the company rather than being it: an SPV series, a fund, a syndicate vehicle
_VEHICLE_RE = re.compile(r"\ba series of\b|\bspv\b|\bfund\b|\bsyndicate\b|\bcapital partners\b", re.I)


def parse_form_d(xml_text):
    """The fields of a Form D primary_doc.xml that matter for an entity record and funding timeline."""
    root = _xml_local(ET.fromstring(xml_text))
    issuer = root.find("primaryIssuer")
    year = issuer.find("yearOfInc") if issuer is not None else None
    if year is not None and _xt(year, "value"):
        year_of_inc = _xt(year, "value")
    elif year is not None and year.find("overFiveYears") is not None:
        year_of_inc = "over five years before filing"
    elif year is not None and year.find("yetToBeFormed") is not None:
        year_of_inc = "yet to be formed"
    else:
        year_of_inc = None
    offering = root.find("offeringData")
    industry = _xt(offering, "industryGroup/industryGroupType")
    sales = offering.find("offeringSalesAmounts") if offering is not None else None
    first_sale = offering.find("typeOfFiling/dateOfFirstSale") if offering is not None else None
    people = []
    for p in root.iter("relatedPersonInfo"):
        first, middle, last = (_xt(p, f"relatedPersonName/{k}Name") for k in ("first", "middle", "last"))
        first, middle = (None if v and v.strip(" .-/").lower() in ("", "na", "n/a", "none") else v for v in (first, middle))
        if first and first.lower().strip(".,") in _LEGAL_SUFFIXES:  # an entity: "Sydecar" + "LLC"
            name = f"{last}, {first}" if last else first
        else:
            name = " ".join(filter(None, [first, middle, last]))
        people.append({"name": name, "relationships": [r.text.strip() for r in p.iter("relationship") if r.text],
                       **({"clarification": _xt(p, "relationshipClarification")}
                          if _xt(p, "relationshipClarification") else {})})
    previous = [v.text.strip() for lst in ("issuerPreviousNameList", "edgarPreviousNameList")
                for v in (issuer.findall(lst + "/value") if issuer is not None else []) if v.text and v.text.strip()]
    return {
        "issuer": _xt(issuer, "entityName"), "cik": _xt(issuer, "cik"),
        "jurisdiction": _xt(issuer, "jurisdictionOfInc"), "year_of_inc": year_of_inc,
        "entity_type": _xt(issuer, "entityType"),
        "address": ", ".join(filter(None, [_xt(issuer, "issuerAddress/city"), _xt(issuer, "issuerAddress/stateOrCountry")])) or None,
        "previous_names": [n for n in previous if n.lower() != "none"] or None,
        "industry": industry, "pooled_fund": bool(industry and "Pooled Investment Fund" in industry),
        "investor_vehicle": bool((industry and "Pooled Investment Fund" in industry)
                                 or _VEHICLE_RE.search(_xt(issuer, "entityName") or "")),
        "revenue_range": _xt(offering, "issuerSize/revenueRange") or _xt(offering, "issuerSize/aggregateNetAssetValueRange"),
        "exemptions": [i.text.strip() for i in offering.iter("item") if i.text] if offering is not None else [],
        "amendment": _xt(offering, "typeOfFiling/newOrAmendment/isAmendment") == "true",
        "first_sale": (_xt(first_sale, "value") or ("yet to occur" if first_sale is not None and first_sale.find("yetToOccur") is not None else None)),
        "securities": [el.tag.removeprefix("is").removesuffix("Type") for el in offering.findall("typesOfSecuritiesOffered/*")
                       if (el.text or "").strip() == "true"] if offering is not None else [],
        "total_offering": _money(_xt(sales, "totalOfferingAmount")), "total_sold": _money(_xt(sales, "totalAmountSold")),
        "total_remaining": _money(_xt(sales, "totalRemaining")),
        "sales_clarification": _xt(sales, "clarificationOfResponse"),  # often explains a gap with the announced round
        "investors": us._int_or_none(_xt(offering, "investors/totalNumberAlreadyInvested")),
        "related_persons": people,
    }


def formd_report(queries, user_agent, search=None, get=None, max_hits=40):
    """Form D filings found by EDGAR full-text search for each name (a company, a former name, or a founder),
    each parsed from its primary_doc.xml."""
    # EDGAR full-text search's "D" covers amendments too; "D,D/A" returns only the amendments
    search = search or (lambda q: edgar_search(q, ["D"], None, None, user_agent, max_hits))
    get = get or (lambda u: common.fetch(u, user_agent))
    seen, issuers, searched = set(), {}, []
    for q in queries:
        try:
            hits, summary = search(q)
        except common.FetchError as e:
            yield {"type": "formd_unavailable", "query": q, "error": str(e)}
            continue
        searched.append({"query": q, "filings": summary.get("total"), "truncated": summary.get("truncated"),
                         "url": search_web_url(q, ["D"], None)})
        for h in hits:
            if h["accession"] in seen or not h.get("cik"):
                continue
            seen.add(h["accession"])
            # the filing's own folder holds the raw XML; xslFormDX01/ holds a rendered copy
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(h['cik'])}/"
                   f"{h['accession'].replace('-', '')}/primary_doc.xml")
            try:
                d = parse_form_d(get(url))
            except (common.FetchError, ET.ParseError, AttributeError) as e:
                yield {"type": "formd_unavailable", "query": q, "url": url, "error": str(e)}
                continue
            yield {"type": "formd_filing", "query": q, "form": h.get("form"), "filed": h.get("filed"), **d, "url": url}
            i = issuers.setdefault(d["cik"] or d["issuer"], {
                "issuer": d["issuer"], "cik": d["cik"], "jurisdiction": d["jurisdiction"],
                "year_of_inc": d["year_of_inc"], "pooled_fund": d["pooled_fund"],
                "investor_vehicle": d["investor_vehicle"], "filings": 0, "first_filed": None,
                "last_filed": None, "people": set()})
            i["filings"] += 1
            i["first_filed"] = min(filter(None, [i["first_filed"], h.get("filed")]), default=None)
            i["last_filed"] = max(filter(None, [i["last_filed"], h.get("filed")]), default=None)
            i["people"].update(p["name"] for p in d["related_persons"])
    yield {"type": "formd_summary", "searched": searched,
           "issuers": [{**i, "people": sorted(i["people"])} for i in issuers.values()],
           "note": "full-text search matches the name anywhere in the filing, so an issuer can be an investor's fund "
                   "or SPV (`investor_vehicle`: a pooled fund, or named \"a Series of\", SPV, or Fund; check others such "
                   "as a syndicate LLC by hand) or a company that only names the person: match each issuer to the entity record "
                   "before using it. Each D/A restates its offering's running total, so take an offering's amount "
                   "from its latest filing and never add amendments together"}
