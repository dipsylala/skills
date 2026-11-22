#!/usr/bin/env python3
"""Deterministic fetchers for muckraker source agents.

Each command fetches one kind of public record and prints JSON lines, one
record per fact, each with the source URL and, where there is one, the exact
text from the document (`quote`) so the coordinator can confirm it.

sec.gov asks automated clients to identify themselves. Pass the name and email
the user gave with --user-agent "Name email" or the MUCKRAKER_SEC_UA
environment variable; commands that reach sec.gov refuse to run without one.

Standard library only; Python 3.9 or later.
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

SEC_MIN_INTERVAL = 0.15  # seconds between sec.gov requests (under 10 a second)
MAX_BODY = 100 * 1024 * 1024  # largest body, raw or decompressed; big BDC 10-Qs run to ~35 MB
_CHUNK = 64 * 1024
_last_sec_request = 0.0


class FetchError(Exception):
    pass


def read_body(stream, gzipped, limit=MAX_BODY):
    """Read a response body in chunks, never holding more than `limit` bytes of
    raw or decompressed data, so an oversized page or a gzip bomb fails cleanly."""
    out, size = [], 0
    raw_total = 0
    d = zlib.decompressobj(16 + zlib.MAX_WBITS) if gzipped else None
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        raw_total += len(chunk)
        if raw_total > limit:
            raise FetchError(f"response larger than {limit} bytes")
        if d is None:
            data = chunk
        else:
            data = d.decompress(chunk, limit - size + 1)
            if d.unconsumed_tail:
                raise FetchError(f"decompressed response larger than {limit} bytes")
        size += len(data)
        if size > limit:
            raise FetchError(f"decompressed response larger than {limit} bytes")
        out.append(data)
    if d is not None:
        tail = d.flush(limit - size + 1)
        size += len(tail)
        if size > limit or d.unconsumed_tail:
            raise FetchError(f"decompressed response larger than {limit} bytes")
        out.append(tail)
    return b"".join(out)


def fetch(url, user_agent, retries=2, auth=None, accept=None):
    """Return the decoded body of `url`."""
    return fetch_bytes(url, user_agent, retries, auth, accept).decode("utf-8", errors="replace")


def fetch_bytes(url, user_agent, retries=2, auth=None, accept=None):
    """Return the raw body of `url`. `auth` is sent as an Authorization header
    on this request only, never on a redirect (Companies House documents redirect
    to signed storage URLs that reject it). `user_agent` is the user's SEC contact,
    so it goes to sec.gov only; every other host gets a generic one."""
    global _last_sec_request
    host = urllib.parse.urlparse(url).hostname or ""
    is_sec = host == "sec.gov" or host.endswith(".sec.gov")
    if is_sec and not user_agent:
        raise FetchError("sec.gov needs --user-agent or MUCKRAKER_SEC_UA")
    headers = {"User-Agent": "muckraker", "Accept-Encoding": "gzip"}
    if accept:
        headers["Accept"] = accept
    for attempt in range(retries + 1):
        if is_sec:
            wait = SEC_MIN_INTERVAL - (time.monotonic() - _last_sec_request)
            if wait > 0:
                time.sleep(wait)
            _last_sec_request = time.monotonic()
        request = urllib.request.Request(url, headers=headers)
        if is_sec:  # unredirected, so a redirect to another host does not carry the contact
            request.add_unredirected_header("User-Agent", user_agent)
        if auth:
            request.add_unredirected_header("Authorization", auth)
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                return read_body(r, r.headers.get("Content-Encoding") == "gzip")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"HTTP {e.code} for {url}") from e
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"{e.reason} for {url}") from e


def emit(record):
    print(json.dumps(record, ensure_ascii=False))


def cik10(cik):
    m = re.fullmatch(r"\s*(?:CIK)?\s*(\d{1,10})\s*", str(cik), re.I)
    if not m:
        raise FetchError(f'not a CIK: {cik}. Find the company\'s CIK with: mr.py edgar-search "{cik}", '
                         f"or https://www.sec.gov/cgi-bin/browse-edgar?company={urllib.parse.quote(str(cik))}")
    return m.group(1).zfill(10)


_INVISIBLE_RE = re.compile("[­​‌‍⁠﻿]")  # soft hyphens, zero-width characters


def text_of(fragment):
    """Visible text of an HTML/XML fragment, whitespace collapsed and invisible
    characters (soft hyphens such as &shy;, zero-width spaces) removed."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", text)).strip()


# ---------------------------------------------------------------- EDGAR ----

def parse_submissions(data, limit):
    recent = data.get("filings", {}).get("recent", {})
    cik = data.get("cik", "")
    yield {
        "type": "filer",
        "cik": cik10(cik),
        "name": data.get("name"),
        "former_names": [f.get("name") for f in data.get("formerNames", [])],
        "state_of_incorporation": data.get("stateOfIncorporation") or None,
        "sic": data.get("sic") or None,
        "sic_description": data.get("sicDescription") or None,
        "tickers": data.get("tickers", []),
        "business_address": data.get("addresses", {}).get("business"),
        "fiscal_year_end": data.get("fiscalYearEnd") or None,
        "url": f"https://data.sec.gov/submissions/CIK{cik10(cik)}.json",
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
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10(data.get('cik', 0))}.json"
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
        data = json.loads(fetch(search_url(query, forms, start, end, offset), user_agent))
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
    shown = text_of(fact.raw)
    if re.fullmatch(r"[-−–—]?", shown):  # a dash printed for zero has no sign
        return False
    if re.match(r"[-−]", shown):
        return True
    before = text_of(doc[max(0, fact.pos - 300):fact.pos] + "<x>")
    after = text_of("<x>" + doc[fact.end:fact.end + 300])
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
    cells = [text_of(c) for c in re.findall(r"<t[dh]\b.*?</t[dh]>", row, re.S | re.I)]
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
    s = text_of(raw).replace(",", "")
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
        text = text_of(body)
        if fid in links and _FLAG_WORDS.search(text):
            for fact in links[fid]:
                flagged.setdefault(fact_ids[fact], set()).add(text)
    return flagged


def parse_ixbrl_holdings(doc, aliases):
    """Schedule-of-investments rows whose investment identifier names an alias.

    Uses the inline XBRL tags BDCs attach to each row (InvestmentIdentifierAxis),
    so the values are the filed numbers, already scaled.
    """
    wanted = [a.lower() for a in aliases]
    contexts = {}
    for cid, body in _CONTEXT_RE.findall(doc):
        typed = _TYPED_RE.search(body)
        if not typed:
            continue
        ident = text_of(typed.group(1))
        if not any(a in ident.lower() for a in wanted):
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
        value = text_of(raw) if field == "maturity" else _number(attrs, raw)
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
    found = _DATE_RE.findall(text_of(doc[max(0, table_start - lookback):table_start])[-heading_chars:])
    if not found:
        return None
    try:
        return dt.datetime.strptime(re.sub(r"\s+", " ", found[-1]), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_table_rows(doc, aliases):
    """Fallback for filings without row-level XBRL: table rows that name an alias
    and read like a holding (a loan, notes, units, shares...)."""
    wanted = [a.lower() for a in aliases]
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
            if (any(a in line.lower() for a in wanted) and _HOLDING_WORDS.search(line)
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


def parse_nport_holdings(doc, aliases):
    """N-PORT holdings whose name or title contains an alias."""
    wanted = [a.lower() for a in aliases]
    root = ET.fromstring(doc.encode("utf-8"))
    for el in root.iter():  # drop namespaces so paths stay simple
        if isinstance(el.tag, str):
            el.tag = el.tag.rsplit("}", 1)[-1]

    def find_text(node, path):
        el = node.find(path)
        return el.text.strip() if el is not None and el.text else None

    period = find_text(root, ".//genInfo/repPdDate")
    fund = find_text(root, ".//genInfo/seriesName") or find_text(root, ".//genInfo/regName")
    series = find_text(root, ".//genInfo/seriesId")  # stable when a fund is renamed
    out = []
    for sec in root.iter("invstOrSec"):
        name, title = find_text(sec, "name") or "", find_text(sec, "title") or ""
        if not any(a in name.lower() or a in title.lower() for a in wanted):
            continue
        record = {"fund": fund, "as_of": period, "name": name, "title": title}
        if series:
            record["series_id"] = series
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
        out.append(record)
    return out


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
                if r.get("type") == "marks_search":
                    searched += r.get("aliases") or []
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
            emit({"type": "already_searched", "alias": alias, "covered_by": by,
                  "note": f'an earlier search for "{by}" already matched every filing naming this alias'})
        else:
            left.append(alias)
    return left


def marks(aliases, user_agent, since, per_filer, max_filers, verbose=False, seen=None):
    seen = seen or set()
    emit({"type": "marks_search", "aliases": aliases, "since": since})  # lets --skip-seen skip covered aliases
    hits, complete = [], []  # complete: aliases whose searches returned every hit
    for alias in sorted(aliases, key=len):  # broadest first, so it can cover the longer names
        by = covering_alias(alias, complete)
        if by:
            emit({"type": "already_searched", "alias": alias, "covered_by": by,
                  "note": f'a shorter alias in this run, "{by}", already matched every filing naming this alias'})
            continue
        whole = True
        # separate searches, so a flood of fund filings cannot push lenders past the cap
        for forms in (["10-K", "10-Q"], ["NPORT-P"]):
            found, summary = edgar_search(alias, forms, since, None, user_agent, SEARCH_CAP)
            whole = whole and not summary["truncated"]
            hits += found
            if summary["truncated"] or verbose:
                emit(summary)
            if summary.get("total", 0) > GENERIC_ALIAS_HITS:
                emit({"type": "generic_alias", "alias": alias, "forms": forms, "total": summary.get("total"),
                      "note": "this name matches thousands of filings, so it is probably a common word; "
                              "results for it are mostly unrelated and the search was cut short"})
        if whole:
            complete.append(alias)
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
    holders, fund_rows, skipped = set(), [], 0
    for filing in unique:
        base = {"filer": filing["filer"], "form": filing["form"], "filed": filing["filed"],
                "period_ending": filing["period_ending"], "url": filing["url"]}
        try:
            doc = fetch(filing["url"], user_agent)
        except FetchError as e:
            emit({**base, "type": "error", "error": str(e)})
            continue
        try:
            if filing["url"].lower().endswith(".xml"):
                rows, kind = parse_nport_holdings(doc, aliases), "fund_holding"
            elif filing["form"].startswith("NPORT"):  # an HTML exhibit in an N-PORT filing
                rows, kind = parse_table_rows(doc, aliases), "table_row"
            else:
                rows, kind = parse_ixbrl_holdings(doc, aliases), "loan_or_equity"
                if not rows:
                    rows, kind = parse_table_rows(doc, aliases), "table_row"
        except ET.ParseError as e:
            emit({**base, "type": "error", "error": f"could not parse: {e}"})
            continue
        if not rows and verbose:  # usually a filer that names the borrower as a customer
            emit({**base, "type": "no_matching_rows"})
        if rows:
            holders.add(filing["cik"])
        for row in rows:
            record = {**base, "type": kind, **row}
            if record_key(record) in seen:  # already in the file this run appends to
                skipped += 1
                continue
            emit(record)
            if kind == "fund_holding":
                fund_rows.append({**base, **row, "cik": filing["cik"]})
    # trend gaps, only for filers that hold the borrower (a company naming it as a
    # customer has no trend to report)
    trust_level = {n["cik"] for n in notes}
    for note in notes:
        if note["cik"] in holders or verbose:
            emit(note)
    for note in fund_trend_notes(fund_rows, per_filer):
        if note["cik"] not in trust_level:  # the trust-level note already says it
            emit(note)
    for change in fund_mark_changes(fund_rows):
        emit(change)
    if not holders:  # say so, so an empty result is not mistaken for a failure
        emit({"type": "no_holdings_found", "aliases": aliases, "searched_since": since,
              "filings_matched": len(hits),
              "note": "no lender schedule or fund holding names these borrowers; nothing failed"})
    if skipped:
        emit({"type": "already_seen", "skipped": skipped,
              "note": "records already in the --skip-seen file were left out, so appending does not double-count"})


# ---------------------------------------------------------------- GLEIF ----

GLEIF = "https://api.gleif.org/api/v1"
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
OFFSHORE = {  # ISO 3166 codes of common secrecy and offshore jurisdictions
    "VG": "British Virgin Islands", "KY": "Cayman Islands", "BM": "Bermuda", "JE": "Jersey",
    "GG": "Guernsey", "IM": "Isle of Man", "PA": "Panama", "SC": "Seychelles", "BS": "Bahamas",
    "BZ": "Belize", "MH": "Marshall Islands", "AI": "Anguilla", "TC": "Turks and Caicos Islands",
    "GI": "Gibraltar", "LI": "Liechtenstein", "MU": "Mauritius", "VU": "Vanuatu", "WS": "Samoa",
    "CW": "Curaçao", "KN": "Saint Kitts and Nevis", "LB": "Lebanon", "CK": "Cook Islands",
}


def gleif_json(path, fetcher=None):
    """GLEIF API response as a dict, or None for 404 (no such relationship)."""
    try:
        return json.loads((fetcher or (lambda u: fetch(u, None)))(GLEIF + path))
    except FetchError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def gleif_entity(record):
    a = record["attributes"]
    e, reg = a["entity"], a["registration"]
    addr = e.get("legalAddress") or {}
    hq = e.get("headquartersAddress") or {}

    def one_line(x):
        return ", ".join(p for p in [*(x.get("addressLines") or []), x.get("city"), x.get("region"),
                                     x.get("postalCode"), x.get("country")] if p) or None
    return {
        "lei": a["lei"],
        "legal_name": e["legalName"]["name"],
        "other_names": [n["name"] for n in e.get("otherNames") or []],
        "jurisdiction": e.get("jurisdiction"),
        "country": (e.get("jurisdiction") or "")[:2] or addr.get("country"),
        "legal_form": (e.get("legalForm") or {}).get("id"),
        "registered_as": e.get("registeredAs"),
        "registration_authority": ((e.get("registeredAt") or {}).get("id")),
        "entity_status": e.get("status"),
        "lei_status": reg.get("status"),
        "initial_registration": reg.get("initialRegistrationDate"),
        "last_update": reg.get("lastUpdateDate"),
        "next_renewal": reg.get("nextRenewalDate"),
        "legal_address": one_line(addr),
        "headquarters_address": one_line(hq),
        "url": f"{GLEIF}/lei-records/{a['lei']}",
    }


LEGAL_FORM_WORDS = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "lp", "plc", "corp", "corporation", "company", "co",
    "holdings", "holding", "group", "the", "and", "of", "sa", "ag", "gmbh", "bv", "nv", "sarl", "sas", "srl",
    "spa", "ab", "as", "asa", "oy", "kft", "sro", "pty", "pte", "kk", "se", "aps", "l", "p",
}


def distinctive_words(name):
    return {w for w in re.findall(r"\w+", name.lower()) if w not in LEGAL_FORM_WORDS and len(w) > 1}


def gleif_search(name, limit, fetcher=None):
    q = urllib.parse.urlencode({"filter[fulltext]": name, "page[size]": str(limit)})
    data = gleif_json(f"/lei-records?{q}", fetcher) or {"data": []}
    records = data.get("data", [])
    # full-text search ranks loose matches too ("Snyk, Inc." returns car dealers);
    # keep candidates whose name or other names share a word with the query beyond its legal form
    wanted, kept, dropped = distinctive_words(name), 0, 0
    for rec in records:
        ent = gleif_entity(rec)
        if wanted and not wanted & distinctive_words(" ".join([ent["legal_name"] or "", *ent["other_names"]])):
            dropped += 1
            continue
        kept += 1
        yield {"type": "gleif_candidate", **{k: ent[k] for k in (
            "lei", "legal_name", "jurisdiction", "registered_as", "entity_status", "lei_status", "legal_address", "url")}}
    if not kept:  # no LEI is itself a result; say so rather than print nothing
        note = "no LEI record matches this name; try another spelling or a parent's name"
        if dropped:
            note += f" ({dropped} loose matches sharing none of the name's words were left out)"
        yield {"type": "gleif_no_match", "query": name, "url": f"{GLEIF}/lei-records?{q}", "note": note}


def gleif_exception(lei, level, fetcher=None):
    data = gleif_json(f"/lei-records/{lei}/{level}-parent-reporting-exception", fetcher)
    return ((data or {}).get("data") or {}).get("attributes", {}).get("reason")


def gleif_children(lei, level, max_children, fetcher=None):
    out, page = [], 1
    while len(out) < max_children:
        data = gleif_json(f"/lei-records/{lei}/{level}-children?page[size]=100&page[number]={page}", fetcher)
        rows = (data or {}).get("data") or []
        out += [gleif_entity(r) for r in rows]
        last = ((data or {}).get("meta", {}).get("pagination") or {}).get("lastPage", 1)
        if not rows or page >= last:
            break
        page += 1
    return out[:max_children]


def gleif_report(lei, max_children=200, fetcher=None):
    """The entity, its parent chain (or why there is none), and its subsidiaries."""
    data = gleif_json(f"/lei-records/{lei}", fetcher)
    if not data:
        yield {"type": "error", "error": f"no LEI record {lei}"}
        return
    entity = gleif_entity(data["data"])
    yield {"type": "gleif_entity", **entity}

    chain, current, seen = [], lei, {lei}
    while len(chain) < 10:
        parent = gleif_json(f"/lei-records/{current}/direct-parent", fetcher)
        if not parent or not parent.get("data"):
            reason = gleif_exception(current, "direct", fetcher)
            yield {"type": "gleif_chain_end", "at_lei": current, "exception_reason": reason,
                   "note": "no direct parent reported" + (f" (reason: {reason})" if reason else "")}
            break
        p = gleif_entity(parent["data"])
        if p["lei"] in seen:
            break
        seen.add(p["lei"])
        chain.append(p)
        yield {"type": "gleif_parent", "level": len(chain), "child_lei": current, **p}
        current = p["lei"]
    ultimate = gleif_json(f"/lei-records/{lei}/ultimate-parent", fetcher)
    if ultimate and ultimate.get("data"):
        u = gleif_entity(ultimate["data"])
        if u["lei"] not in seen:
            yield {"type": "gleif_ultimate_parent", **u}
            chain.append(u)
    elif not chain:
        reason = gleif_exception(lei, "ultimate", fetcher)
        yield {"type": "gleif_no_ultimate_parent", "exception_reason": reason}

    offshore = [p for p in chain if p["country"] in OFFSHORE]
    for p in offshore:
        yield {"type": "gleif_flag", "flag": "offshore parent", "lei": p["lei"], "legal_name": p["legal_name"],
               "country": p["country"], "country_name": OFFSHORE[p["country"]], "url": p["url"]}

    kids = {k["lei"]: k for k in gleif_children(lei, "direct", max_children, fetcher)}
    for k in gleif_children(lei, "ultimate", max_children, fetcher):
        kids.setdefault(k["lei"], k)
    for k in kids.values():
        yield {"type": "gleif_child", **{f: k[f] for f in (
            "lei", "legal_name", "jurisdiction", "country", "entity_status", "lei_status", "url")}}
    countries = sorted({k["country"] for k in kids.values() if k["country"]})
    yield {"type": "gleif_summary", "lei": lei, "parents": len(chain), "children": len(kids),
           "child_countries": countries,
           "child_countries_outside_us_uk": [c for c in countries if c not in ("US", "GB")],
           "offshore_parents": [p["lei"] for p in offshore]}


# ------------------------------------------------------ Companies House ----

CH_API = "https://api.company-information.service.gov.uk"
CH_WEB = "https://find-and-update.company-information.service.gov.uk"
# statutory filing windows, in days after the event (Companies Act 2006)
OFFICER_FORMS = {"AP01", "AP02", "AP03", "AP04", "TM01", "TM02", "CH01", "CH02", "CH03", "CH04"}
PSC_FORMS = {f"PSC0{i}" for i in range(1, 10)}
GAZETTE_FORMS_RE = re.compile(r"^(GAZ\d|DISS|SOAS)", re.I)


class CompaniesHouse:
    def __init__(self, key, fetcher=None):
        if not key and fetcher is None:
            raise FetchError("Companies House commands need COMPANIES_HOUSE_API_KEY")
        import base64
        self.auth = "Basic " + base64.b64encode(f"{key}:".encode()).decode() if key else None
        self._fetch = fetcher or (lambda url, accept=None: fetch(url, None, auth=self.auth, accept=accept))

    def get(self, path):
        """API JSON, or None for 404."""
        try:
            return json.loads(self._fetch(CH_API + path))
        except FetchError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def document(self, metadata_url, accept):
        return self._fetch(metadata_url.rstrip("/") + "/content", accept=accept)

    def metadata(self, metadata_url):
        return json.loads(self._fetch(metadata_url))


def _date(s):
    return dt.date.fromisoformat(s) if s else None


def _add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.date(year, month, min(d.day, days))


def describe_filing(item):
    """Readable description from Companies House's description key and values."""
    values = item.get("description_values") or {}
    desc = (item.get("description") or "").replace("-", " ")
    extra = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in values.items() if isinstance(v, str))
    return f"{desc} ({extra})" if extra else desc


def website_quote(item):
    """The filing as the Companies House filing-history page prints it ("31 Oct 2024 AA"),
    so verify-report and quote-check can find it there."""
    d = _date(item.get("date"))
    return f"{d.strftime('%d %b %Y')} {item.get('type')}" if d else None


def covid_extension(due):
    """Hint when an accounts deadline fell in the COVID-19 period, when Companies House gave 3-month extensions."""
    if dt.date(2020, 3, 25) <= due <= dt.date(2021, 4, 5):
        return ("the deadline fell in the COVID-19 period: most accounts deadlines up to 5 April 2021 got an automatic "
                "3-month extension (Corporate Insolvency and Governance Act 2020); check")
    if dt.date(2021, 4, 6) <= due <= dt.date(2022, 4, 5):
        return ("the deadline fell in the COVID-19 period: Companies House granted 3-month extensions on application, "
                "accepted automatically for COVID-19 reasons; the register does not show whether one was granted; check")
    return None


def late_filing(item, company_type):
    """A flag record if a filing went in after its statutory deadline, else None."""
    form, filed, action = item.get("type", ""), _date(item.get("date")), _date(item.get("action_date"))
    values = item.get("description_values") or {}
    if not filed:
        return None
    if form in OFFICER_FORMS and action:
        limit, rule = 14, "officer changes must be filed within 14 days"
    elif form in PSC_FORMS and action:
        limit, rule = 28, "PSC changes: 14 days to update the register, then 14 days to file"
    elif form == "CS01" and action:
        limit, rule = 14, "confirmation statements must be filed within 14 days of the made-up date"
    elif form == "AA" and values.get("made_up_date"):  # not AAMD: amended accounts have no deadline of their own
        months = 6 if company_type == "plc" else 9
        due = _add_months(_date(values["made_up_date"]), months)
        if filed > due:
            return {"flag": "late accounts", "severity": "major", "form": form, "filed": filed.isoformat(),
                    "made_up_date": values["made_up_date"], "due": due.isoformat(), "days_late": (filed - due).days,
                    "rule": f"accounts due {months} months after the period end (first accounts and extensions differ; check)"}
        return None
    else:
        return None
    days = (filed - action).days
    if days > limit:
        return {"flag": "late filing", "severity": "minor", "form": form, "filed": filed.isoformat(), "event_date": action.isoformat(),
                "days_after_event": days, "days_late": days - limit, "rule": rule,
                "description": describe_filing(item)}
    return None


def ch_report(number, ch, max_filings=200, today=None, list_filings=25):
    """Profile, officers, PSCs, charges, insolvency, filing history and computed flags."""
    number = number.strip().upper()
    today = today or dt.date.today()
    web = f"{CH_WEB}/company/{number}"
    p = ch.get(f"/company/{number}")
    if not p:
        yield {"type": "error", "error": f"no company {number}"}
        return
    acc, cs = p.get("accounts") or {}, p.get("confirmation_statement") or {}
    yield {"type": "ch_profile", "company_number": number, "name": p.get("company_name"),
           "status": p.get("company_status"), "company_type": p.get("type"), "jurisdiction": p.get("jurisdiction"),
           "incorporated": p.get("date_of_creation"), "dissolved": p.get("date_of_cessation"),
           "registered_office": ", ".join(v for v in (p.get("registered_office_address") or {}).values() if v),
           "sic_codes": p.get("sic_codes") or [],
           "previous_names": [n.get("name") for n in p.get("previous_company_names") or []],
           "last_accounts": acc.get("last_accounts"), "next_accounts_due": acc.get("next_due"),
           "accounts_overdue": acc.get("overdue"), "confirmation_last": cs.get("last_made_up_to"),
           "confirmation_next_due": cs.get("next_due"), "confirmation_overdue": cs.get("overdue"),
           "has_charges": p.get("has_charges"), "has_insolvency_history": p.get("has_insolvency_history"),
           "registered_office_in_dispute": p.get("registered_office_is_in_dispute"), "url": web}
    overdue = 0
    for field, what in (("accounts_overdue", "accounts overdue"), ("confirmation_overdue", "confirmation statement overdue")):
        if (acc if field == "accounts_overdue" else cs).get("overdue"):
            overdue += 1
            yield {"type": "ch_flag", "flag": what, "severity": "major", "url": web}

    officers = (ch.get(f"/company/{number}/officers?items_per_page=100") or {}).get("items", [])
    recent = 0
    for o in officers:
        rec = {"type": "ch_officer", "name": o.get("name"), "role": o.get("officer_role"),
               "appointed_on": o.get("appointed_on"), "resigned_on": o.get("resigned_on"), "url": f"{web}/officers"}
        for d in (o.get("appointed_on"), o.get("resigned_on")):
            if d and (today - _date(d)).days <= 730:
                recent += 1
        yield rec
    yield {"type": "ch_officer_summary", "current": sum(1 for o in officers if not o.get("resigned_on")),
           "resigned": sum(1 for o in officers if o.get("resigned_on")),
           "appointments_and_resignations_last_24_months": recent}

    pscs = (ch.get(f"/company/{number}/persons-with-significant-control?items_per_page=100") or {}).get("items", [])
    for s in pscs:
        ident = s.get("identification") or {}
        yield {"type": "ch_psc", "name": s.get("name"), "kind": s.get("kind"),
               "natures_of_control": s.get("natures_of_control") or [], "notified_on": s.get("notified_on"),
               "ceased_on": s.get("ceased_on"), "country_of_residence": s.get("country_of_residence"),
               "registered_in": ident.get("country_registered") or ident.get("place_registered"),
               "registration_number": ident.get("registration_number"), "url": f"{web}/persons-with-significant-control"}
    statements, seen_statements = [], set()
    for s in (ch.get(f"/company/{number}/persons-with-significant-control-statements") or {}).get("items", []):
        key = (s.get("statement"), s.get("notified_on"), s.get("ceased_on"))
        if key in seen_statements:  # the register can hold the same statement twice
            continue
        seen_statements.add(key)
        statements.append(s)
        yield {"type": "ch_psc_statement", "statement": (s.get("statement") or "").replace("-", " "),
               "notified_on": s.get("notified_on"), "ceased_on": s.get("ceased_on"),
               "url": f"{web}/persons-with-significant-control"}

    # Always ask: the profile's has_charges can be stale (false while the register lists charges).
    charges = (ch.get(f"/company/{number}/charges?items_per_page=100") or {}).get("items", [])
    if not charges:
        yield {"type": "ch_charges", "count": 0, "url": f"{web}/charges",
               "note": "the charges register was read and lists no charges"}
    elif p.get("has_charges") is False:
        yield {"type": "ch_profile_mismatch", "field": "has_charges", "profile": False, "register_count": len(charges),
               "url": f"{web}/charges",
               "note": "the company profile says there are no charges, but the charges register lists these; "
                       "the register is right, so a tool that trusts the profile would miss them"}
    for c in charges:
        yield {"type": "ch_charge", "status": c.get("status"), "created_on": c.get("created_on"),
               "delivered_on": c.get("delivered_on"), "satisfied_on": c.get("satisfied_on"),
               "persons_entitled": [x.get("name") for x in c.get("persons_entitled") or []],
               "classification": (c.get("classification") or {}).get("description"),
               "charge_code": c.get("charge_code"), "url": f"{web}/charges"}
    if p.get("has_insolvency_history"):
        for case in (ch.get(f"/company/{number}/insolvency") or {}).get("cases", []):
            yield {"type": "ch_insolvency", "case_type": case.get("type"),
                   "dates": {d.get("type"): d.get("date") for d in case.get("dates") or []},
                   "practitioners": [x.get("name") for x in case.get("practitioners") or []],
                   "url": f"{web}/insolvency"}

    filings, start = [], 0
    while len(filings) < max_filings:
        page = ch.get(f"/company/{number}/filing-history?items_per_page=100&start_index={start}") or {}
        items = page.get("items") or []
        filings += items
        start += len(items)
        if not items or start >= page.get("total_count", 0):
            break
    filings = filings[:max_filings]
    counts = {"major": 0, "minor": 0, "minor_last_24_months": 0}
    appointed = {o.get("appointed_on") for o in officers if o.get("appointed_on")}
    ref_date_changes = [_date(f.get("date")) for f in filings if f.get("type") == "AA01" and f.get("date")]
    for i, f in enumerate(filings):
        quote = website_quote(f)
        if i < list_filings:  # every filing is checked for flags; only the latest are listed
            yield {"type": "ch_filing", "date": f.get("date"), "form": f.get("type"), "category": f.get("category"),
                   "description": describe_filing(f), "event_date": f.get("action_date"), "quote": quote,
                   "url": f"{web}/filing-history/{f.get('transaction_id')}/document?format=pdf"}
        late = late_filing(f, p.get("type"))
        if late and late["form"] in ("CH01", "CH02") and late.get("event_date") in appointed:
            late = None  # a details change dated on an appointment day is a correction, not a late change
        if late and late["flag"] == "late accounts":
            due = _date(late["due"])
            near = [d for d in ref_date_changes if due - dt.timedelta(days=550) <= d <= due]
            hints = []
            if near:
                hints.append(f"an AA01 (change of accounting reference date) was filed on "
                             f"{max(near).isoformat()}, which can move the deadline; check it")
            covid = covid_extension(due)
            if covid:
                hints.append(covid)
            if hints:
                late["possible_extension"] = "; ".join(hints)
        page_url = f"{web}/filing-history?page={i // 25 + 1}"  # the website lists 25 filings a page
        if late:
            counts[late["severity"]] += 1
            if late["severity"] == "minor" and (today - _date(late["filed"])).days <= 730:
                counts["minor_last_24_months"] += 1
            yield {"type": "ch_flag", **late, "quote": quote, "url": page_url}
        if GAZETTE_FORMS_RE.match(f.get("type") or ""):
            counts["major"] += 1
            yield {"type": "ch_flag", "flag": "gazette notice", "severity": "major", "form": f.get("type"), "filed": f.get("date"),
                   "description": describe_filing(f), "quote": quote, "url": page_url}
    yield {"type": "ch_summary", "company_number": number, "officers": len(officers), "pscs": len(pscs),
           "psc_statements": len(statements), "filings_read": min(len(filings), max_filings),
           "major_flags": counts["major"] + overdue, "minor_late_filings": counts["minor"],
           "minor_late_filings_last_24_months": counts["minor_last_24_months"],
           "note": ("minor flags are officer, PSC and confirmation-statement filings made late: register "
                    "housekeeping, worth reporting as a red flag only as a pattern (several in two years)")}


# ---------------------------------------------------------- UK accounts ----

UK_FIGURES = {  # field: local names in the UK FRS / IFRS taxonomies, first found wins
    "turnover": ["TurnoverRevenue", "Turnover", "Revenue", "RevenueFromContractsWithCustomers"],
    "gross_profit": ["GrossProfitLoss", "GrossProfit"],
    "operating_profit": ["OperatingProfitLoss", "ProfitLossFromOperatingActivities"],
    "profit_before_tax": ["ProfitLossOnOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax"],
    "net_profit": ["ProfitLoss", "ProfitLossForPeriod"],
    "cash": ["CashBankOnHand", "CashCashEquivalents", "CashAndCashEquivalents"],
    "current_assets": ["CurrentAssets"],
    "net_current_assets": ["NetCurrentAssetsLiabilities"],
    "net_assets": ["NetAssetsLiabilities", "Equity"],
    "bank_borrowings": ["BankBorrowings", "BankBorrowingsOverdrafts", "BankOverdrafts", "LoansFromBanks"],
    "owed_by_group": ["AmountsOwedByGroupUndertakings"],
    "owed_to_group": ["AmountsOwedToGroupUndertakings"],
    "operating_cash_flow": ["NetCashFlowsFromUsedInOperatingActivities", "NetCashGeneratedFromOperations"],
    "employees": ["AverageNumberEmployeesDuringPeriod"],
    "director_remuneration": ["DirectorRemuneration"],
}
UK_DURATION_FIELDS = {"turnover", "gross_profit", "operating_profit", "profit_before_tax", "net_profit",
                      "operating_cash_flow", "employees", "director_remuneration"}
UK_TEXT = {  # field: local names of text facts describing the accounts
    "accounts_type": ["AccountsType"], "audited": ["AccountsStatusAuditedOrUnaudited"],
    "standards": ["AccountingStandardsApplied"], "dormant": ["EntityDormantTruefalse"],
    "going_concern_basis": ["FinancialStatementsArePreparedOnGoing-concernBasisTruefalse"],
    "auditor": ["NameEntityAuditors", "NameSeniorStatutoryAuditorOnBehalfAuditor", "NameIndividualAuditor"],
    "period_start": ["StartDateForPeriodCoveredByReport"], "period_end": ["EndDateForPeriodCoveredByReport"],
}


def parse_uk_ixbrl(doc):
    """Figures per period end and the accounts' descriptive facts from iXBRL accounts.

    Uses facts with no dimension (the entity's own totals) or, for group accounts,
    the consolidated member, so segment and note breakdowns are left out."""
    contexts = {}
    for cid, body in _CONTEXT_RE.findall(doc):
        members = re.findall(r"<xbrldi:explicitMember\b[^>]*>([^<]+)<", body)
        typed = re.search(r"<xbrldi:typedMember", body)
        if typed or any("consolidated" not in m.lower() for m in members):
            continue
        consolidated = bool(members)
        instant = re.search(r"<xbrli:instant>([^<]+)", body)
        start = re.search(r"<xbrli:startDate>([^<]+)", body)
        end = re.search(r"<xbrli:endDate>([^<]+)", body)
        if instant:
            contexts[cid] = (instant.group(1), None, consolidated)
        elif start and end:
            contexts[cid] = (end.group(1), start.group(1), consolidated)
    local_to_field = {n: f for f, names in UK_FIGURES.items() for n in names}
    table, texts, negative = {}, {}, {}
    for fact in iter_facts(doc):
        kind, attrs, raw = fact.kind, fact.attrs, fact.raw
        name = (_attr(attrs, "name") or "").split(":")[-1]
        cid = _attr(attrs, "contextRef")
        if kind == "nonNumeric":
            for field, names in UK_TEXT.items():
                if name in names and field not in texts:
                    texts[field] = text_of(raw)
            continue
        field = local_to_field.get(name)
        if not field or cid not in contexts:
            continue
        end, start, consolidated = contexts[cid]
        if field in UK_DURATION_FIELDS:
            if not start or not 350 <= (_date(end) - _date(start)).days <= 380:
                continue
        elif start:
            continue
        value = _number(attrs, raw)
        if value is None:
            continue
        # UK filers often get the sign attribute wrong (Veracode Ltd tags a printed
        # inflow of 613,886 as negative and a printed (92,485) as positive), so the
        # printed sign decides, and a disagreement is reported
        tagged_neg = _attr(attrs, "sign") == "-" and value != 0
        shown_neg = printed_negative(doc, fact)
        value = -abs(value) if shown_neg else abs(value)
        row = table.setdefault(end, {})
        rank = UK_FIGURES[field].index(name) - (10 if consolidated else 0)  # group totals first, then preferred name
        if field not in row or rank < row[field][1]:
            row[field] = (value, rank)
            if tagged_neg != shown_neg:
                negative.setdefault(end, set()).add(field)
            else:
                negative.get(end, set()).discard(field)
    figures = {}
    for end, row in table.items():
        figures[end] = {f: v for f, (v, _) in row.items()}
        if negative.get(end):
            figures[end]["sign_mismatch"] = sorted(negative[end])
    return figures, texts


NOTE_TOPICS = {  # topic: phrase patterns, most specific first; earlier tiers fill the topic first
    "parent_and_control": [r"ultimate parent|ultimate controlling|controlling party|ultimate holding",
                           r"immediate parent|parent undertaking|smallest and largest group|consolidated financial statements .*obtained"],
    "going_concern": [r"going concern.{0,200}(support|letter|material uncertaint|significant doubt|depend)"
                      r"|(support|letter|depend).{0,200}going concern",
                      r"going concern"],
    "events_after_year_end": [r"post balance sheet|subsequent event|events? after the (?:reporting|balance sheet|end of)"],
    "debt_and_covenants": [r"covenant|borrowing facilit|loan facilit|secured on|security over"],
    "group_balances": [r"amounts? owed (?:by|to) (?:group|parent|related)|due (?:from|to) (?:group|parent|related) (?:undertaking|compan)"
                       r"|owed (?:to|by) the company (?:by|to) \S"
                       r"|(?:owed|due) (?:to|by|from) (?:its|the company's) (?:parent|fellow subsidiar|group)",
                       r"related part(?:y|ies)"],
}


def extract_notes(doc, per_topic=4, max_len=400):
    """Sentences from the accounts' text that mention the parent chain, going
    concern, events after the year end, or borrowing and covenants, so the notes
    can be read without opening the whole document."""
    text = text_of(re.sub(r"<(script|style|ix:header)\b.*?</\1>", " ", doc, flags=re.S | re.I))
    sentences = [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)]
    notes = {}
    for topic, tiers in NOTE_TOPICS.items():
        seen, picked = set(), []
        for pattern in tiers:
            for s in sentences:
                if len(picked) >= per_topic:
                    break
                key = s.lower()[:120]
                if key not in seen and re.search(pattern, s, re.I):
                    seen.add(key)
                    picked.append(s[:max_len])
        if picked:
            notes[topic] = picked
    return notes


def uk_accounts(number, ch, sets=3):
    """Multi-year figures from the latest accounts filings that have an iXBRL version."""
    number = number.strip().upper()
    web = f"{CH_WEB}/company/{number}"
    page = ch.get(f"/company/{number}/filing-history?category=accounts&items_per_page=50") or {}
    # the accounts category also holds forms that are not accounts, such as AA01 (change of accounting
    # reference date) and AA03 (auditor removal); keep accounts (AA), amended accounts and old dormant accounts
    filings = [f for f in page.get("items") or [] if f.get("type") in ("AA", "AAMD", "AA02")]
    if not filings:
        yield {"type": "uk_accounts_none", "url": f"{web}/filing-history?category=accounts",
               "note": "no accounts filed yet; a newly incorporated company's first accounts fall due "
                       "21 months after incorporation"}
        return
    combined, used, used_filings, scanned_newer = {}, 0, [], []
    for f in filings:
        if used >= sets:
            break
        meta_url = (f.get("links") or {}).get("document_metadata")
        doc_url = f"{web}/filing-history/{f.get('transaction_id')}/document?format=xhtml&download=1"
        base = {"filed": f.get("date"), "form": f.get("type"),
                "made_up_date": (f.get("description_values") or {}).get("made_up_date"),
                "description": describe_filing(f)}
        if not meta_url:
            yield {"type": "uk_accounts_unavailable", **base, "reason": "no document on file"}
            continue
        try:
            meta = ch.metadata(meta_url)
            if "application/xhtml+xml" not in (meta.get("resources") or {}):
                yield {"type": "uk_accounts_scanned", **base, "pages": meta.get("pages"),
                       "url": f"{web}/filing-history/{f.get('transaction_id')}/document?format=pdf",
                       "note": "filed as a PDF only, usually a scan with no text layer. Read it: run mr.py uk-pages "
                               "<url> <folder> and open the page images it writes, starting with the contents page. "
                               "Its figures may also appear as prior-year comparatives in the next accounts"}
                if not used and base["made_up_date"] not in scanned_newer:  # an amendment repeats the date
                    scanned_newer.append(base["made_up_date"])
                continue
            doc = ch.document(meta_url, "application/xhtml+xml")
        except FetchError as e:
            yield {"type": "error", **base, "error": str(e)}
            continue
        figures, texts = parse_uk_ixbrl(doc)
        used += 1
        kind = re.search(r"accounts type (\w+)", base["description"] or "")
        used_filings.append({"made_up_date": base["made_up_date"], "auditor": texts.get("auditor"),
                             "accounts_type": kind.group(1) if kind else None, "url": doc_url})
        yield {"type": "uk_accounts_filing", **base, **texts, "periods": sorted(figures, reverse=True), "url": doc_url}
        if used == 1:  # the latest accounts' notes
            if scanned_newer:
                yield {"type": "uk_accounts_latest_scanned", "scanned_made_up_dates": scanned_newer,
                       "notes_from": base["made_up_date"],
                       "note": "the newest accounts are scans with no text layer, so the notes and latest figures "
                               "here come from older accounts; read the newest scan before relying on them"}
            notes = extract_notes(doc)
            if notes:
                yield {"type": "uk_accounts_notes", **base, "notes": notes, "url": doc_url}
            latest = figures.get(max(figures)) if figures else {}
            if latest is not None and "bank_borrowings" not in latest:
                yield {"type": "uk_accounts_borrowings", **base, "bank_borrowings_tagged": False, "url": doc_url,
                       "note": "the latest accounts tag no bank borrowings or overdrafts; confirm in the "
                               "creditors note before reporting that the company has no borrowings"}
        for end, row in figures.items():
            # newer accounts restate earlier years, so a figure already taken from newer
            # accounts stays; older accounts only fill figures the newer ones lack
            have, urls = combined.setdefault(end, ({}, []))
            added = False
            for k, v in row.items():
                if k == "sign_mismatch":
                    continue
                if k not in have:
                    have[k] = v
                    added = True
                    if k in row.get("sign_mismatch", []):
                        have.setdefault("sign_mismatch", []).append(k)
            if added:
                urls.append(doc_url)
    for end in sorted(combined, reverse=True):
        row, urls = combined[end]
        figures = {k: v for k, v in row.items() if k != "sign_mismatch"}
        record = {"type": "uk_accounts_year", "period_end": end, "figures": figures, "sources": urls}
        if row.get("sign_mismatch"):
            record["sign_mismatch"] = sorted(row["sign_mismatch"])
            record["note"] = ("figures use the sign printed in the accounts, which is right; the filer's XBRL sign "
                              "tag disagrees for these, a tagging error by the filer, so a tool reading the tags "
                              "would show the opposite sign. Not a red flag")
        yield record
    ends = sorted(combined)
    for prev, cur in zip(ends, ends[1:]):
        a, b = combined[prev][0], combined[cur][0]
        derived = {}
        if a.get("turnover") and "turnover" in b:
            derived["turnover_growth_pct"] = round(100 * (b["turnover"] / a["turnover"] - 1), 1)
        if b.get("turnover") and "operating_profit" in b:
            derived["operating_margin_pct"] = round(100 * b["operating_profit"] / b["turnover"], 1)
        if "cash" in a and "cash" in b:
            derived["cash_change"] = b["cash"] - a["cash"]
        if a.get("employees") and "employees" in b:
            derived["employees_change_pct"] = round(100 * (b["employees"] / a["employees"] - 1), 1)
        if derived:
            yield {"type": "uk_accounts_derived", "period_end": cur, "versus": prev, **derived}
    for change in accounts_changes(used_filings):
        yield change


def _auditor_key(name):
    """An auditor's name without suffixes, so "Zome Audit Limited (Statutory Auditor)"
    and "Zome (Statutory Auditor)" count as the same firm."""
    s = re.sub(r"\(.*?\)|statutory auditors?|chartered accountants|registered auditors?", " ", (name or "").lower())
    s = re.sub(r"\b(audit|limited|ltd|llp|plc|uk|and|&)\b|[^a-z ]", " ", s)
    return " ".join(s.split())


def accounts_changes(used_filings):
    """Auditor and accounts-type changes between consecutive accounts, newest first in the input."""
    ordered = [f for f in reversed(used_filings) if f["made_up_date"]]
    for prev, cur in zip(ordered, ordered[1:]):
        if prev["auditor"] and cur["auditor"] and _auditor_key(prev["auditor"]) != _auditor_key(cur["auditor"]):
            yield {"type": "uk_accounts_change", "change": "auditor", "from": prev["auditor"], "to": cur["auditor"],
                   "between": [prev["made_up_date"], cur["made_up_date"]], "url": cur["url"]}
        if prev["accounts_type"] and cur["accounts_type"] and prev["accounts_type"] != cur["accounts_type"]:
            yield {"type": "uk_accounts_change", "change": "accounts type", "from": prev["accounts_type"],
                   "to": cur["accounts_type"], "between": [prev["made_up_date"], cur["made_up_date"]], "url": cur["url"]}


# ----------------------------------------------------------- page images -----
# Scanned accounts are PDFs of CCITT Group 4 fax images (or JPEGs). Decoding the fax
# images to PNG here lets an agent read them without pdftoppm, Pillow or OCR tools.

# T.4 run-length codes in run order: terminating codes for runs 0-63, then make-up codes for 64, 128, ... 2560.
_WHITE_TERM = """00110101 000111 0111 1000 1011 1100 1110 1111 10011 10100 00111 01000 001000 000011 110100 110101
    101010 101011 0100111 0001100 0001000 0010111 0000011 0000100 0101000 0101011 0010011 0100100 0011000 00000010
    00000011 00011010 00011011 00010010 00010011 00010100 00010101 00010110 00010111 00101000 00101001 00101010
    00101011 00101100 00101101 00000100 00000101 00001010 00001011 01010010 01010011 01010100 01010101 00100100
    00100101 01011000 01011001 01011010 01011011 01001010 01001011 00110010 00110011 00110100"""
_WHITE_MAKEUP = """11011 10010 010111 0110111 00110110 00110111 01100100 01100101 01101000 01100111 011001100 011001101
    011010010 011010011 011010100 011010101 011010110 011010111 011011000 011011001 011011010 011011011 010011000
    010011001 010011010 011000 010011011"""
_BLACK_TERM = """0000110111 010 11 10 011 0011 0010 00011 000101 000100 0000100 0000101 0000111 00000100 00000111
    000011000 0000010111 0000011000 0000001000 00001100111 00001101000 00001101100 00000110111 00000101000
    00000010111 00000011000 000011001010 000011001011 000011001100 000011001101 000001101000 000001101001
    000001101010 000001101011 000011010010 000011010011 000011010100 000011010101 000011010110 000011010111
    000001101100 000001101101 000011011010 000011011011 000001010100 000001010101 000001010110 000001010111
    000001100100 000001100101 000001010010 000001010011 000000100100 000000110111 000000111000 000000100111
    000000101000 000001011000 000001011001 000000101011 000000101100 000001011010 000001100110 000001100111"""
_BLACK_MAKEUP = """0000001111 000011001000 000011001001 000001011011 000000110011 000000110100 000000110101
    0000001101100 0000001101101 0000001001010 0000001001011 0000001001100 0000001001101 0000001110010
    0000001110011 0000001110100 0000001110101 0000001110110 0000001110111 0000001010010 0000001010011
    0000001010100 0000001010101 0000001011010 0000001011011 0000001100100 0000001100101"""
_SHARED_MAKEUP = """00000001000 00000001100 00000001101 000000010010 000000010011 000000010100 000000010101
    000000010110 000000010111 000000011100 000000011101 000000011110 000000011111"""


def _run_codes(term, makeup):
    codes = {c: run for run, c in enumerate(term.split())}
    codes.update({c: 64 * (i + 1) for i, c in enumerate((makeup + " " + _SHARED_MAKEUP).split())})
    return codes


_RUNS = (_run_codes(_WHITE_TERM, _WHITE_MAKEUP), _run_codes(_BLACK_TERM, _BLACK_MAKEUP))  # indexed by colour
# T.6 2D modes: a vertical offset (a1 = b1 + offset), "pass", "horizontal" or "end" (EOFB).
_MODES = {"1": 0, "011": 1, "010": -1, "000011": 2, "000010": -2, "0000011": 3, "0000010": -3,
          "0001": "pass", "001": "horizontal", "000000000001": "end"}


def _read_code(bits, p, table, longest):
    for n in range(1, longest + 1):
        value = table.get(bits[p:p + n])
        if value is not None:
            return value, p + n
    raise ValueError(f"bad CCITT code at bit {p}")


def _read_run(bits, p, colour):
    total = 0
    while True:
        run, p = _read_code(bits, p, _RUNS[colour], 13)
        total += run
        if run < 64:
            return total, p


def g4_rows(data, width, height):
    """Decode CCITT Group 4 (T.6) data: for each row, the positions where the colour
    changes, starting white (so black runs are [c0, c1), [c2, c3), ...)."""
    bits = bin(int.from_bytes(b"\x01" + data, "big"))[3:]
    p, ref = 0, [width] * 3
    for _ in range(height):
        cur, a0, colour, k = [], -1, 0, 0
        while a0 < width:
            while k > 0 and ref[k - 1] > a0:
                k -= 1
            while ref[k] <= a0 or k % 2 != colour:  # b1: next change on the row above to the opposite colour
                k += 1
            b1, b2 = ref[k], ref[k + 1]
            mode, p = _read_code(bits, p, _MODES, 12)
            if mode == "end":
                raise ValueError("data ends before the last row")
            if mode == "pass":
                a0 = b2
            elif mode == "horizontal":
                a0 = max(a0, 0)
                r1, p = _read_run(bits, p, colour)
                r2, p = _read_run(bits, p, 1 - colour)
                a1 = min(a0 + r1, width)
                a0 = min(a1 + r2, width)
                cur += [a1, a0]
            else:
                a0 = b1 + mode
                if not 0 <= a0 <= width:
                    raise ValueError(f"vertical code points outside the row ({a0})")
                cur.append(a0)
                colour = 1 - colour
        yield cur
        ref = cur + [width] * 3


# Limits on a fetched PDF's images, whose sizes the PDF itself declares: a scanned A4 page
# at 300 dpi is about 2500 x 3500 pixels, a 1 MB bitmap, from a ~100 KB fax stream.
MAX_PAGE_SIDE = 20000  # pixels; A0 at 600 dpi
MAX_PAGE_BITMAP = 64 * 1024 * 1024  # bytes of decoded 1-bit bitmap per page
MAX_PAGE_STREAM = 16 * 1024 * 1024  # bytes of encoded image data per page
MAX_PAGES = 1000


def _shrink_row(black, bits, scale, out_bits):
    """A row bitmap (pixel 0 in the top bit of `bits`) shrunk `scale` times: an
    output pixel is black when any of the `scale` input pixels it covers is."""
    spread = black
    for i in range(1, scale):
        spread |= black << i
    spread &= (1 << bits) - 1
    kept = format(spread, f"0{bits}b")[::scale]
    return int(kept.ljust(out_bits, "0")[:out_bits], 2)


def png_1bit(changes_by_row, width, height, invert=False, scale=1):
    """A black-and-white PNG from g4_rows output, optionally `scale` times smaller."""
    nbytes = (width + 7) // 8
    if not (0 < width <= MAX_PAGE_SIDE and 0 < height <= MAX_PAGE_SIDE) or (nbytes + 1) * height > MAX_PAGE_BITMAP:
        raise ValueError(f"image of {width} x {height} pixels is larger than a scanned page")
    out_w, out_h = -(-width // scale), -(-height // scale)
    out_bytes = (out_w + 7) // 8
    full = (1 << out_bytes * 8) - 1
    raw, block, rows_in_block = bytearray(), 0, 0

    def add(black):
        if scale > 1:
            black = _shrink_row(black, nbytes * 8, scale, out_bytes * 8)
        raw.extend(b"\x00" + (black if invert else full ^ black).to_bytes(out_bytes, "big"))  # PNG: 1 is white
    for changes in changes_by_row:
        black = 0
        for i in range(0, len(changes), 2):
            start, end = changes[i], changes[i + 1] if i + 1 < len(changes) else width
            if end > start:
                black |= ((1 << (end - start)) - 1) << (nbytes * 8 - end)
        block, rows_in_block = block | black, rows_in_block + 1
        if rows_in_block == scale:
            add(block)
            block, rows_in_block = 0, 0
    if rows_in_block:
        add(block)
    width, height = out_w, out_h

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


_PDF_STREAM_RE = re.compile(rb"\d+\s+\d+\s+obj((?:(?!endobj).)*?)\bstream\r?\n", re.S)


def pdf_images(pdf):
    """(dictionary, data) for each image in a PDF, in file order, which in scanned
    filings is page order."""
    for m in _PDF_STREAM_RE.finditer(pdf):
        d = m.group(1)
        if not re.search(rb"/Subtype\s*/Image\b", d):
            continue
        length, size = re.search(rb"/Length\s+(\d+)(?:\s+(\d+)\s+R)?", d), None
        if length and length.group(2):  # an indirect length: "8 0 R" points at "8 0 obj 12345 endobj"
            target = re.search(rb"\b%s\s+%s\s+obj\s*(\d+)\s*endobj" % (length.group(1), length.group(2)), pdf)
            size = int(target.group(1)) if target else None
        elif length:
            size = int(length.group(1))
        start = m.end()
        yield d, pdf[start:start + size] if size else pdf[start:pdf.find(b"endstream", start)].rstrip(b"\r\n")


def parse_pages(spec):
    """'1-3,7' -> {1, 2, 3, 7}"""
    pages = set()
    for part in filter(None, (x.strip() for x in spec.split(","))):
        lo, _, hi = part.partition("-")
        pages.update(range(int(lo), int(hi or lo) + 1))
    return pages


def page_images(pdf, out_dir, pages=None, scale=1):
    """Write each page image in a scanned PDF to out_dir as PNG (fax images) or JPEG.
    `scale` shrinks fax images that many times (JPEGs are saved as filed)."""
    os.makedirs(out_dir, exist_ok=True)
    count = written = 0
    for d, data in pdf_images(pdf):
        count += 1
        if count > MAX_PAGES:
            yield {"type": "error", "error": f"more than {MAX_PAGES} images; the rest were not read"}
            count -= 1
            break
        if pages and count not in pages:
            continue
        filters = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", d)
        filters = [f.decode() for f in re.findall(rb"/(\w+)", filters.group(1))] if filters else []
        size = re.search(rb"/Width\s+(\d+)", d), re.search(rb"/Height\s+(\d+)", d)
        width, height = (int(m.group(1)) for m in size) if all(size) else (None, None)
        base = {"image": count, "width": width, "height": height}  # as filed
        try:
            if filters == ["DCTDecode"]:
                ext, body = "jpg", data
            elif filters == ["CCITTFaxDecode"] and width and height:
                if len(data) > MAX_PAGE_STREAM:
                    raise ValueError(f"image data of {len(data)} bytes is larger than a scanned page")
                k = re.search(rb"/K\s+(-?\d+)", d)
                if not k or int(k.group(1)) >= 0:
                    raise ValueError("CCITT Group 3 images are not supported, only Group 4 (/K -1)")
                invert = (re.search(rb"/BlackIs1\s+true", d) is not None) != \
                    (re.search(rb"/Decode\s*\[\s*1(?:\.0*)?\s+0(?:\.0*)?\s*\]", d) is not None)
                ext, body = "png", png_1bit(g4_rows(data, width, height), width, height, invert, scale)
                base.update(width=-(-width // scale), height=-(-height // scale))  # as saved
            else:
                yield {"type": "uk_accounts_page_unsupported", **base, "filters": filters}
                continue
        except ValueError as e:
            yield {"type": "error", **base, "error": f"image {count}: {e}"}
            continue
        path = os.path.join(out_dir, f"page-{count:03d}.{ext}")
        with open(path, "wb") as f:
            f.write(body)
        written += 1
        yield {"type": "uk_accounts_page", **base, "path": path}
    yield {"type": "uk_accounts_pages", "images": count, "written": written, "out_dir": out_dir,
           "note": "image n is page n in a scanned filing; open the pages you need with your file reader"}


# --------------------------------------------------------------- quote -----

def _find_in_order(page, parts, window):
    """Start of the first place where every part appears in order, each within
    `window` characters of the previous one; -1 if there is none."""
    if not parts:
        return -1
    start = page.find(parts[0])
    while start >= 0:
        pos, ok = start + len(parts[0]), True
        for part in parts[1:]:
            nxt = page.find(part, pos, pos + window + len(part))
            if nxt < 0:
                ok = False
                break
            pos = nxt + len(part)
        if ok:
            return start
        start = page.find(parts[0], start + 1)
    return -1


_QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


def find_quote(page, quote):
    """Position of `quote` in `page` (both plain text, lower-cased), or -1, and
    the length of the matched span. Handles table quotes (cells in order, any
    separators) and XML quotes (element values in order, close together)."""
    page = page.translate(_QUOTE_CHARS)
    if re.search(r"<[A-Za-z/][^>]*>", quote):
        parts = [p.lower().translate(_QUOTE_CHARS) for p in (text_of(x) for x in re.split(r"<[^>]+>", quote)) if p]
        return _find_in_order(page, parts, window=1500), 1500
    needle = re.sub(r"\s+", " ", quote.replace("|", " ")).strip().lower().translate(_QUOTE_CHARS)
    pos = page.find(needle)
    if pos >= 0:
        return pos, len(needle)
    tokens = [t for t in re.split(r"[\s|]+", needle) if t]
    if tokens:  # table quotes: allow anything non-alphanumeric between the cells
        m = re.search(r"\W+".join(re.escape(t) for t in tokens), page)
        if m:
            return m.start(), m.end() - m.start()
    return -1, 0


def quote_check(url, quote, user_agent, context_chars):
    page = text_of(fetch(url, user_agent)).lower()
    pos, span = find_quote(page, quote)
    record = {"type": "quote_check", "url": url, "quote": quote, "found": pos >= 0}
    if pos >= 0:
        record["context"] = page[max(0, pos - context_chars): pos + span + context_chars]
    emit(record)


# ------------------------------------------------------- verify-report -----

_URL_RE = re.compile(r"https?://[^\s<>()\"'`\]]+")
_QUOTE_LINE_RE = re.compile(r"\bQuote:\s*(.+)", re.I)
_QUOTED_RE = re.compile(r"[\"“](.+?)[\"”]|`([^`]+)`")


def parse_red_flags(markdown):
    """Red-flag items from a report: each with its title, URLs, and quote.

    The section starts at a 'Red flags' heading or bold label and ends at the next
    heading or bold section label; items are top-level numbered or bulleted lines,
    with their indented continuation lines."""
    lines = markdown.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"^\s*(#+\s*|\*\*)\s*Red flags\b", l, re.I)), None)
    if start is None:
        return []
    first = next((l for l in lines[start + 1:] if l.strip()), "")
    if re.match(r"^\s*(none|no red flags)\b", first, re.I):  # "None." then explanatory bullets
        return []
    items, current = [], None
    for line in lines[start + 1:]:
        if re.match(r"^(#+\s|\*\*(Gaps|Facts|Sources)\b)", line):
            break
        if re.match(r"^(\d+[.)]|[-*])\s+", line):  # a new top-level item
            current = [line]
            items.append(current)
        elif current is not None and line.strip():
            current.append(line)
    flags = []
    for n, block in enumerate(items, 1):
        text = "\n".join(block)
        if re.match(r"^(\d+[.)]|[-*])\s+(none|no red flags)\b", block[0], re.I):
            continue
        title = re.search(r"\*\*(.+?)\*\*", block[0])
        quote = None
        m = _QUOTE_LINE_RE.search(text)
        if m:
            q = _QUOTED_RE.search(m.group(1))
            quote = (q.group(1) or q.group(2)) if q else m.group(1).strip()
        urls = list(dict.fromkeys(u.rstrip(".,;:") for u in _URL_RE.findall(text)))
        flags.append({"index": n, "title": title.group(1) if title else block[0][:120].strip(),
                      "urls": urls, "quote": quote})
    return flags


MIN_QUOTE_WORDS = 4


def quote_warnings(page, quote, matched):
    """Why a found quote may still not prove the flag: too short to carry the
    flagged figures, or matched in several places (the context shows the first)."""
    warnings = []
    if len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", quote))) < MIN_QUOTE_WORDS:
        warnings.append(f"quote has fewer than {MIN_QUOTE_WORDS} words, so finding it does not show the flagged "
                        "figures; quote the whole row or sentence")
    count = page.count(matched) if matched else 0
    if count > 1:
        warnings.append(f"quote appears {count} times on the page; the context shows the first, "
                        "which may be another row or period")
    return warnings


def verify_reports(paths, user_agent, fetcher=None):
    """Check every red flag's quote against its cited pages. Each page is fetched
    once; a flag passes when its quote is found on any URL it cites."""
    fetcher = fetcher or (lambda u: fetch(u, user_agent))
    pages = {}
    totals = {"confirmed": 0, "not_found": 0, "unreachable": 0, "no_text_layer": 0, "no_quote": 0, "no_url": 0}

    def page_text(url):
        if url not in pages:
            try:
                body = fetcher(url)
                if body.lstrip()[:5] == "%PDF-":  # a PDF has no searchable text here (often a scan)
                    pages[url] = ("pdf", None)
                else:
                    pages[url] = ("ok", text_of(body).lower())
            except FetchError as e:
                pages[url] = ("error", str(e))
        return pages[url]

    for path in paths:
        report = pathlib_name(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            flags = parse_red_flags(f.read())
        for flag in flags:
            record = {"type": "red_flag_check", "report": report, **flag}
            if not flag["quote"] or not flag["urls"]:
                record["result"] = "no_quote" if not flag["quote"] else "no_url"
                totals[record["result"]] += 1
                yield record
                continue
            errors, pdfs = [], []
            for url in flag["urls"]:
                status, text = page_text(url)
                if status == "error":
                    errors.append(f"{url}: {text}")
                    continue
                if status == "pdf":
                    pdfs.append(url)
                    continue
                pos, span = find_quote(text, flag["quote"])
                if pos >= 0:
                    # an XML quote's match starts at its first element; context before it
                    # belongs to the previous holding, so start there
                    lead = 0 if re.search(r"<[A-Za-z/][^>]*>", flag["quote"]) else 80
                    record.update(result="confirmed", matched_url=url,
                                  context=text[max(0, pos - lead): pos + span + 80])
                    warnings = quote_warnings(text, flag["quote"], text[pos:pos + span])
                    if warnings:
                        record["warnings"] = warnings
                    totals["confirmed"] += 1
                    break
            else:
                if pdfs and len(pdfs) + len(errors) == len(flag["urls"]):
                    record.update(result="no_text_layer", pdfs=pdfs,
                                  note="the cited page is a PDF with no text to search (often a scan); read it yourself")
                    totals["no_text_layer"] += 1
                elif errors and len(errors) == len(flag["urls"]):
                    no_contact = all("needs --user-agent" in e for e in errors)
                    record.update(result="unreachable", errors=errors,
                                  note="sec.gov pages need the SEC contact: rerun with --user-agent (it is sent to "
                                       "sec.gov only), or check the quote with quote-check" if no_contact
                                  else "no cited page could be fetched; check it in a browser")
                    totals["unreachable"] += 1
                else:
                    record.update(result="not_found", errors=errors or None)
                    totals["not_found"] += 1
            yield record
    yield {"type": "verify_summary", "reports": len(paths), **totals}


def pathlib_name(path):
    return os.path.basename(path)


def is_source_report(path):
    """A source report starts with its SOURCE: line (entity.md and notes do not)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(2000)
    return re.search(r"^\W*SOURCE:", head, re.M) is not None


def report_paths(targets):
    out = []
    for t in targets:
        if os.path.isdir(t):
            out += sorted(os.path.join(t, n) for n in os.listdir(t)
                          if n.endswith(".md") and n != "dossier.md" and is_source_report(os.path.join(t, n)))
        else:
            out.append(t)
    return out


# ----------------------------------------------------------------- main ----

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user-agent", default=os.environ.get("MUCKRAKER_SEC_UA"),
                   help='"Name email" for sec.gov (or set MUCKRAKER_SEC_UA)')
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
    s.add_argument("name_or_lei", help="a legal name to search, or a 20-character LEI")
    s.add_argument("--limit", type=int, default=10, help="search candidates to return")
    s.add_argument("--max-children", type=int, default=200)

    s = sub.add_parser("ch", help="UK Companies House: profile, officers, PSCs, charges, filings, late-filing flags")
    s.add_argument("company_number")
    s.add_argument("--max-filings", type=int, default=200, help="filings to read and check for late-filing flags")
    s.add_argument("--list-filings", type=int, default=25, help="latest filings to list in the output")

    s = sub.add_parser("uk-accounts", help="UK Companies House: multi-year figures from iXBRL accounts")
    s.add_argument("company_number")
    s.add_argument("--sets", type=int, default=3, help="accounts filings to read (each covers two years)")

    s = sub.add_parser("uk-pages", help="save a scanned accounts PDF's pages as images an agent can read")
    s.add_argument("pdf", help="the uk_accounts_scanned record's url, or a local PDF file")
    s.add_argument("out_dir")
    s.add_argument("--pages", help="pages to save, such as 1-5,33 (default: all)")
    s.add_argument("--scale", type=int, choices=(1, 2, 3, 4), default=2,
                   help="shrink fax-image pages this many times; the default 2 halves each side of a 300 dpi "
                        "scan and stays legible, 1 keeps full size for small print")

    s = sub.add_parser("verify-report", help="check every red flag's quote in source reports against its cited pages")
    s.add_argument("targets", nargs="+", help="report files, or a run folder (every .md except dossier.md)")

    s = sub.add_parser("quote-check", help="confirm a quote appears on a page, ignoring markup")
    s.add_argument("url")
    s.add_argument("quote")
    s.add_argument("--context", type=int, default=200)

    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    try:
        if a.cmd == "edgar-filings":
            data = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{cik10(a.cik)}.json", a.user_agent))
            for r in parse_submissions(data, a.limit):
                emit(r)
        elif a.cmd == "edgar-facts":
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10(a.cik)}.json"
            try:
                data = json.loads(fetch(url, a.user_agent))
            except FetchError as e:
                if "HTTP 404" not in str(e):
                    raise
                emit({"type": "no_xbrl_financials", "url": url,
                      "note": "SEC holds no tagged financial statements for this CIK (it has never filed a 10-K, 10-Q or 20-F with XBRL)"})
                return 0
            for r in parse_companyfacts(data, a.years):
                emit(r)
        elif a.cmd == "edgar-search":
            forms = [f.strip() for f in a.forms.split(",") if f.strip()]
            hits, summary = edgar_search(a.phrase, forms, a.since, a.until, a.user_agent, a.max_hits)
            emit(summary)
            for r in hits:
                emit(r)
        elif a.cmd == "marks":
            aliases = skip_covered(a.aliases, load_searched(a.skip_seen)) if a.skip_seen else a.aliases
            if aliases:
                marks(aliases, a.user_agent, a.since, a.per_filer, a.max_filers, a.verbose, load_seen(a.skip_seen))
        elif a.cmd == "gleif":
            target = a.name_or_lei.strip().upper()
            results = gleif_report(target, a.max_children) if LEI_RE.match(target) else gleif_search(a.name_or_lei, a.limit)
            for r in results:
                emit(r)
        elif a.cmd in ("ch", "uk-accounts"):
            ch = CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY"))
            results = ch_report(a.company_number, ch, a.max_filings, list_filings=a.list_filings) if a.cmd == "ch" \
                else uk_accounts(a.company_number, ch, a.sets)
            for r in results:
                emit(r)
        elif a.cmd == "uk-pages":
            if a.pdf.startswith(("http://", "https://")):
                pdf = fetch_bytes(a.pdf, None)
            else:
                with open(a.pdf, "rb") as f:
                    pdf = f.read()
            for r in page_images(pdf, a.out_dir, parse_pages(a.pages) if a.pages else None, a.scale):
                emit(r)
        elif a.cmd == "verify-report":
            for r in verify_reports(report_paths(a.targets), a.user_agent):
                emit(r)
        elif a.cmd == "quote-check":
            quote_check(a.url, a.quote, a.user_agent, a.context)
    except FetchError as e:
        emit({"type": "error", "error": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
