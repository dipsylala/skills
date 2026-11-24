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
import http.client
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
from html.parser import HTMLParser
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
    return decode_body(fetch_bytes(url, user_agent, retries, auth, accept))


_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)


def decode_body(raw):
    """UTF-8 when the body is valid UTF-8; otherwise the charset the page declares
    in its first 4 KB (a Latin-1 register page such as w2.brreg.no), else cp1252.
    Decoding a Latin-1 page as UTF-8 turns every å or ø into U+FFFD, so quotes
    with those letters are never found."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    m = _CHARSET_RE.search(raw[:4096])
    if m:
        try:
            return raw.decode(m.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    return raw.decode("cp1252", errors="replace")


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
        except (TimeoutError, ConnectionError, http.client.HTTPException) as e:  # read timeout, reset, cut-off body
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"{type(e).__name__} for {url}") from e


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
            emit({"type": "already_searched", "alias": alias, "covered_by": by,
                  "note": f'an earlier search for "{by}" already matched every filing naming this alias'})
        else:
            left.append(alias)
    return left


def marks(aliases, user_agent, since, per_filer, max_filers, verbose=False, seen=None):
    seen = seen or set()
    complete, by_alias = [], {}  # complete: aliases whose searches returned every hit
    for alias in sorted(aliases, key=len):  # broadest first, so it can cover the longer names
        by = covering_alias(alias, complete)
        if by:
            emit({"type": "already_searched", "alias": alias, "covered_by": by,
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
                emit(summary)
            if summary.get("total", 0) > GENERIC_ALIAS_HITS:
                emit({"type": "generic_alias", "alias": alias, "forms": forms, "total": summary.get("total"),
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
            emit({"type": "generic_alias", "alias": alias, "total": total, "dropped": True,
                  "note": f"this name matched {total} filings, over {OUTLIER_RATIO} times the most specific "
                          "alias, so it is probably a common word; its filings were not read. Search it by "
                          "hand with the company name if it matters"})
            if alias in complete:
                complete.remove(alias)
            continue
        hits += found
    # lets --skip-seen skip covered aliases: only those searched in full can cover another
    search_urls = [search_web_url(a, forms, since) for a in by_alias for forms in (["10-K", "10-Q"], ["NPORT-P"])]
    emit({"type": "marks_search", "aliases": aliases, "searched": complete, "since": since, "urls": search_urls})
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
              "filings_matched": len(hits), "urls": search_urls,
              "note": "no lender schedule or fund holding names these borrowers; nothing failed. Cite the "
                      "full-text searches in urls"})
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
        "category": e.get("category"),
        "legal_form_other": (e.get("legalForm") or {}).get("other"),
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


def gleif_search(name, limit, fetcher=None, registered_as=None):
    """LEI candidates by name, or by the entity's number in its national register (KVK, SIREN, HRB...)."""
    if registered_as:
        q = urllib.parse.urlencode({"filter[entity.registeredAs]": registered_as, "page[size]": str(limit)})
    else:
        q = urllib.parse.urlencode({"filter[fulltext]": name, "page[size]": str(limit)})
    data = gleif_json(f"/lei-records?{q}", fetcher) or {"data": []}
    records = data.get("data", [])
    # full-text search ranks loose matches too ("Snyk, Inc." returns car dealers);
    # keep candidates whose name or other names share a word with the query beyond its legal form
    wanted = set() if registered_as else distinctive_words(name)
    kept, dropped = 0, 0
    for rec in records:
        ent = gleif_entity(rec)
        if wanted and not wanted & distinctive_words(" ".join([ent["legal_name"] or "", *ent["other_names"]])):
            dropped += 1
            continue
        kept += 1
        yield {"type": "gleif_candidate", **{k: ent[k] for k in (
            "lei", "legal_name", "category", "jurisdiction", "registered_as", "entity_status", "lei_status",
            "legal_address", "url")}}
    if not kept:  # no LEI is itself a result; say so rather than print nothing
        note = ("no LEI record has this registration number; try the name" if registered_as else
                "no LEI record matches this name; try another spelling or a parent's name")
        if dropped:
            note += f" ({dropped} loose matches sharing none of the name's words were left out)"
        yield {"type": "gleif_no_match", "query": registered_as or name, "url": f"{GLEIF}/lei-records?{q}", "note": note}


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
    if entity["category"] == "FUND":
        links = {}
        for rel in ("umbrella-fund", "fund-manager"):
            rec = gleif_json(f"/lei-records/{lei}/{rel}", fetcher)
            if rec and rec.get("data"):
                links[rel.replace("-", "_")] = gleif_entity(rec["data"])["legal_name"]
        yield {"type": "gleif_fund", "lei": lei, "legal_name": entity["legal_name"],
               "legal_form_other": entity["legal_form_other"], **links,
               "note": "this LEI is a fund vehicle, often an investor's fund named after a holding, not the operating "
                       "company; do not use it as the company's LEI"}
    if entity["lei_status"] in ("LAPSED", "RETIRED", "ANNULLED"):
        yield {"type": "gleif_lapsed", "lei": lei, "lei_status": entity["lei_status"],
               "last_update": entity["last_update"], "legal_name": entity["legal_name"],
               "note": "the LEI is not maintained, so its name, address and parents date from its last update; "
                       "check the name against the company register before relying on them"}

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


def ch_search(name, ch, limit=20):
    """Companies House companies whose name matches, so a non-UK target's UK
    companies and overseas registrations (FC numbers) are found in step 1."""
    q = urllib.parse.quote(name)
    items = (ch.get(f"/search/companies?q={q}&items_per_page={limit}") or {}).get("items", [])
    for i in items:
        yield {"type": "ch_candidate", "company_number": i.get("company_number"), "name": i.get("title"),
               "status": i.get("company_status"), "company_type": i.get("company_type"),
               "created": i.get("date_of_creation"), "address": i.get("address_snippet"),
               "url": f"{CH_WEB}/company/{i.get('company_number')}"}
    yield {"type": "ch_search_summary", "query": name, "results": len(items),
           "url": f"{CH_WEB}/search/companies?q={q}"}


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

    if p.get("type") == "oversea-company":
        for e in (ch.get(f"/company/{number}/uk-establishments") or {}).get("items", []):
            yield {"type": "ch_uk_establishment", "branch_number": e.get("company_number"), "name": e.get("company_name"),
                   "status": e.get("company_status"), "locality": e.get("locality"),
                   "url": f"{CH_WEB}/company/{e.get('company_number')}"}

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
        if f.get("type") == "OSIN01" and p.get("type") == "oversea-company" and p.get("date_of_creation") and f.get("date"):
            opened, due = _date(p["date_of_creation"]), _add_months(_date(p["date_of_creation"]), 1)
            if _date(f["date"]) > due:
                counts["minor"] += 1
                if (today - _date(f["date"])).days <= 730:
                    counts["minor_last_24_months"] += 1
                yield {"type": "ch_flag", "flag": "late overseas registration", "severity": "minor", "form": "OSIN01",
                       "filed": f["date"], "event_date": opened.isoformat(), "days_late": (_date(f["date"]) - due).days,
                       "rule": "an overseas company must register within one month of opening a UK establishment "
                               "(Overseas Companies Regulations 2009, reg. 4); the register's creation date is the opening date",
                       "quote": quote, "url": page_url}
        if GAZETTE_FORMS_RE.match(f.get("type") or ""):
            counts["major"] += 1
            yield {"type": "ch_flag", "flag": "gazette notice", "severity": "major", "form": f.get("type"), "filed": f.get("date"),
                   "description": describe_filing(f), "quote": quote, "url": page_url}
    yield {"type": "ch_summary", "company_number": number, "officers": len(officers), "pscs": len(pscs),
           "psc_statements": len(statements), "filings_read": min(len(filings), max_filings),
           "major_flags": counts["major"] + overdue, "minor_late_filings": counts["minor"],
           "minor_late_filings_last_24_months": counts["minor_last_24_months"],
           "note": ("minor flags are officer, PSC, confirmation-statement and overseas-registration filings made late: register "
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


NO_PSC_STATEMENTS = ("no-individual-or-entity-with-signficant-control",  # sic: Companies House's spelling
                     "no-individual-or-entity-with-significant-control")


_PARENT_NAMED_RE = re.compile(r"parent (?:undertaking|company|entity) is|controlled by|owned by|subsidiary of", re.I)


def psc_parent_mismatch(number, ch, parent_sentences):
    """A minor flag when the PSC register says no one has significant control
    but the accounts name a parent, which should then be a registrable entity."""
    # quote the sentence that names the parent, not a related-party exemption that only mentions one
    parent_sentences = sorted(parent_sentences, key=lambda s: not _PARENT_NAMED_RE.search(s))
    web = f"{CH_WEB}/company/{number}/persons-with-significant-control"
    statements = (ch.get(f"/company/{number}/persons-with-significant-control-statements") or {}).get("items", [])
    current = [x for x in statements if x.get("statement") in NO_PSC_STATEMENTS and not x.get("ceased_on")]
    pscs = (ch.get(f"/company/{number}/persons-with-significant-control?items_per_page=100") or {}).get("items", [])
    corporate = [x for x in pscs if re.search(r"corporate-entity|legal-person", x.get("kind") or "")]
    if not current and corporate and not any(not x.get("ceased_on") for x in corporate):
        ceased = max(corporate, key=lambda x: x.get("ceased_on") or "")
        yield {"type": "uk_psc_mismatch", "severity": "minor", "statement": "no current corporate PSC",
               "last_corporate_psc": ceased.get("name"), "notified_on": ceased.get("notified_on"),
               "ceased_on": ceased.get("ceased_on"), "accounts_say": parent_sentences[0], "url": web,
               "note": "the accounts name a parent, but the register shows every corporate PSC as ceased; a parent "
                       "company holding over 25% is normally a current registrable PSC. Register housekeeping unless "
                       "the parent is hidden elsewhere"}
    if current:
        yield {"type": "uk_psc_mismatch", "severity": "minor", "statement": current[0]["statement"].replace("-", " "),
               "notified_on": current[0].get("notified_on"), "accounts_say": parent_sentences[0], "url": web,
               "note": "the PSC register says no person or entity has significant control, but the accounts name "
                       "a parent; a parent company holding over 25% is normally a registrable PSC. Register "
                       "housekeeping unless the parent is hidden elsewhere"}


def uk_no_accounts_note(profile):
    """Why a company may have no accounts on file, by company type."""
    if profile.get("type") != "oversea-company":
        return "no accounts filed yet; a newly incorporated company's first accounts fall due 21 months after incorporation"
    req = ((profile.get("foreign_company_details") or {}).get("accounting_requirement") or {}).get("foreign_account_type")
    if req == "accounting-requirements-of-originating-country-do-not-apply":
        return ("no accounts filed yet; an overseas company whose home law does not require it to publish accounts "
                "delivers accounts for each period within 13 months of its end (Overseas Companies Regulations 2009); "
                f"next period ends {(profile.get('accounts') or {}).get('next_made_up_to')}")
    return ("no accounts filed here; an overseas company delivers the accounts its home law requires it to publish "
            "within 3 months of their publication, so read them in its home register")


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
               "note": uk_no_accounts_note(ch.get(f"/company/{number}") or {})}
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
            if notes.get("parent_and_control"):
                yield from psc_parent_mismatch(number, ch, notes["parent_and_control"])
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

    def rows():
        for changes in changes_by_row:
            black = 0
            for i in range(0, len(changes), 2):
                start, end = changes[i], changes[i + 1] if i + 1 < len(changes) else width
                if end > start:
                    black |= ((1 << (end - start)) - 1) << (nbytes * 8 - end)
            yield black
    return png_black_rows(rows(), width, height, invert, scale)


def flate_1bit_rows(data, width, height, invert=False):
    """Black-pixel rows of an uncompressed 1-bit DeviceGray bitmap (a FlateDecode
    scan, as in Brønnøysund's accounts copies): 0 is black unless `invert`."""
    nbytes = (width + 7) // 8
    if len(data) < nbytes * height:
        raise ValueError(f"image data of {len(data)} bytes is shorter than {width} x {height} pixels")
    full = (1 << nbytes * 8) - 1
    for y in range(height):
        row = int.from_bytes(data[y * nbytes:(y + 1) * nbytes], "big")
        yield row if invert else full ^ row


def png_black_rows(black_rows, width, height, invert=False, scale=1):
    """A black-and-white PNG from rows of black-pixel bits (most significant bit
    first), optionally `scale` times smaller."""
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
    for black in black_rows:
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
            elif (filters == ["FlateDecode"] and width and height and re.search(rb"/BitsPerComponent\s+1(?!\d)", d)
                  and not re.search(rb"/DecodeParms", d)):
                z = zlib.decompressobj()
                try:
                    raw = z.decompress(data, MAX_PAGE_BITMAP + 1)
                except zlib.error as e:
                    raise ValueError(f"image data does not decompress: {e}") from e
                if len(raw) > MAX_PAGE_BITMAP or z.unconsumed_tail:
                    raise ValueError("image data is larger than a scanned page")
                invert = re.search(rb"/Decode\s*\[\s*1(?:\.0*)?\s+0(?:\.0*)?\s*\]", d) is not None
                ext = "png"
                body = png_black_rows(flate_1bit_rows(raw, width, height, invert), width, height, False, scale)
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
    note = "image n is page n in a scanned filing; open the pages you need with your file reader"
    try:
        has_text = not written and bool(pdf_text(pdf))
    except ValueError:
        has_text = False
    if has_text:
        note = "no page images to save: this PDF was made by software and has a text layer; read it with mr.py pdf-text"
    yield {"type": "uk_accounts_pages", "images": count, "written": written, "out_dir": out_dir, "note": note}


# a PDF number; its parts cannot repartition, so a long digit run cannot make the matcher backtrack
_PDF_NUM = rb"-?(?:\d{1,32}(?:\.\d{0,32})?|\.\d{1,32})"
_PDF_TEXT_TOKEN_RE = re.compile(
    rb"\((?:\\.|[^\\)])*\)"            # literal string
    rb"|<[0-9A-Fa-f\s]*>"              # hex string
    rb"|\[|\]"
    rb"|/([^\s/\[\]()<>]+)\s+" + _PDF_NUM + rb"\s+Tf\b"   # font selection
    rb"|(" + _PDF_NUM + rb")\s+(" + _PDF_NUM + rb")\s+T[dD]\b"
    rb"|" + _PDF_NUM +
    rb"|T\*|Tj|TJ|'|\"|ET\b|BT\b", re.S)
_PDF_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                b"(": b"(", b")": b")", b"\\": b"\\"}
_PDF_OBJ_RE = re.compile(rb"(?<!\d)(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj\b", re.S)


def _pdf_literal(raw):
    out, i = bytearray(), 1
    while i < len(raw) - 1:
        c = raw[i:i + 1]
        if c == b"\\":
            nxt = raw[i + 1:i + 2]
            octal = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                i += 1 + len(octal.group(0))
                continue
            out += _PDF_ESCAPES.get(nxt, b"")
            i += 2
            continue
        out += c
        i += 1
    return bytes(out)


def _pdf_hex(raw):
    return bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", raw[1:-1]).decode().ljust(2, "0"))


MAX_PDF_OBJECTS = 200000
MAX_PDF_DECODED = MAX_BODY  # decompressed bytes across all of a PDF's streams


def _pdf_objects(pdf):
    """Object number -> (dictionary bytes, decoded stream bytes or None). Raises
    ValueError when the PDF holds too many objects or its streams decompress to
    more than MAX_PDF_DECODED bytes in all, so a fetched PDF cannot exhaust memory."""
    objects, decoded = {}, 0
    for m in _PDF_OBJ_RE.finditer(pdf):
        if len(objects) >= MAX_PDF_OBJECTS:
            raise ValueError(f"more than {MAX_PDF_OBJECTS} objects in the PDF")
        body = m.group(3)
        split = re.search(rb"\bstream\r?\n", body)
        if not split:
            objects[int(m.group(1))] = (body, None)
            continue
        d, data = body[:split.start()], body[split.end():]
        data = data[:data.rfind(b"endstream")].rstrip(b"\r\n")
        if re.search(rb"/Filter\s*/FlateDecode\b", d):
            z = zlib.decompressobj()
            try:
                data = z.decompress(data, min(MAX_PAGE_BITMAP, MAX_PDF_DECODED - decoded + 1))
            except zlib.error:
                data = None
            if z.unconsumed_tail:
                raise ValueError("a stream decompresses to more than a page's worth of data")
        elif re.search(rb"/Filter", d):
            data = None
        if data:
            decoded += len(data)
            if decoded > MAX_PDF_DECODED:
                raise ValueError(f"the PDF's streams decompress to more than {MAX_PDF_DECODED} bytes")
        objects[int(m.group(1))] = (d, data)
    return objects


def _pdf_resolve(objects, value):
    """An inline dictionary, or the one an `n 0 R` reference points at."""
    ref = re.fullmatch(rb"\s*(\d+)\s+\d+\s+R\s*", value or b"")
    return objects.get(int(ref.group(1)), (b"", None))[0] if ref else (value or b"")


def _pdf_dict_entry(d, key):
    """The value of /key in a dictionary: a reference, or a nested << >> dictionary."""
    m = re.search(rb"/" + key + rb"\s*(\d+\s+\d+\s+R|<<)", d)
    if not m:
        return None
    if m.group(1) != b"<<":
        return m.group(1)
    depth, i = 0, m.start(1)
    while i < len(d):
        if d.startswith(b"<<", i):
            depth, i = depth + 1, i + 2
        elif d.startswith(b">>", i):
            depth, i = depth - 1, i + 2
            if not depth:
                return d[m.start(1):i]
        else:
            i += 1
    return None


def _pdf_cmap(data):
    """A ToUnicode CMap as (code width in bytes, {code: text})."""
    out, width = {}, 1
    space = re.search(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>", data)
    if space:
        width = max(1, len(space.group(1)) // 2)

    def text(hexstr):
        return bytes.fromhex(hexstr.decode()).decode("utf-16-be", errors="replace")
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            out[int(src, 16)] = text(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block):
            lo, hi = int(lo, 16), int(hi, 16)
            if hi - lo > 65535:
                continue
            if dst.startswith(b"["):
                for i, item in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", dst)):
                    out[lo + i] = text(item)
            else:
                start = bytes.fromhex(dst[1:-1].decode())
                for i in range(hi - lo + 1):
                    last = int.from_bytes(start[-2:], "big") + i
                    out[lo + i] = (start[:-2] + last.to_bytes(2, "big")).decode("utf-16-be", errors="replace")
    return width, out


def _pdf_page_fonts(objects, page_dict, cache):
    """Font resource name -> (code width, ToUnicode map or None) for one page."""
    resources = _pdf_resolve(objects, _pdf_dict_entry(page_dict, b"Resources"))
    fonts = _pdf_resolve(objects, _pdf_dict_entry(resources, b"Font"))
    out = {}
    for name, num in re.findall(rb"/([^\s/\[\]()<>]+)\s*(\d+)\s+\d+\s+R", fonts):
        num = int(num)
        if num not in cache:
            font = objects.get(num, (b"", None))[0]
            tu = re.search(rb"/ToUnicode\s*(\d+)\s+\d+\s+R", font)
            data = objects.get(int(tu.group(1)), (b"", None))[1] if tu else None
            two_byte = re.search(rb"/Subtype\s*/Type0\b", font) is not None
            cache[num] = _pdf_cmap(data) if data else (2 if two_byte else 1, None)
        out[name] = cache[num]
    return out


def _pdf_decode(raw, font):
    width, cmap = font or (1, None)
    if cmap is None:
        return raw.decode("latin-1") if width == 1 else raw[1::2].decode("latin-1")
    codes = [int.from_bytes(raw[i:i + width], "big") for i in range(0, len(raw), width)]
    return "".join(cmap.get(c, "") for c in codes)


def pdf_content_text(content, fonts=None):
    """Text shown by a page content stream: strings drawn with Tj, TJ, ' and ",
    decoded through each font's ToUnicode map, with line breaks where the text moves down."""
    fonts, out, in_array, font = fonts or {}, [], False, None
    for m in _PDF_TEXT_TOKEN_RE.finditer(content):
        tok = m.group(0)
        if m.group(1) is not None:  # Tf
            font = fonts.get(m.group(1))
        elif m.group(2) is not None:  # Td / TD
            if float(m.group(3)) != 0:  # a move along the line only places the next glyph; spaces are glyphs
                out.append("\n")
        elif tok.startswith(b"("):
            out.append(_pdf_decode(_pdf_literal(tok), font))
        elif tok.startswith(b"<"):
            out.append(_pdf_decode(_pdf_hex(tok), font))
        elif tok == b"[":
            in_array = True
        elif tok == b"]":
            in_array = False
        elif in_array and re.fullmatch(_PDF_NUM, tok) and float(tok) < -200:
            out.append(" ")  # a wide kerning gap inside TJ is a space
        elif tok in (b"T*", b"'", b'"', b"ET"):
            out.append("\n")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", "".join(out))).strip()


def pdf_text(pdf):
    """The text layer of a PDF made by software (not a scan), one block per page,
    in file order."""
    objects, cache, blocks = _pdf_objects(pdf), {}, []
    for d, _ in list(objects.values()):
        if not re.search(rb"/Type\s*/Page\b(?!s)", d):
            continue
        fonts = _pdf_page_fonts(objects, d, cache)
        contents = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", d)
        refs = re.findall(rb"(\d+)\s+\d+\s+R", contents.group(1)) if contents else []
        content = b"\n".join(objects.get(int(r), (b"", None))[1] or b"" for r in refs)
        text = pdf_content_text(content, fonts)
        if text:
            blocks.append(text)
    return blocks


def pdf_text_records(pdf, source):
    blocks = pdf_text(pdf)
    if blocks:
        yield {"type": "pdf_text", "source": source, "blocks": len(blocks), "text": "\n\n".join(blocks)}
    else:
        yield {"type": "pdf_no_text", "source": source,
               "note": "no text layer (a scan); save its pages as images with mr.py uk-pages and read those"}


# --------------------------------------------------------------- quote -----

# ------------------------------------------------------ officer history ----

INSOLVENT_STATUSES = {"liquidation", "administration", "receivership", "voluntary-arrangement",
                      "insolvency-proceedings"}
DIRECTOR_ROLES = {"director", "llp-member", "llp-designated-member", "member"}


def _name_tokens(name):
    """Lower-case name words, for "SURNAME, Forenames" and "Forenames SURNAME" alike."""
    return set(re.findall(r"[a-z]+", (name or "").lower()))


SOLVENT_CASES = {"members-voluntary-liquidation"}  # a solvent winding-up, routine for group subsidiaries


def insolvency_cases(ch, number):
    """The company's insolvency case types, leaving out solvent (members') liquidations."""
    cases = (ch.get(f"/company/{number}/insolvency") or {}).get("cases") or []
    return [c.get("type") for c in cases if c.get("type") not in SOLVENT_CASES]


def ch_officers(number, ch, max_appointments=100, max_checks=30):
    """Each current director's other UK appointments: companies that went insolvent,
    and any matching disqualification. Company roles only: no addresses or birth
    dates in the output."""
    number = number.strip().upper()
    officers = (ch.get(f"/company/{number}/officers?items_per_page=100") or {}).get("items", [])
    directors = [o for o in officers if not o.get("resigned_on") and o.get("officer_role") in DIRECTOR_ROLES]
    flagged = 0
    for o in directors:
        link = ((o.get("links") or {}).get("officer") or {}).get("appointments")
        if not link:
            continue
        data = ch.get(f"{link}?items_per_page={max_appointments}") or {}
        items, insolvent, checked, unchecked = data.get("items") or [], [], 0, 0
        for a in items:
            to = a.get("appointed_to") or {}
            other, status = to.get("company_number"), to.get("company_status")
            if other == number or not (status in INSOLVENT_STATUSES or status == "dissolved"):
                continue
            if checked >= max_checks:
                unchecked += status in INSOLVENT_STATUSES
                continue
            checked += 1
            if status == "dissolved" and not (ch.get(f"/company/{other}") or {}).get("has_insolvency_history"):
                continue  # struck off without an insolvency
            cases = insolvency_cases(ch, other)  # a members' (solvent) liquidation is not an insolvency
            if cases:
                insolvent.append(other)
                yield {"type": "ch_officer_insolvent_company", "officer": o.get("name"), "company_number": other,
                       "company_name": to.get("company_name"), "status": status, "cases": cases,
                       "role": a.get("officer_role"), "appointed_on": a.get("appointed_on"),
                       "resigned_on": a.get("resigned_on"), "url": f"{CH_WEB}/company/{other}/insolvency"}
        yield {"type": "ch_officer_history", "officer": o.get("name"), "role": o.get("officer_role"),
               "appointments": data.get("total_results", len(items)), "read": len(items),
               "active": sum(1 for a in items if (a.get("appointed_to") or {}).get("company_status") == "active"),
               "insolvent_companies": len(insolvent), "unchecked_in_liquidation_or_administration": unchecked,
               "url": f"{CH_WEB}{link}"}
        if insolvent:
            flagged += 1
            many = len(insolvent) >= 2
            yield {"type": "ch_flag", "flag": "director of insolvent companies" if many else "director of an insolvent company",
                   "severity": "major" if many else "minor", "officer": o.get("name"), "companies": insolvent,
                   "rule": "a director of two or more companies that went insolvent is the 'phoenix' pattern; one is "
                           "common among founders, so check whether they served in the run-up",
                   "url": f"{CH_WEB}{link}"}
        dob = o.get("date_of_birth") or {}
        q = urllib.parse.quote(o.get("name") or "")
        for d in (ch.get(f"/search/disqualified-officers?q={q}&items_per_page=20") or {}).get("items", []):
            born = _date((d.get("date_of_birth") or "")[:10] or None)
            same_name = _name_tokens(d.get("title")) == _name_tokens(o.get("name"))
            if same_name and born and dob and (born.year, born.month) == (dob.get("year"), dob.get("month")):
                flagged += 1
                yield {"type": "ch_flag", "flag": "disqualified director", "severity": "major", "officer": o.get("name"),
                       "disqualification": d.get("description"),
                       "rule": "the disqualified directors register lists someone with the same name and birth month",
                       "url": CH_WEB + ((d.get("links") or {}).get("self") or "")}
    yield {"type": "ch_officers_summary", "company_number": number, "directors": len(directors), "flags": flagged}


# -------------------------------------------------------------- layoffs ----

CA_WARN = "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
TX_WARN = "https://data.texas.gov/resource/8w53-c4f6.json"
_XLSX = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_XLSX_UNPACKED = 50 * 1024 * 1024


def xlsx_rows(data):
    """Rows of every sheet in an .xlsx file, in sheet order, each a dict of column letter to text."""
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > MAX_XLSX_UNPACKED:
        raise ValueError("the spreadsheet unpacks to too much data")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(_XLSX + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_XLSX + "si")]
    sheets = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    for name in sheets:
        for row in ET.fromstring(z.read(name)).iter(_XLSX + "row"):
            out = {}
            for c in row.findall(_XLSX + "c"):
                v = c.find(_XLSX + "v")
                if v is None or v.text is None:
                    continue
                out[re.sub(r"\d", "", c.get("r") or "")] = shared[int(v.text)] if c.get("t") == "s" else v.text
            yield out


def _excel_date(value):
    if value and re.fullmatch(r"\d+(\.\d+)?", value):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(value)))).isoformat()
    return value


def _name_match(name, text):
    """True when every distinctive word of the company name appears in `text` as a word."""
    words = distinctive_words(name) or set(re.findall(r"\w+", name.lower()))
    return bool(words) and words <= set(re.findall(r"\w+", (text or "").lower()))


def _int_or_none(value):
    return int(value) if value and str(value).isdigit() else None


def warn_ca(name, data):
    header = None
    for row in xlsx_rows(data):
        cells = {k: re.sub(r"\s+", " ", v).strip() for k, v in row.items()}
        if "Company" in cells.values() and any(v.startswith("Notice") for v in cells.values()):
            header = {v.lower(): k for k, v in cells.items()}
            continue
        if not header:
            continue
        col = lambda label: cells.get(header.get(label, ""))
        if _name_match(name, col("company")):
            yield {"type": "warn_notice", "state": "CA", "company": col("company"),
                   "notice_date": _excel_date(col("notice date")), "effective_date": _excel_date(col("effective date")),
                   "employees": _int_or_none(col("no. of employees")), "kind": col("layoff/ closure"),
                   "site": col("address"), "url": CA_WARN}


def warn_report(name, fetcher=None):
    """WARN notices naming the company in states that publish them as open data."""
    get = fetcher or (lambda u: fetch_bytes(u, None))
    covered, found = [], 0
    try:
        for r in warn_ca(name, get(CA_WARN)):
            found += 1
            yield r
        covered.append("CA (current fiscal year from 1 July; earlier years are PDFs)")
    except (FetchError, ValueError, KeyError) as e:
        yield {"type": "warn_unavailable", "state": "CA", "error": str(e), "url": CA_WARN}
    word = max(distinctive_words(name) or {name}, key=len).upper().replace("'", "''")
    tx_url = TX_WARN + "?" + urllib.parse.urlencode({"$where": f"upper(job_site_name) like '%{word}%'", "$limit": 200})
    try:
        for r in json.loads(get(tx_url)):
            if _name_match(name, r.get("job_site_name")):
                found += 1
                yield {"type": "warn_notice", "state": "TX", "company": r.get("job_site_name"),
                       "notice_date": (r.get("notice_date") or "")[:10], "effective_date": (r.get("layoff_date") or "")[:10],
                       "employees": _int_or_none(r.get("total_layoff_number")), "site": r.get("city_name"), "url": tx_url}
        covered.append("TX (open data, updated every few months)")
    except (FetchError, ValueError) as e:
        yield {"type": "warn_unavailable", "state": "TX", "error": str(e), "url": tx_url}
    yield {"type": "warn_summary", "query": name, "notices": found, "states_searched": covered,
           "note": "WARN notices are filed for layoffs of 50 or more at one site; other states publish theirs as web "
                   "pages or PDFs, so search those where the company has offices"}


# ------------------------------------------------------ US state registers ----

# States that publish their business register as open data (Socrata). New York's and Texas's
# datasets list only active entities; the others include inactive ones with their status.
US_STATE_DATASETS = [
    ("CO", "https://data.colorado.gov/resource/4ykn-tg5h.json", "entityname"),
    ("NY", "https://data.ny.gov/resource/n9v6-gdp6.json", "current_entity_name"),
    ("TX", "https://data.texas.gov/resource/9cir-efmm.json", "taxpayer_name"),
    ("OR", "https://data.oregon.gov/resource/tckn-sxa6.json", "business_name"),
    ("CT", "https://data.ct.gov/resource/n7gp-d28j.json", "name"),
]
TX_RIGHT_TO_TRANSACT = {"A": "active"}  # other codes: check the Comptroller's taxable entity search


def us_state_entity(state, r):
    """One register row as a `us_state_entity` record, or None for Oregon's non-address rows."""
    day = lambda v: (v or "")[:10] or None
    if state == "CO":  # Colorado appends the status to the name: "Acme LLC, Delinquent June 1, 2024"
        name = re.sub(r",\s*(?:Delinquent|Dissolved|Noncompliant|Withdrawn|Expired|Revoked|Forfeited)\b.*$", "",
                      r.get("entityname") or "")
        return {"name": name or r.get("entityname"), "number": r.get("entityid"), "entity_type": r.get("entitytype"),
                "formed_in": r.get("jurisdictonofformation"), "status": r.get("entitystatus"),
                "registered": day(r.get("entityformdate")),
                "address": ", ".join(filter(None, [r.get("principalcity"), r.get("principalstate")])),
                "agent": r.get("agentorganizationname") or " ".join(filter(None, [r.get("agentfirstname"), r.get("agentlastname")])) or None,
                "page": "https://www.sos.state.co.us/biz/BusinessEntityDetail.do?masterFileId=" + (r.get("entityid") or "")}
    if state == "NY":
        return {"name": r.get("current_entity_name"), "number": r.get("dos_id"), "entity_type": r.get("entity_type"),
                "formed_in": r.get("jurisdiction"), "status": "active (the dataset lists active entities only)",
                "registered": day(r.get("initial_dos_filing_date")), "agent": r.get("dos_process_name"),
                "page": "https://apps.dos.ny.gov/publicInquiry/ (search DOS ID " + (r.get("dos_id") or "") + ")"}
    if state == "TX":
        code = r.get("right_to_transact_business_code")
        return {"name": r.get("taxpayer_name"), "number": r.get("secretary_of_state_sos_or_coa_file_number"),
                "taxpayer_number": r.get("taxpayer_number"), "entity_type": r.get("taxpayer_organizational_type"),
                "status": TX_RIGHT_TO_TRANSACT.get(code, f"right to transact business code {code!r}" if code else None),
                "registered": day(r.get("sos_charter_date")), "tax_liable_from": day(r.get("responsibility_beginning_date")),
                "address": ", ".join(filter(None, [r.get("taxpayer_city"), r.get("taxpayer_state")])),
                "page": "https://mycpa.cpa.state.tx.us/coa/ (search taxpayer number "
                        + (r.get("taxpayer_number") or "") + ")"}
    if state == "CT":
        return {"name": r.get("name"), "number": r.get("accountnumber"), "entity_type": r.get("business_type"),
                "formed_in": r.get("state_or_territory_formation"),
                "status": " - ".join(filter(None, [r.get("status"), r.get("sub_status")])) or None,
                "registered": day(r.get("date_registration")),
                "address": ", ".join(filter(None, [r.get("billingcity"), r.get("billingstate")]))}
    return None


def oregon_entities(rows):
    """Oregon has one row per name or address of an entity; merge them into one record per registry number."""
    merged = {}
    for r in rows:
        e = merged.setdefault(r.get("registry_number"), {
            "name": r.get("business_name"), "number": r.get("registry_number"), "entity_type": r.get("entity_type"),
            "formed_in": r.get("jurisdiction"), "status": "listed (the dataset lists active businesses only)",
            "registered": (r.get("registry_date") or "")[:10] or None,
            "page": (r.get("business_details") or {}).get("url")})
        kind = r.get("associated_name_type") or ""
        if kind == "PRINCIPAL PLACE OF BUSINESS":
            e["address"] = ", ".join(filter(None, [r.get("city"), r.get("state")]))
        elif kind == "REGISTERED AGENT":
            e["agent"] = r.get("entity_of_record_name") or " ".join(filter(None, [r.get("first_name"), r.get("last_name")])) or None
        e["formed_in"] = e["formed_in"] or r.get("jurisdiction")
    return list(merged.values())


def us_states_report(names, fetcher=None, limit=50):
    """Entities whose names start with any of `names` in the state registers published as open data."""
    get = fetcher or (lambda u: fetch_bytes(u, None))
    searched = []
    for state, base, field in US_STATE_DATASETS:
        clauses = " or ".join(f"upper({field}) like '{n.upper().strip().replace(chr(39), chr(39) * 2)}%'" for n in names)
        url = base + "?" + urllib.parse.urlencode({"$where": clauses, "$limit": limit * (6 if state == "OR" else 1)})
        try:
            rows = json.loads(get(url))
        except (FetchError, ValueError) as e:
            yield {"type": "us_state_unavailable", "state": state, "error": str(e), "url": url}
            continue
        entities = oregon_entities(rows) if state == "OR" else [us_state_entity(state, r) for r in rows]
        for e in entities:
            yield {"type": "us_state_entity", "state": state, **{k: v for k, v in e.items() if v}, "url": url}
        searched.append({"state": state, "matches": len(entities), "url": url,
                         **({"truncated": True} if len(rows) >= limit * (6 if state == "OR" else 1) else {})})
    yield {"type": "us_states_summary", "query": names, "searched": searched,
           "note": "names starting with the query; match each entity to the company by address, state of formation, "
                   "and agent before using it. NY, TX and OR list active entities only, so a missing entity there is "
                   "inactive or never registered. Other states' registers are web pages: search them by hand"}


# --------------------------------------------------------------- hiring ----

JOB_BOARDS = [  # provider, pattern for the board token in a careers page or URL
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"),
]
BOARD_PAGES = {"greenhouse": ["https://job-boards.greenhouse.io/{t}", "https://boards.greenhouse.io/{t}"],
               "lever": ["https://jobs.lever.co/{t}"]}
BOARD_JOB_LINK = {"greenhouse": r"/{t}/jobs/(\d+)", "lever": r"jobs\.lever\.co/{t}/([0-9a-f-]{{36}})"}


def find_job_board(text):
    """(provider, token) for the first job board linked from a careers page, or None."""
    for provider, pattern in JOB_BOARDS:
        for m in re.finditer(pattern, text):
            if m.group(1).lower() not in ("embed", "jobs", "js"):
                return provider, m.group(1)
    return None


def job_board_openings(provider, token, get):
    """Open roles as (title, department, location) from the provider's public jobs API."""
    if provider == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/departments"
        jobs = [(j.get("title"), d.get("name"), (j.get("location") or {}).get("name"))
                for d in json.loads(get(url)).get("departments") or [] for j in d.get("jobs") or []]
    elif provider == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        jobs = [(j.get("text"), (j.get("categories") or {}).get("team"), (j.get("categories") or {}).get("location"))
                for j in json.loads(get(url))]
    else:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        jobs = [(j.get("title"), j.get("department"), j.get("location"))
                for j in json.loads(get(url)).get("jobs") or [] if j.get("isListed", True)]
    return jobs, url


def job_history(provider, token, get, months=12, pause=1.0):
    """Approximate open-role counts from monthly Wayback Machine snapshots of the board page."""
    link = BOARD_JOB_LINK.get(provider)
    if not link:
        yield {"type": "jobs_history_unavailable", "provider": provider,
               "note": "this provider's board page is built by JavaScript, so archived copies hold no job list"}
        return
    pattern = re.compile(link.format(t=re.escape(token)))
    rows = []
    for page in BOARD_PAGES[provider]:
        cdx = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
            {"url": page.format(t=token), "output": "json", "filter": "statuscode:200", "collapse": "timestamp:6"})
        rows = (json.loads(get(cdx) or "[]") or [[]])[1:]
        if rows:
            break
    if not rows:
        yield {"type": "jobs_history_unavailable", "provider": provider, "note": "no archived copies of the board page"}
        return
    for ts, original in [(r[1], r[2]) for r in rows[-months:]]:
        date, snap = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", f"https://web.archive.org/web/{ts}id_/{original}"
        try:
            count = len(set(pattern.findall(get(snap))))
        except FetchError as e:
            yield {"type": "jobs_snapshot_unreadable", "date": date, "error": str(e)}
            continue
        yield {"type": "jobs_snapshot", "date": date, "open_roles": count, "approximate": True, "url": snap}
        time.sleep(pause)


def jobs_report(target, history=False, fetcher=None, pause=1.0):
    """Open roles from the company's job board, by department and location, and
    optionally a monthly trend from archived copies of the board page."""
    get = fetcher or (lambda u: fetch(u, None))
    m = re.fullmatch(r"(greenhouse|lever|ashby):([A-Za-z0-9_.-]+)", target)
    board = (m.group(1), m.group(2)) if m else find_job_board(target)
    if not board:
        try:
            board = find_job_board(get(target))
        except FetchError as e:
            yield {"type": "error", "error": str(e)}
            return
    guessed = False
    if not board:  # many careers pages build the job list in JavaScript; try the domain's name as the board
        label = (urllib.parse.urlparse(target).hostname or "").removeprefix("www.").split(".")[0]
        for provider in ("greenhouse", "ashby", "lever"):
            try:
                if label and job_board_openings(provider, label, get)[0]:
                    board, guessed = (provider, label), True
                    break
            except (FetchError, ValueError):
                continue
    if not board:
        yield {"type": "jobs_board_unknown", "url": target,
               "note": "no Greenhouse, Lever or Ashby board is linked from this page; pass provider:token if you know it"}
        return
    provider, token = board
    try:
        jobs, url = job_board_openings(provider, token, get)
    except (FetchError, ValueError) as e:
        yield {"type": "error", "error": f"{provider} board {token}: {e}"}
        return
    if guessed:
        yield {"type": "jobs_board_guessed", "provider": provider, "board": token, "url": url,
               "note": "the careers page links no board, so this one was found by the company's domain name; "
                       "check that its job pages are the company's before using the counts"}

    def tally(i):
        counts = {}
        for j in jobs:
            counts[j[i] or "unspecified"] = counts.get(j[i] or "unspecified", 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))
    yield {"type": "jobs_openings", "provider": provider, "board": token, "open_roles": len(jobs),
           "by_department": tally(1), "by_location": dict(list(tally(2).items())[:15]), "url": url}
    if history:
        yield from job_history(provider, token, get, pause=pause)


# --------------------------------------------------------------- France ----

FR_SEARCH = "https://recherche-entreprises.api.gouv.fr/search?q="
BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
FR_ACCOUNTS_DUE_MONTHS = 8  # filed within 7 months of the year end, plus about a month for BODACC to publish
MAX_BODACC_NOTICES = 1000


def _json_field(value):
    """BODACC stores some fields as JSON text inside the JSON record."""
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def bodacc_url(siren, offset=0):
    query = urllib.parse.urlencode({"where": f'registre like "{siren}"', "order_by": "dateparution",
                                    "limit": 100, "offset": offset})
    return f"{BODACC}?{query}"


def fr_notice_records(notice, capital_before):
    """Typed records for one BODACC notice; returns (records, capital after it)."""
    url = notice.get("url_complete") or f"https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:{notice.get('id')}"
    base = {"date": notice.get("dateparution"), "url": url}
    family = notice.get("familleavis")
    person = _json_field(notice.get("listepersonnes")).get("personne") or {}
    if isinstance(person, list):
        person = person[0] if person else {}
    capital = (person.get("capital") or {}).get("montantCapital")
    capital = float(capital) if capital and re.fullmatch(r"\d+(\.\d+)?", capital) else None
    records = []
    if family == "dpc":
        depot = _json_field(notice.get("depot"))
        descriptif = depot.get("descriptif") or ""
        records.append({"type": "fr_accounts_filed", "year_end": depot.get("dateCloture"),
                        "kind": depot.get("typeDepot"), "confidential": "L. 232-25" in descriptif or "L.232-25" in descriptif,
                        "quote": descriptif or depot.get("typeDepot"), **base})
    elif family == "collective":
        j = _json_field(notice.get("jugement"))
        records.append({"type": "fr_insolvency", "nature": j.get("nature"), "judgment_date": j.get("date"),
                        "court": notice.get("tribunal"), "quote": (j.get("complementJugement") or j.get("nature") or "")[:400],
                        **base})
    elif family == "radiation":
        records.append({"type": "fr_struck_off", "quote": str(_json_field(notice.get("radiationaurcs")))[:300], **base})
    elif family == "creation":
        acte = _json_field(notice.get("acte"))
        records.append({"type": "fr_registered", "registered": acte.get("dateImmatriculation"),
                        "activity_start": acte.get("dateCommencementActivite"), **base})
    elif family == "modification":
        descriptif = _json_field(notice.get("modificationsgenerales")).get("descriptif") or ""
        if "capital" in descriptif:
            direction = "increase" if "augmentation" in descriptif else "reduction" if "diminution" in descriptif else None
            records.append({"type": "fr_capital", "direction": direction, "capital_eur": capital,
                            "previous_capital_eur": capital_before, "quote": descriptif, **base})
        if person.get("administration"):
            records.append({"type": "fr_officer_change", "quote": person["administration"], **base})
        if not records:
            records.append({"type": "fr_notice", "kind": notice.get("familleavis_lib"), "quote": descriptif, **base})
    else:
        records.append({"type": "fr_notice", "kind": notice.get("familleavis_lib"), **base})
    # other notices repeat the capital as it stood when filed, which can be stale
    changed = capital is not None and any(r["type"] in ("fr_capital", "fr_registered") for r in records)
    return records, capital if changed else capital_before


def fr_filing_gaps(year_ends, created, today, closed=None):
    """Financial years whose accounts should have had a BODACC filing notice by
    `today` but have none. BODACC publishes about two million filing notices a
    year, confidential filings included, so a missing year is a signal."""
    end = closed or today
    if not year_ends:
        if created and _add_months(created, 24 + FR_ACCOUNTS_DUE_MONTHS) <= end:
            return [{"type": "fr_flag", "rule": "no accounts-filing notice since the company was registered",
                     "registered": created.isoformat()}]
        return []
    gaps, ye = [], min(year_ends)
    while _add_months(ye, FR_ACCOUNTS_DUE_MONTHS) <= end:
        if ye not in year_ends:
            gaps.append({"type": "fr_flag", "rule": "no accounts-filing notice for this financial year",
                         "year_end": ye.isoformat(), "due_by": _add_months(ye, FR_ACCOUNTS_DUE_MONTHS).isoformat()})
        ye = _add_months(ye, 12)
    return gaps


def fr_report(query, fetcher=None, today=None):
    """French company: register profile and officers, then its BODACC notices as
    typed records, with a flag for each financial year missing an accounts notice."""
    get = fetcher or (lambda u: fetch(u, None))
    today = today or dt.date.today()
    siren = re.sub(r"\s", "", query)
    search_url = FR_SEARCH + urllib.parse.quote(siren if re.fullmatch(r"\d{9}", siren) else query)
    results = json.loads(get(search_url)).get("results") or []
    if not re.fullmatch(r"\d{9}", siren):
        for r in results[:10]:
            yield {"type": "fr_candidate", "siren": r.get("siren"), "name": r.get("nom_complet"),
                   "city": (r.get("siege") or {}).get("libelle_commune"), "created": r.get("date_creation"),
                   "status": r.get("etat_administratif")}
        yield {"type": "fr_note", "note": "run mr.py fr <SIREN> with the right company's SIREN"}
        return
    company = next((r for r in results if r.get("siren") == siren), None)
    created = closed = None
    if company:
        seat = company.get("siege") or {}
        created, closed = _date(company.get("date_creation")), _date(company.get("date_fermeture"))
        yield {"type": "fr_company", "siren": siren, "name": company.get("nom_complet"),
               "status": {"A": "active", "C": "closed"}.get(company.get("etat_administratif"), company.get("etat_administratif")),
               "created": company.get("date_creation"), "closed": company.get("date_fermeture"),
               "legal_form_code": company.get("nature_juridique"), "activity": company.get("activite_principale"),
               "head_office": seat.get("adresse"), "headcount_band": company.get("tranche_effectif_salarie"),
               "headcount_year": company.get("annee_tranche_effectif_salarie"),
               "category": company.get("categorie_entreprise"), "url": search_url,
               "page": f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"}
        for d in company.get("dirigeants") or []:
            name = d.get("denomination") or " ".join(x for x in (d.get("prenoms"), d.get("nom")) if x)
            yield {"type": "fr_officer", "name": name, "role": d.get("qualite"), "born": d.get("date_de_naissance"),
                   "siren": d.get("siren"), "url": search_url}
        finances = company.get("finances")
        if finances:
            for year, figures in sorted(finances.items()):
                yield {"type": "fr_finances", "year": year, "revenue_eur": figures.get("ca"),
                       "net_income_eur": figures.get("resultat_net"), "url": search_url}
        else:
            yield {"type": "fr_finances", "published": False, "url": search_url,
                   "note": "the register publishes no figures: the accounts were filed with a confidentiality "
                           "declaration (art. L. 232-25) or not filed; the fr_accounts_filed records show which"}
    else:
        yield {"type": "fr_note", "note": f"the register search returned no company with SIREN {siren}", "url": search_url}
    notices, offset = [], 0
    while offset < MAX_BODACC_NOTICES:
        page = json.loads(get(bodacc_url(siren, offset)))
        batch = page.get("results") or []
        notices += batch
        offset += len(batch)
        if not batch or offset >= (page.get("total_count") or 0):
            break
    capital, year_ends, counts = None, set(), {}
    for n in notices:
        records, capital = fr_notice_records(n, capital)
        for r in records:
            counts[r["type"]] = counts.get(r["type"], 0) + 1
            if r["type"] == "fr_accounts_filed" and r.get("year_end"):
                year_ends.add(_date(r["year_end"]))
            yield r
    for r in fr_filing_gaps(year_ends, created, today, closed):
        counts["fr_flag"] = counts.get("fr_flag", 0) + 1
        yield {**r, "url": bodacc_url(siren)}
    yield {"type": "fr_summary", "siren": siren, "bodacc_notices": len(notices), "bodacc_url": bodacc_url(siren),
           "counts": counts, "truncated": len(notices) >= MAX_BODACC_NOTICES}


# ----------------------------------------------------------- Luxembourg ----

CDB_DATASET = "https://data.public.lu/api/1/datasets/donnees-comptes-annuels/"
LU_DUE_MONTHS = 7  # accounts approved within 6 months of the year end, then filed within a month
LU_FIELDS = [  # field, label prefix (lower case, spaces collapsed); the first match in a declaration wins
    ("total_assets", "total du bilan (actif)"),
    ("equity", "capitaux propres"),
    ("cash", "avoirs en banques"),
    ("debts", "dettes"),
    ("convertible_loans", "emprunts convertibles"),
    ("bank_debt", "dettes envers des établissements de crédit"),
    ("owed_to_affiliates", "dettes envers des entreprises liées"),
    ("net_result", "résultat de l'exercice"),
    ("turnover", "chiffre d'affaires net"),
    ("staff_costs", "frais de personnel"),
]
LU_EXACT = {"equity", "debts", "net_result"}  # these labels must match whole, not as a prefix


def cdb_quarters(get, quarters):
    """The newest `quarters` quarterly deposit files of the Centrale des Bilans open data."""
    resources = json.loads(get(CDB_DATASET)).get("resources") or []
    files = []
    for r in resources:
        m = re.match(r"deposit-(\d{4})q([1-4])\.xml$", r.get("title") or "")
        if m:
            files.append((int(m.group(1)), int(m.group(2)), r["url"], r.get("filesize")))
    return [(f"{y}q{q}", url, size) for y, q, url, size in sorted(files, reverse=True)[:quarters]]


def cdb_stream_blocks(url, rcs, chunk=1 << 20):
    """Stream a quarterly file and return the <Declarer> blocks for one RCS number, decoded."""
    needle = f"<RcsNumber>{rcs}</RcsNumber>".encode()
    request = urllib.request.Request(url, headers={"User-Agent": "muckraker"})
    found, buf = [], b""
    with urllib.request.urlopen(request, timeout=60) as r:
        while True:
            data = r.read(chunk)
            if not data:
                break
            buf += data
            while True:
                end = buf.find(b"</Declarer>")
                if end < 0:
                    break
                block, buf = buf[:end + 11], buf[end + 11:]
                if needle in block:
                    found.append(block[block.rfind(b"<Declarer>"):].decode("iso8859_15", errors="replace"))
            if len(buf) > 64 << 20:
                raise FetchError(f"no </Declarer> in 64 MB of {url}")
    return found


def lu_declarations(block):
    """One record per <Declaration> in a Declarer block: period, deposit date and figures."""
    out = []
    name = re.search(r"<LegalUnitName>([^<]*)</LegalUnitName>", block)
    for d in re.finditer(r"<Declaration\b([^>]*)>(.*?)</Declaration>", block, re.S):
        attrs, body = d.group(1), d.group(2)
        tag = lambda t: (re.search(rf"<{t}>([^<]*)</{t}>", body) or [None, None])[1]
        figures, labels = {}, {}
        for m in re.finditer(r"<Label>([^<]*)</Label>\s*<Data>([^<]*)</Data>", body):
            label = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            low = label.lower()
            for field, prefix in LU_FIELDS:
                if field in figures:
                    continue
                if (low == prefix) if field in LU_EXACT else low.startswith(prefix):
                    try:
                        figures[field] = float(m.group(2))
                    except ValueError:
                        continue
                    labels[field] = f"{label} {m.group(2)}"
        out.append({"name": html.unescape(name.group(1)) if name else None,
                    "form": (re.search(r'type="([^"]+)"', attrs) or [None, None])[1],
                    "start": tag("StartDate"), "end": tag("EndDate"), "deposited": (tag("RCSDepositDate") or "")[:10] or None,
                    "doc": tag("ID_Doc"), "currency": tag("Currency"), "figures": figures, "labels": labels})
    return out


def lu_report(rcs, quarters=12, workers=4, save=None, fetcher=None, streamer=None, today=None):
    """Luxembourg company accounts from the Centrale des Bilans open data: each
    filing's deposit date against the deadline, each year's main figures, and flags
    for late filing and negative equity."""
    import concurrent.futures
    get = fetcher or (lambda u: fetch(u, None))
    stream = streamer or cdb_stream_blocks
    today = today or dt.date.today()
    rcs = re.sub(r"\s", "", rcs).upper()
    files = cdb_quarters(get, quarters)
    hits, saved = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(stream, url, rcs): (q, url) for q, url, _ in files}
        for fut in concurrent.futures.as_completed(futures):
            q, url = futures[fut]
            try:
                blocks = fut.result()
            except (FetchError, OSError, http.client.HTTPException) as e:
                yield {"type": "lu_quarter_unreadable", "quarter": q, "error": str(e), "url": url}
                continue
            for b in blocks:
                saved.append(f"<!-- {url} -->\n{b}")
                hits += [dict(d, quarter=q, url=url) for d in lu_declarations(b)]
    if save and saved:
        with open(save, "w", encoding="utf-8") as f:
            f.write("<CdbExtract>\n" + "\n".join(saved) + "\n</CdbExtract>\n")
    years = {}
    for d in sorted(hits, key=lambda d: (d["end"] or "", d["deposited"] or "")):
        years.setdefault(d["end"], []).append(d)
    flags = 0
    for end, decls in sorted(years.items()):
        end_date = _date(end)
        first = min((d["deposited"] for d in decls if d["deposited"]), default=None)
        due = _add_months(end_date, LU_DUE_MONTHS) if end_date else None
        late = (_date(first) - due).days if first and due else None
        yield {"type": "lu_accounts_filed", "rcs": rcs, "name": decls[-1]["name"], "year_end": end,
               "forms": sorted({d["form"] for d in decls if d["form"]}), "deposited": first,
               "due": due and due.isoformat(), "days_late": max(late, 0) if late is not None else None,
               "filings": len({d["doc"] for d in decls}), "url": decls[0]["url"]}
        if late and late > 0:
            flags += 1
            yield {"type": "lu_flag", "flag": "late accounts", "severity": "major", "year_end": end,
                   "deposited": first, "due": due.isoformat(), "days_late": late,
                   "recent": bool(end_date and (today - end_date).days <= 3 * 366),
                   "rule": "accounts are due within 7 months of the year end (approval within 6 months, filing "
                           "within 1 month after)", "url": decls[0]["url"]}
        figures, labels = {}, {}
        for d in decls:  # the latest filing for the year wins
            figures.update(d["figures"])
            labels.update(d["labels"])
        yield {"type": "lu_accounts_year", "year_end": end, "currency": decls[-1]["currency"], **figures,
               "quotes": labels, "url": decls[-1]["url"]}
    latest = max(years) if years else None
    if latest:
        equity = next((d["figures"].get("equity") for d in reversed(years[latest]) if "equity" in d["figures"]), None)
        if equity is not None and equity < 0:
            flags += 1
            yield {"type": "lu_flag", "flag": "negative equity", "severity": "major", "year_end": latest,
                   "equity": equity, "quote": next(d["labels"]["equity"] for d in reversed(years[latest]) if "equity" in d["labels"]),
                   "rule": "equity below zero at the latest year end; when losses exceed half the capital, "
                           "Luxembourg law requires the shareholders to decide on dissolution (art. 480-2 / 1100-2)",
                   "url": years[latest][-1]["url"]}
    yield {"type": "lu_summary", "rcs": rcs, "years": len(years), "flags": flags,
           "quarters_searched": [q for q, _, _ in files], "saved_extract": save if save and saved else None,
           "note": "a filing appears in the quarter it was deposited, so years filed before the oldest quarter "
                   "searched are missing; raise --quarters to look further back"}


# -------------------------------------------------------------- Ireland ----

CRO_API = "https://opendata.cro.ie/api/3/action/"
CRO_COMPANIES = "3fef41bc-b8f4-4b10-8434-ce51c29b1bba"
IE_RETURN_DAYS = 56  # an annual return, with its accounts, is due within 56 days of its annual return date


def cro_search_url(resource, filters=None, q=None, limit=100):
    params = {"resource_id": resource, "limit": limit}
    if filters:
        params["filters"] = json.dumps(filters)
    if q:
        params["q"] = q
    return CRO_API + "datastore_search?" + urllib.parse.urlencode(params)


def _cro_date(s):
    return _date(s[:10]) if s else None


def ie_report(query, fetcher=None, today=None):
    """Irish company from the CRO's open data: profile, each annual return's
    accounts filing with the days it took, and flags for late or overdue returns."""
    get = fetcher or (lambda u: fetch(u, None))
    today = today or dt.date.today()
    number = re.sub(r"\s", "", query)
    if not re.fullmatch(r"\d{1,7}", number):
        # the datastore's full-text search stems words ("tines" finds "tine"), so match name words instead
        name = re.sub(r"[%_\\]", "", query).replace("'", "''").strip()
        sql = (f"SELECT * FROM \"{CRO_COMPANIES}\" WHERE company_name ILIKE '{name}%' "
               f"OR company_name ILIKE '% {name}%' ORDER BY company_name LIMIT 20")
        url = CRO_API + "datastore_search_sql?" + urllib.parse.urlencode({"sql": sql})
        for r in json.loads(get(url))["result"]["records"]:
            yield {"type": "ie_candidate", "company_num": r.get("company_num"), "name": r.get("company_name"),
                   "status": (r.get("company_status") or "").strip(), "registered": (r.get("company_reg_date") or "")[:10],
                   "address": r.get("company_address_4")}
        yield {"type": "ie_note", "note": "run mr.py ie <CRO number> with the right company's number", "url": url}
        return
    url = cro_search_url(CRO_COMPANIES, {"company_num": int(number)})
    records = json.loads(get(url))["result"]["records"]
    if not records:
        yield {"type": "ie_note", "note": f"the CRO open data has no company {number}", "url": url}
        return
    c = records[0]
    nard, last_ar = _cro_date(c.get("nard")), _cro_date(c.get("last_ar_date"))
    status = (c.get("company_status") or "").strip()
    yield {"type": "ie_company", "company_num": c.get("company_num"), "name": c.get("company_name"), "status": status,
           "status_date": (c.get("company_status_date") or "")[:10] or None, "company_type": c.get("company_type"),
           "registered": (c.get("company_reg_date") or "")[:10], "dissolved": (c.get("comp_dissolved_date") or "")[:10] or None,
           "address": ", ".join(x for x in (c.get(f"company_address_{i}") for i in range(1, 5)) if x),
           "name_since": (c.get("company_name_eff_date") or "")[:10] or None, "nace": c.get("nace_v2_code"),
           "last_annual_return_date": last_ar and last_ar.isoformat(), "next_annual_return_date": nard and nard.isoformat(),
           "last_accounts_to": (c.get("last_accounts_date") or "")[:10] or None, "url": url}
    flags = 0
    if status == "Normal" and nard and today > nard + dt.timedelta(days=IE_RETURN_DAYS) and (not last_ar or last_ar < nard):
        flags += 1
        yield {"type": "ie_flag", "flag": "annual return overdue", "severity": "major",
               "annual_return_date": nard.isoformat(), "due": (nard + dt.timedelta(days=IE_RETURN_DAYS)).isoformat(),
               "rule": f"an annual return is due within {IE_RETURN_DAYS} days of its annual return date "
                       "(Companies Act 2014, s. 343)", "url": url}
    package = json.loads(get(CRO_API + "package_show?id=financial-statements"))["result"]
    resources = sorted((r for r in package.get("resources") or [] if r.get("datastore_active")), key=lambda r: r.get("name") or "")
    filings = []
    for r in resources:
        fs_url = cro_search_url(r["id"], {"company_num": str(int(number))})
        for f in json.loads(get(fs_url))["result"]["records"]:
            filings.append((r.get("name"), fs_url, f))
    for dataset, fs_url, f in filings:
        received, ard = _cro_date(f.get("submission_rec_date")), _cro_date(f.get("submission_eff_date"))
        days = (received - ard).days if received and ard else None
        yield {"type": "ie_accounts_filed", "accounts_to": (f.get("submissions_accounts_to_date") or "")[:10] or None,
               "annual_return_date": ard and ard.isoformat(), "received": received and received.isoformat(),
               "days_after_return_date": days, "submission": f.get("submission_num"), "dataset": dataset, "url": fs_url}
        if days is not None and days > IE_RETURN_DAYS:
            flags += 1
            yield {"type": "ie_flag", "flag": "late annual return", "severity": "major",
                   "accounts_to": (f.get("submissions_accounts_to_date") or "")[:10] or None,
                   "annual_return_date": ard.isoformat(), "received": received.isoformat(),
                   "days_late": days - IE_RETURN_DAYS,
                   "rule": f"the annual return and its accounts are due within {IE_RETURN_DAYS} days of the annual return date",
                   "url": fs_url}
    covered = [r.get("name") for r in resources]
    latest_ard = max((_cro_date(f.get("submission_eff_date")) for _, _, f in filings if f.get("submission_eff_date")), default=None)
    yield {"type": "ie_summary", "company_num": c.get("company_num"), "accounts_filings": len(filings), "flags": flags,
           "financial_statement_datasets": covered,
           "note": "the CRO publishes accounts filings in yearly datasets, so the newest returns may not be in them yet"
                   + (f"; the profile's last annual return date ({last_ar.isoformat()}) is newer than the latest filing here, "
                      "so check its received date in a copy of the filing list" if last_ar and (not latest_ard or last_ar > latest_ard) else "")}


# --------------------------------------------------------------- Norway ----

BRREG_API = "https://data.brreg.no/enhetsregisteret/api"
BRREG_ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
BRREG_NOTICES = "https://w2.brreg.no/kunngjoring"
NO_ACCOUNTS_MONTHS = 7  # adopted within 6 months of the year end (aksjeloven § 5-5), filed within 1 month (regnskapsloven § 8-2)
NO_RECENT_YEARS = 3
NO_MAX_NOTICES = 60  # notice pages fetched one by one; older ones are listed but not opened
# notice types (as the list names them) whose text the report reads; officer and address changes are only counted
_NO_READ_RE = re.compile(r"årsregnskap|kapital|kreditorvarsel|meldepliktig avtale|konkurs|tvangs|avvikling|oppløsning|"
                         r"fusjon|fisjon|akkord|rekonstruksjon", re.I)
_NO_WINDUP_RE = re.compile(r"konkurs|tvangs|avvikling|oppløsning|rekonstruksjon|akkord", re.I)
_NO_OFFICER_RE = re.compile(r"styre|daglig leder|revisor|prokura|signatur", re.I)
_NO_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def _no_date(s):
    m = _NO_DATE_RE.search(s or "")
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    except ValueError:
        return None


def _add_months_end(d, months):
    """The last day of the month `months` after d's month: 31.01 + 7 -> 31.08."""
    y, m = divmod(d.month - 1 + months + 1, 12)
    return dt.date(d.year + y, m + 1, 1) - dt.timedelta(days=1)


def parse_no_notice_list(page):
    """(date, type, kid) for each row of a kunngjøringer list page; a row with no
    date shares the date of the row above (several notices published together)."""
    out, last = [], None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        kid = re.search(r"hent_en\.jsp\?kid=(\d+)", row)
        if not kid:
            continue
        cells = [text_of(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c]
        date = next((_no_date(c) for c in cells if _NO_DATE_RE.fullmatch(c)), None) or last
        kind = next((c for c in cells if not _NO_DATE_RE.fullmatch(c)), "")
        last = date
        out.append((date, kind, kid.group(1)))
    return out


def parse_no_notice(page):
    """Title and plain text of one kunngjøring page, from its heading to the
    register's signature line."""
    text = text_of(re.sub(r"<(script|style)\b.*?</\1\s*>", " ", page, flags=re.S | re.I))
    start = text.find("Organisasjonsnummer")
    end = re.search(r"(?:Foretaksregisteret|Regnskapsregisteret|Konkursregisteret|Enhetsregisteret)\s+\d{2}\.\d{2}\.\d{4}",
                    text[start:]) if start >= 0 else None
    body = text[start:start + end.end()] if end else text[start:start + 3000] if start >= 0 else text[:3000]
    return body


def _no_money(s):
    """'1.000.000,00' -> 1000000.0"""
    try:
        return float(s.replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "."))
    except ValueError:
        return None


def no_report(query, fetcher=None, today=None):
    """Norwegian company from Brønnøysund's open data: Enhetsregisteret profile,
    officers, the last three years of filed accounts, and the announcements
    (kunngjøringer), with flags for bankruptcy and winding-up, late or missing
    accounts, and negative equity."""
    get = fetcher or (lambda u: fetch(u, None))
    today = today or dt.date.today()
    orgnr = re.sub(r"[\s.]", "", query)
    if not re.fullmatch(r"\d{9}", orgnr):
        url = f"{BRREG_API}/enheter?" + urllib.parse.urlencode({"navn": query, "size": 20})
        for e in (json.loads(get(url)).get("_embedded") or {}).get("enheter", []):
            yield {"type": "no_candidate", "orgnr": e.get("organisasjonsnummer"), "name": e.get("navn"),
                   "form": (e.get("organisasjonsform") or {}).get("kode"), "founded": e.get("stiftelsesdato"),
                   "employees": e.get("antallAnsatte"), "bankrupt": e.get("konkurs"),
                   "address": ", ".join((e.get("forretningsadresse") or {}).get("adresse") or []),
                   "municipality": (e.get("forretningsadresse") or {}).get("kommune")}
        yield {"type": "no_note", "note": "run mr.py no <organisasjonsnummer> with the right company's number", "url": url}
        return
    url = f"{BRREG_API}/enheter/{orgnr}"
    try:
        e = json.loads(get(url))
    except FetchError as err:
        yield {"type": "no_note", "note": f"Enhetsregisteret has no current unit {orgnr} ({err}); a deleted company "
                                          "answers 410 or 404", "url": url}
        return
    capital = e.get("kapital") or {}
    address = e.get("forretningsadresse") or {}
    yield {"type": "no_company", "orgnr": orgnr, "name": e.get("navn"), "form": (e.get("organisasjonsform") or {}).get("kode"),
           "founded": e.get("stiftelsesdato"), "registered": e.get("registreringsdatoEnhetsregisteret"),
           "in_foretaksregisteret": e.get("registrertIForetaksregisteret"),
           "address": ", ".join(address.get("adresse") or []) + (f", {address.get('postnummer')} {address.get('poststed')}"
                                                                  if address.get("poststed") else ""),
           "nace": (e.get("naeringskode1") or {}).get("kode"), "activity": " ".join(e.get("aktivitet") or []) or None,
           "employees": e.get("antallAnsatte"), "share_capital": capital.get("belop"), "shares": capital.get("antallAksjer"),
           "capital_entered": capital.get("innfortDato"), "articles_date": e.get("vedtektsdato"),
           "in_group": e.get("erIKonsern"), "last_accounts_year": e.get("sisteInnsendteAarsregnskap"),
           "bankrupt": e.get("konkurs"), "bankrupt_since": e.get("konkursdato"),
           "being_wound_up": e.get("underAvvikling"), "wound_up_since": e.get("underAvviklingDato"),
           "compulsory_dissolution": e.get("underTvangsavviklingEllerTvangsopplosning"),
           "former_names": e.get("historiskeNavn") or [], "url": url}
    flags = 0
    for key, since, what in (("konkurs", "konkursdato", "bankruptcy proceedings opened (konkurs)"),
                             ("underAvvikling", "underAvviklingDato", "being wound up (under avvikling)"),
                             ("underTvangsavviklingEllerTvangsopplosning", None,
                              "under compulsory winding-up or dissolution (tvangsavvikling or tvangsoppløsning)")):
        if e.get(key):
            flags += 1
            yield {"type": "no_flag", "flag": what, "severity": "major", "since": e.get(since) if since else None,
                   "quote": f'"{key}": true', "url": url}
    if capital.get("antallAksjer") == 1:
        yield {"type": "no_note", "note": "the share capital is one share, so the company has a single shareholder; "
                                          "Enhetsregisteret does not name it (the accounts' notes or a § 3-8 agreement "
                                          "notice usually do)", "url": url}

    sub_url = f"{BRREG_API}/underenheter?overordnetEnhet={orgnr}"
    try:
        for s in (json.loads(get(sub_url)).get("_embedded") or {}).get("underenheter", []):
            yield {"type": "no_subunit", "orgnr": s.get("organisasjonsnummer"), "name": s.get("navn"),
                   "employees": s.get("antallAnsatte"), "started": s.get("oppstartsdato"),
                   "address": ", ".join((s.get("beliggenhetsadresse") or {}).get("adresse") or []), "url": sub_url}
    except FetchError:
        pass

    roles_url = f"{url}/roller"
    try:
        roles = json.loads(get(roles_url))
    except FetchError as err:
        roles = {}
        yield {"type": "error", "error": str(err), "url": roles_url}
    for group in roles.get("rollegrupper") or []:
        for r in group.get("roller") or []:
            person, unit = (r.get("person") or {}).get("navn") or {}, r.get("enhet") or {}
            name = " ".join(x for x in (person.get("fornavn"), person.get("mellomnavn"), person.get("etternavn")) if x)
            # month and year only: enough to tell a director from a namesake on a sanctions list
            born = ((r.get("person") or {}).get("fodselsdato") or "")[:7] or None
            yield {"type": "no_officer", "role": (r.get("type") or {}).get("beskrivelse"),
                   "name": name or " ".join(unit.get("navn") or []) or None, "born": born,
                   "orgnr": unit.get("organisasjonsnummer"),
                   "resigned": r.get("fratraadt"), "group_changed": group.get("sistEndret"), "url": roles_url}

    accounts_url = f"{BRREG_ACCOUNTS}/{orgnr}"
    try:
        accounts = json.loads(get(accounts_url))
    except FetchError:  # 404 when nothing is filed
        accounts = []
    years = []
    for a in sorted(accounts if isinstance(accounts, list) else [], key=lambda a: (a.get("regnskapsperiode") or {}).get("tilDato") or ""):
        period = a.get("regnskapsperiode") or {}
        eq = (a.get("egenkapitalGjeld") or {})
        assets, result = a.get("eiendeler") or {}, a.get("resultatregnskapResultat") or {}
        operating = result.get("driftsresultat") or {}
        debt = eq.get("gjeldOversikt") or {}
        finance = (result.get("finansresultat") or {}).get("finanskostnad") or {}
        audit = a.get("revisjon") or {}
        year = {"period_start": period.get("fraDato"), "period_end": period.get("tilDato"), "currency": a.get("valuta"),
                "revenue": (operating.get("driftsinntekter") or {}).get("sumDriftsinntekter"),
                "staff_costs": (operating.get("driftskostnad") or {}).get("loennskostnad"),
                "operating_result": operating.get("driftsresultat"), "net_result": result.get("aarsresultat"),
                "equity": (eq.get("egenkapital") or {}).get("sumEgenkapital"), "total_debt": debt.get("sumGjeld"),
                "long_term_debt": (debt.get("langsiktigGjeld") or {}).get("sumLangsiktigGjeld"),
                "short_term_debt": (debt.get("kortsiktigGjeld") or {}).get("sumKortsiktigGjeld"),
                "cash": assets.get("sumBankinnskuddOgKontanter"), "receivables": assets.get("sumFordringer"),
                "total_assets": assets.get("sumEiendeler"), "group_interest": finance.get("rentekostnadSammeKonsern"),
                "audited": not audit.get("ikkeRevidertAarsregnskap") and not audit.get("fravalgRevisjon"),
                "audit_opted_out": audit.get("fravalgRevisjon"), "parent_company": (a.get("virksomhet") or {}).get("morselskap"),
                "small_company": (a.get("regnkapsprinsipper") or {}).get("smaaForetak"),
                "pdf": f"{BRREG_ACCOUNTS}/aarsregnskap/kopi/{orgnr}/{(period.get('tilDato') or '')[:4]}", "url": accounts_url}
        years.append(year)
        yield {"type": "no_accounts_year", **year}
    if years and isinstance(years[-1]["equity"], (int, float)) and years[-1]["equity"] < 0:
        flags += 1
        yield {"type": "no_flag", "flag": "negative equity", "severity": "major", "period_end": years[-1]["period_end"],
               "equity": years[-1]["equity"], "quote": f'"sumEgenkapital": {years[-1]["equity"]}', "url": accounts_url}

    list_url = f"{BRREG_NOTICES}/hent_nr.jsp?orgnr={orgnr}"
    try:
        notices = parse_no_notice_list(get(list_url))
    except FetchError as err:
        notices = []
        yield {"type": "error", "error": f"announcements: {err}", "url": list_url}
    filed, read = [], 0
    since = today - dt.timedelta(days=730)
    for date, kind, kid in notices:
        notice_url = f"{BRREG_NOTICES}/hent_en.jsp?kid={kid}&sokeverdi={orgnr}&spraak=nb"
        record = {"type": "no_notice", "date": date and date.isoformat(), "notice": kind, "url": notice_url}
        # officer and auditor changes are read only for the last 24 months, where a departure matters
        recent_officers = date is not None and date >= since and _NO_OFFICER_RE.search(kind)
        if not (_NO_READ_RE.search(kind) or recent_officers) or read >= NO_MAX_NOTICES:
            yield record
            continue
        read += 1
        try:
            text = parse_no_notice(get(notice_url))
        except FetchError as err:
            yield {**record, "error": str(err)}
            continue
        received = re.search(r"har den (\d{2}\.\d{2}\.\d{4}) mottatt", text)
        period = re.search(r"perioden fra (\d{2}\.\d{2}\.\d{4}) til (\d{2}\.\d{2}\.\d{4})", text)
        if received and period:
            end = _no_date(period.group(2))
            got = _no_date(received.group(1))
            if any(r["period_end"] == end.isoformat() and r["received"] == got.isoformat() for r in filed):
                yield {**record, "note": "the same accounts filing as an earlier notice"}  # Brreg sometimes lists it twice
                continue
            due = _add_months_end(end, NO_ACCOUNTS_MONTHS)
            row = {"type": "no_accounts_filed", "period_start": _no_date(period.group(1)).isoformat(),
                   "period_end": end.isoformat(), "received": got.isoformat(), "due": due.isoformat(),
                   "days_late": max(0, (got - due).days), "parent_company": "ikke registrert som morselskap" not in text,
                   "quote": f"Regnskapsregisteret har den {received.group(1)} mottatt komplett", "url": notice_url}
            filed.append(row)
            yield row
            if got > due:
                flags += 1
                recent = end >= today - dt.timedelta(days=365 * NO_RECENT_YEARS)
                yield {"type": "no_flag", "flag": "late accounts", "severity": "major" if recent else "minor",
                       "recent": recent, "period_end": end.isoformat(), "received": got.isoformat(), "due": due.isoformat(),
                       "days_late": (got - due).days,
                       "rule": f"accounts are due {NO_ACCOUNTS_MONTHS} months after the year end at the latest: adopted "
                               "within six months (aksjeloven § 5-5) and filed within one month of adoption "
                               "(regnskapsloven § 8-2); the deadline assumes adoption on the last permitted day",
                       "quote": row["quote"], "url": notice_url}
            continue
        capital = re.search(r"Kapital\s*:\s*NOK\s*([\d.\s]+,\d{2})", text)
        reduced = re.search(r"nedsatt fra NOK\s*([\d.\s]+,\d{2}) til NOK\s*([\d.\s]+,\d{2})", text)
        raised = re.search(r"forhøyet fra NOK\s*([\d.\s]+,\d{2}) til NOK\s*([\d.\s]+,\d{2})", text)
        if reduced or raised:
            m = reduced or raised
            yield {"type": "no_capital", "date": record["date"], "change": "reduction" if reduced else "increase",
                   "from": _no_money(m.group(1)), "to": _no_money(m.group(2)), "notice": kind,
                   "repaid_to_shareholders": bool(reduced and re.search(r"utbetal|tilbakebetal", text, re.I)),
                   "quote": text[m.start():m.start() + 200].split(".  ")[0], "url": notice_url}
            continue
        if capital:
            yield {"type": "no_capital", "date": record["date"], "change": "registered", "to": _no_money(capital.group(1)),
                   "notice": kind, "quote": capital.group(0), "url": notice_url}
            continue
        agreement = re.search(r"avtale etter aksjeloven § 3-8 mellom selskapet og (.+?)\.\s", text + " ")
        if agreement:
            yield {"type": "no_agreement", "date": record["date"], "counterparty": agreement.group(1).strip(),
                   "note": "an agreement under aksjeloven § 3-8 is between the company and a shareholder or a party close "
                           "to one, so the counterparty is often the owner",
                   "quote": agreement.group(0).strip(), "url": notice_url}
            continue
        if _NO_WINDUP_RE.search(kind):
            recent = date is not None and date >= today - dt.timedelta(days=365 * NO_RECENT_YEARS)
            flags += 1
            yield {"type": "no_flag", "flag": f"announcement: {kind}", "severity": "major" if recent else "minor",
                   "recent": recent, "date": record["date"],
                   "quote": text.split(")", 1)[-1].strip()[:200],  # after "Organisasjonsnummer … (NAME)"
                   "url": notice_url}
            continue
        yield {**record, "text": text[:400]}

    # a year whose accounts are past their deadline and not filed
    ends = sorted({r["period_end"] for r in filed} | {y["period_end"] for y in years if y["period_end"]})
    if ends and not e.get("konkurs") and not e.get("underAvvikling"):
        latest = dt.date.fromisoformat(ends[-1])
        next_end = _add_months_end(latest, 12)
        due = _add_months_end(next_end, NO_ACCOUNTS_MONTHS)
        if today > due:
            flags += 1
            yield {"type": "no_flag", "flag": "accounts not filed", "severity": "major", "period_end": next_end.isoformat(),
                   "due": due.isoformat(), "latest_filed_period_end": latest.isoformat(),
                   "note": "no accounts for the year after the latest filed one, and their deadline has passed; a change "
                           "of year end can also cause this, so check the register before calling them missing",
                   "url": list_url}
    officer_notices = [n for n in notices if n[0] and n[0] >= since and _NO_OFFICER_RE.search(n[1])]
    yield {"type": "no_summary", "orgnr": orgnr, "accounts_years": len(years), "accounts_filed": len(filed),
           "notices": len(notices), "notices_read": read, "flags": flags,
           "officer_or_auditor_notices_last_24_months": len(officer_notices),
           "note": "Enhetsregisteret lists current officers only; their changes are in the announcements. Shareholders "
                   "are in Aksjonærregisteret, which has no open access. The accounts' notes (parent company, group loans, "
                   "going concern) are only in the filed PDFs at each no_accounts_year's pdf link: save their pages with "
                   "mr.py uk-pages", "url": list_url}


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


def _json_strings(value, depth=0):
    """Every string in a JSON value, decoding strings that hold JSON themselves."""
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        for v in value:
            yield from _json_strings(v, depth)
    elif isinstance(value, str):
        inner = _json_field(value) if depth < 3 and value[:1] in "{[" else None
        if inner:
            yield from _json_strings(inner, depth + 1)
        else:
            yield value
    elif value is not None:
        yield str(value)


def searchable_text(body):
    """Searchable text of a fetched page. A JSON body (an API response) is decoded
    first, so escaped characters such as \\u00e9 match the quote's accented letters."""
    if body.lstrip()[:1] in ("{", "["):
        try:
            return text_of(" \n ".join(_json_strings(json.loads(body))))
        except ValueError:
            pass
    return text_of(body)


def quote_check(url, quote, user_agent, context_chars):
    try:
        if url.startswith(("http://", "https://")):
            body = fetch(url, user_agent)
        else:  # a saved extract, such as mr.py lu --save
            with open(url, encoding="utf-8", errors="replace") as f:
                body = f.read()
        page = searchable_text(body).lower()
    except FetchError as e:
        emit({"type": "quote_check", "url": url, "quote": quote, "found": None, "unreachable": str(e),
              "note": "the page could not be fetched; check the quote in a browser"})
        return
    pos, span = find_quote(page, quote)
    record = {"type": "quote_check", "url": url, "quote": quote, "found": pos >= 0}
    if pos >= 0:
        record["context"] = page[max(0, pos - context_chars): pos + span + context_chars]
    emit(record)


# --------------------------------------------------------------- Finland ----

PRH_YTJ = "https://avoindata.prh.fi/opendata-ytj-api/v3"
PRH_NOTICES = "https://avoindata.prh.fi/opendata-registerednotices-api/v3"
PRH_XBRL = "https://avoindata.prh.fi/opendata-xbrl-api/v3"
FI_ACCOUNTS_MONTHS = 8  # adopted within 6 months of the year end (OYL 5:3), filed within 2 months (KPL 3:9)
FI_RECENT_YEARS = 3
FI_SITUATIONS = {"KONK": "bankruptcy", "SANE": "restructuring", "SELTILA": "liquidation"}
FI_STATUS = {"1": "pending", "2": "valid", "5": "business ID invalidated"}
FI_TOPICS = {  # entry codes in the registered notices, grouped for the timeline
    "capital": {"KOROI", "ALE", "OSMIT", "ANTIP", "ANTIK", "VAIPA", "JAPPO"},
    "board": {"HAL", "HALE", "TOIM", "JOHT", "HN", "HNE"},
    "auditor": {"TILTAR"},
    "accounts": {"TASE"},
    "insolvency": {"KONALK", "KONLOP", "KONRAU", "SANE", "SELTILA"},
    "merger": {"FUUSI"},
    "removal": {"POISTO"},
}
FI_INSOLVENCY_CODES = {"KONALK", "SANE", "SELTILA"}


def _en(descriptions):
    """The English text from PRH's descriptions list (languageCode 3), else the first one."""
    for d in descriptions or []:
        if d.get("languageCode") == "3":
            return d.get("description")
    return (descriptions or [{}])[0].get("description")


def _fi_city(post_offices):
    for p in post_offices or []:
        if p.get("languageCode") == "1":
            return p.get("city")
    return (post_offices or [{}])[0].get("city")


def fi_code_list(get, code):
    """{code: English description} from a PRH code list (tab-separated text)."""
    out = {}
    for line in decode_body(get(f"{PRH_NOTICES}/description?code={code}&lang=EN")).splitlines():
        parts = [p for p in line.split("\t") if p]
        if len(parts) >= 2:
            out[parts[0].strip()] = parts[-1].strip()
    return out


def _fy_end_date(year, mm, dd):
    last = (dt.date(year + (mm == 12), mm % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, mm, min(dd, last))


def fi_accounts_check(fy_end, tase_dates, registered, today):
    """(period_end, registered_on, due) for each financial year to check. Each year takes the earliest
    unmatched registration after its year end, up to the next year end; checking starts at the
    year end before the first registration (a first year can run up to 18 months), or the year after
    incorporation if nothing was registered."""
    mm, dd = fy_end
    filed = sorted(tase_dates)
    if filed:
        start = max((y for y in range(registered.year, filed[0].year + 1) if _fy_end_date(y, mm, dd) < filed[0]),
                    default=filed[0].year)
    else:
        start = registered.year + 1
    rows, pool = [], list(filed)
    for year in range(start, today.year + 1):
        end = _fy_end_date(year, mm, dd)
        due = _add_months_end(end, FI_ACCOUNTS_MONTHS)
        got = next((d for d in pool if end < d <= _fy_end_date(year + 1, mm, dd)), None)
        if got:
            pool.remove(got)
        if got or due < today:
            rows.append((end, got, due))
    return rows


def fi_report(query, fy_end=None, fetcher=None, today=None):
    """Finnish company from PRH's open data (CC BY 4.0): the YTJ profile, the registered-notices
    timeline (deduplicated by record number, with entry codes described), the periods of digitally
    filed accounts, and flags for bankruptcy, restructuring or liquidation, removal from the trade
    register, and accounts registered late or not at all."""
    get = fetcher or (lambda u: fetch_bytes(u, None))
    today = today or dt.date.today()
    bid = query.strip()
    if not re.fullmatch(r"\d{7}-\d", bid):
        url = f"{PRH_YTJ}/companies?" + urllib.parse.urlencode({"name": query})
        q = query.strip().lower()
        starts = lambda c: not any(n.get("name", "").lower().startswith(q) for n in c.get("names", []))
        for c in sorted(json.loads(get(url)).get("companies", []), key=starts)[:20]:  # PRH's search is fuzzy
            yield {"type": "fi_candidate", "business_id": (c.get("businessId") or {}).get("value"),
                   "names": [n.get("name") for n in c.get("names", []) if not n.get("endDate")],
                   "form": _en((c.get("companyForms") or [{}])[0].get("descriptions")),
                   "registered": (c.get("businessId") or {}).get("registrationDate"),
                   "situations": [FI_SITUATIONS.get(s.get("type"), s.get("type")) for s in c.get("companySituations", [])]}
        yield {"type": "fi_note", "note": "run mr.py fi <business ID> with the right company's ID", "url": url}
        return
    url = f"{PRH_YTJ}/companies?businessId={bid}"
    found = json.loads(get(url)).get("companies") or []
    if not found:
        yield {"type": "fi_note", "note": f"no company with business ID {bid}", "url": url}
        return
    c = found[0]
    virre = f"https://virre.prh.fi/yritys/{bid}"
    names = c.get("names", [])
    trade = next((e for e in c.get("registeredEntries", []) if e.get("register") == "1" and not e.get("endDate")), {})
    address = next((a for a in c.get("addresses", []) if a.get("type") == 1), None) or (c.get("addresses") or [None])[0]
    registered = _date((c.get("businessId") or {}).get("registrationDate")) or today
    yield {"type": "fi_company", "business_id": bid,
           "name": next((n["name"] for n in names if n.get("type") == "1" and not n.get("endDate")), None),
           "other_names": [n["name"] for n in names if n.get("type") != "1" and not n.get("endDate")],
           "former_names": [f'{n["name"]} (until {n["endDate"]})' for n in names if n.get("endDate")],
           "form": _en((c.get("companyForms") or [{}])[0].get("descriptions")), "registered": registered.isoformat(),
           "trade_register": _en(trade.get("descriptions")), "status": FI_STATUS.get(str(c.get("status")), c.get("status")),
           "main_line": _en((c.get("mainBusinessLine") or {}).get("descriptions")),
           "website": (c.get("website") or {}).get("url"),
           "address": address and " ".join(filter(None, [address.get("street"), address.get("buildingNumber"),
                                                          address.get("postCode"), _fi_city(address.get("postOffices"))])),
           "last_modified": c.get("lastModified"), "url": url, "page": virre}
    flags = 0
    situations = [s for s in c.get("companySituations", []) if not s.get("endDate")]
    for s in situations:
        flags += 1
        yield {"type": "fi_flag", "flag": FI_SITUATIONS.get(s.get("type"), s.get("type")), "severity": "major",
               "since": s.get("registrationDate"), "url": url}
    if (trade and trade.get("type") in ("2", "4")) or str(c.get("status")) == "5":
        flags += 1
        yield {"type": "fi_flag", "flag": "not on the trade register", "severity": "major",
               "trade_register": _en(trade.get("descriptions")), "since": trade.get("registrationDate"), "url": url}

    notices_url = f"{PRH_NOTICES}/{bid}"
    records = {}
    try:
        for n in json.loads(get(notices_url)).get("publicNotices", []):
            r = records.setdefault(n.get("recordNumber"), {"date": n.get("registrationDate"),
                                                          "kind": n.get("typeOfRegistration"), "codes": []})
            r["codes"] += [e for e in n.get("entryCodes", []) if e not in r["codes"]]
    except (FetchError, ValueError) as e:
        yield {"type": "fi_unavailable", "source": "registered notices", "error": str(e), "url": notices_url}
    try:
        codes, kinds = fi_code_list(get, "EC"), fi_code_list(get, "NRT")
    except (FetchError, ValueError):
        codes, kinds = {}, {}
    topics_seen = {}
    for number, r in sorted(records.items(), key=lambda kv: (kv[1]["date"] or "", kv[0] or "")):
        topics = [t for t, cs in FI_TOPICS.items() if cs & set(r["codes"])]
        for t in topics:
            topics_seen.setdefault(t, []).append(r["date"])
        yield {"type": "fi_notice", "date": r["date"], "record": number, "kind": kinds.get(r["kind"], r["kind"]),
               "entries": [f"{e} ({codes[e].lower()})" if e in codes else e for e in r["codes"]],
               **({"topics": topics} if topics else {}), "url": notices_url}
        if FI_INSOLVENCY_CODES & set(r["codes"]) and not situations:
            flags += 1
            yield {"type": "fi_flag", "flag": "insolvency entry in the notices", "severity": "major",
                   "date": r["date"], "record": number, "url": notices_url}

    xbrl_url = f"{PRH_XBRL}/financials?businessId={bid}"
    periods = []
    try:
        periods = sorted(f["financialDate"] for f in json.loads(get(xbrl_url)).get("financials", []) if f.get("financialDate"))
    except (FetchError, ValueError, KeyError) as e:
        yield {"type": "fi_unavailable", "source": "digital financial statements", "error": str(e), "url": xbrl_url}
    for p in periods:
        yield {"type": "fi_accounts_digital", "period_end": p,
               "url": f"{PRH_XBRL}/financial?businessId={bid}&financialDate={p}",
               "note": "an XBRL statement coded in the Finnish taxonomy; the figures are not parsed"}

    fy_source = "--fy-end"
    if fy_end is None and periods:
        ends = [p[5:] for p in periods]
        fy_end, fy_source = max(set(ends), key=ends.count), "the periods of the digitally filed accounts"
    tase = [d for d in (_date(x) for x in topics_seen.get("accounts", [])) if d]
    checked = 0
    if fy_end:
        mm, dd = (int(x) for x in fy_end.split("-"))
        rule = (f"accounts are due {FI_ACCOUNTS_MONTHS} months after the year end: adopted within 6 months "
                "(OYL 5:3) and filed within 2 months of adoption (KPL 3:9)")
        for end, got, due in fi_accounts_check((mm, dd), tase, registered, today):
            checked += 1
            recent = end >= today - dt.timedelta(days=365 * FI_RECENT_YEARS)
            if got is None:
                flags += 1
                yield {"type": "fi_flag", "flag": "accounts not registered", "severity": "major" if recent else "minor",
                       "period_end": end.isoformat(), "due": due.isoformat(), "rule": rule, "url": notices_url}
            elif got > due:
                flags += 1
                yield {"type": "fi_flag", "flag": "late accounts", "severity": "major" if recent else "minor",
                       "period_end": end.isoformat(), "registered": got.isoformat(), "due": due.isoformat(),
                       "days_late": (got - due).days, "rule": rule,
                       "note": "the date PRH registered the accounts; they may have arrived a few days earlier",
                       "url": notices_url}
    yield {"type": "fi_summary", "business_id": bid, "notices": len(records),
           "capital_events": topics_seen.get("capital", []), "board_changes": topics_seen.get("board", []),
           "auditor_changes": topics_seen.get("auditor", []), "accounts_registered": topics_seen.get("accounts", []),
           "financial_year_end": fy_end and f"{fy_end} (from {fy_source})", "years_checked": checked, "flags": flags,
           "note": ("the open data has no officer names, share capital, notice text, or shareholders; the notices "
                    "give dates and entry codes only. " + ("" if fy_end else "Pass --fy-end MM-DD (Virre shows the "
                    "financial period) to check the accounts deadlines. ") + "Source: PRH open data, CC BY 4.0"),
           "page": virre}


# --------------------------------------------------------------- Denmark ----

DK_FILINGS = "http://distribution.virk.dk/offentliggoerelser/_search"
DK_RECENT_YEARS = 3
DK_LATE_GRACE_DAYS = 7  # publication can trail receipt by a few days; later than this is a major flag
DK_FIGURES = {  # field: element names in the Danish GAAP (fsa) and IFRS taxonomies, first found wins
    "revenue": ["fsa:Revenue", "ifrs-full:Revenue", "ifrs-full:RevenueFromContractsWithCustomers"],
    "gross_profit": ["fsa:GrossProfitLoss", "fsa:GrossResult", "ifrs-full:GrossProfit"],
    "operating_profit": ["fsa:ProfitLossFromOrdinaryOperatingActivities", "ifrs-full:ProfitLossFromOperatingActivities"],
    "profit_before_tax": ["fsa:ProfitLossFromOrdinaryActivitiesBeforeTax", "ifrs-full:ProfitLossBeforeTax"],
    "net_profit": ["fsa:ProfitLoss", "ifrs-full:ProfitLoss"],
    "equity": ["fsa:Equity", "ifrs-full:Equity"],
    "assets": ["fsa:Assets", "ifrs-full:Assets"],
    "cash": ["fsa:CashAndCashEquivalents", "ifrs-full:CashAndCashEquivalents"],
    "current_assets": ["fsa:CurrentAssets", "ifrs-full:CurrentAssets"],
    "current_liabilities": ["fsa:ShorttermLiabilitiesOtherThanProvisions", "ifrs-full:CurrentLiabilities"],
    "payables_to_group_short": ["fsa:ShorttermPayablesToGroupEnterprises"],
    "payables_to_group_long": ["fsa:LongtermPayablesToGroupEnterprises"],
    "receivables_from_group": ["fsa:ShorttermReceivablesFromGroupEnterprises"],
    "operating_cash_flow": ["fsa:CashFlowsFromUsedInOperatingActivities",
                            "ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "employees": ["fsa:AverageNumberOfEmployees"],
}
DK_INSTANT_FIELDS = {"equity", "assets", "cash", "current_assets", "current_liabilities", "payables_to_group_short",
                     "payables_to_group_long", "receivables_from_group"}
DK_HEADER = {"reporting_class": "fsa:ClassOfReportingEntity", "report_type": "gsd:InformationOnTypeOfSubmittedReport",
             "approved": "sob:DateOfApprovalOfAnnualReport", "auditor_assistance": "cmn:TypeOfAuditorAssistance",
             "modified_opinion": "arr:TypeOfModifiedOpinionOnAuditedFinancialStatements",
             "modified_opinion_basis": "arr:TypeOfBasisForModifiedOpinionOnAuditedFinancialStatements",
             "audit_firm": "cmn:NameOfAuditFirm"}
DK_NOTE_TOPICS = {  # topic: pattern on the element's local name
    "going_concern": r"GoingConcern",
    "events_after_year_end": r"AfterEndOfReportingPeriod|EventsAfterReportingPeriod",
    "parent_and_related_parties": r"RelatedPart|NameOfParent|UltimateParent|OmissionOfConsolidatedFinancialStatement",
    "subsidiaries": r"Subsidiar|^DisclosureOfInvestments$|InvestmentsInGroupEnterprises",
    "contingencies_and_security": r"ContingentLiabilit|Collateral|Mortgage",
    "audit_remarks": r"EmphasisOfMatter|SupplementaryInformationOnAudit|OtherMatter|MaterialUncertainty",
}
_DK_LAW_BREACH_RE = re.compile(r"selskabslov|companies act|kapitaltab|capital loss|half of the (?:share )?capital|"
                               r"overtr|breach|contraven|ansvar|liab", re.I)
_DK_OFFICER_FIELDS = {
    "cmn:NameAndSurnameOfMemberOfExecutiveBoard": ("executive_board", "name"),
    "cmn:TitleOfMemberOfExecutiveBoard": ("executive_board", "title"),
    "cmn:NameAndSurnameOfMemberOfSupervisoryBoard": ("supervisory_board", "name"),
    "cmn:TitleOfMemberOfSupervisoryBoard": ("supervisory_board", "title"),
    "cmn:NameAndSurnameOfAuditor": ("auditor", "name"),
}


class _IxParser(HTMLParser):
    """Inline XBRL facts with their text, nested facts included (a CVR number or a
    name split over several tags), as (kind, attributes, text) tuples."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open, self.facts, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag == "ix:exclude":
            self.skip += 1
        elif tag in ("ix:nonfraction", "ix:nonnumeric"):
            self.open.append([tag, dict(attrs), []])

    def handle_startendtag(self, tag, attrs):
        if tag in ("ix:nonfraction", "ix:nonnumeric"):
            self.facts.append((tag, dict(attrs), ""))

    def handle_endtag(self, tag):
        if tag == "ix:exclude":
            self.skip = max(0, self.skip - 1)
        elif tag in ("ix:nonfraction", "ix:nonnumeric") and self.open:
            kind, attrs, parts = self.open.pop()
            self.facts.append((kind, attrs, re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", "".join(parts))).strip()))

    def handle_data(self, data):
        if not self.skip:
            for f in self.open:
                f[2].append(data)


def _dk_number(text, fmt=None, scale=None, sign=None):
    s = (text or "").strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "–", "—"):
        return 0.0
    s = s.replace(".", "").replace(",", ".") if fmt and "comma" in fmt else s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    if scale:
        v *= 10 ** int(scale)
    return -v if sign == "-" else v


def dk_facts(doc):
    """(contexts, facts) from a Danish XBRL (.xml) or inline XBRL (.xhtml) report.
    contexts: {id: (start, end, dims)}, start None for an instant; dims the explicit
    members and typed dimension names. facts: (name, context id, text, number, unit)."""
    # element names get the taxonomy's usual prefix (fsa, cmn, ifrs-full...) whatever the file declares:
    # older Danish reports use e: for fsa and d: for cmn
    prefixes = {p: _dk_prefix(uri) for p, uri in re.findall(r"xmlns:([\w-]+)=\"([^\"]+)\"", doc[:20000])}
    canon = lambda qname: qname and (lambda p, _, local: f"{prefixes.get(p, p)}:{local}" if local else qname)(
        *qname.partition(":"))
    contexts, units, facts = {}, {}, []
    if re.search(r"<ix:(?:nonFraction|nonNumeric)\b", doc):
        for cid, body in _CONTEXT_RE.findall(doc):
            dims = tuple(canon(m) for m in re.findall(r"<xbrldi:explicitMember\b[^>]*>\s*([^<\s]+)", body)
                         + re.findall(r"<xbrldi:typedMember\b[^>]*dimension=\"([^\"]+)\"", body))
            instant = re.search(r"<xbrli:instant>\s*([^<\s]+)", body)
            start = re.search(r"<xbrli:startDate>\s*([^<\s]+)", body)
            end = re.search(r"<xbrli:endDate>\s*([^<\s]+)", body)
            if instant:
                contexts[cid] = (None, instant.group(1)[:10], dims)
            elif start and end:
                contexts[cid] = (start.group(1)[:10], end.group(1)[:10], dims)
        units = dict(re.findall(r"<xbrli:unit\b[^>]*id=\"([^\"]+)\"[^>]*>.*?<xbrli:measure>\s*([^<\s]+)", doc, re.S))
        p = _IxParser()
        p.feed(doc)
        for kind, a, text in p.facts:
            number = _dk_number(text, a.get("format"), a.get("scale"), a.get("sign")) if kind == "ix:nonfraction" else None
            facts.append((canon(a.get("name")), a.get("contextref"), text, number, units.get(a.get("unitref"))))
        return contexts, facts
    root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", doc))
    xi, di = "{http://www.xbrl.org/2003/instance}", "{http://xbrl.org/2006/xbrldi}"
    for c in root.iter(xi + "context"):
        dims = tuple([canon(m.text.strip()) for m in c.iter(di + "explicitMember") if m.text]
                     + [canon(m.get("dimension")) for m in c.iter(di + "typedMember")])
        instant, start, end = (c.findtext(f".//{xi}{t}") for t in ("instant", "startDate", "endDate"))
        if instant:
            contexts[c.get("id")] = (None, instant.strip()[:10], dims)
        elif start and end:
            contexts[c.get("id")] = (start.strip()[:10], end.strip()[:10], dims)
    for u in root.iter(xi + "unit"):
        units[u.get("id")] = (u.findtext(f".//{xi}measure") or "").strip()
    for el in root:
        cid = el.get("contextRef")
        if cid is None or not el.tag.startswith("{"):
            continue
        uri, local = el.tag[1:].split("}", 1)
        text = text_of("".join(el.itertext()))
        unit = el.get("unitRef")
        facts.append((f"{_dk_prefix(uri)}:{local}", cid, text, _dk_number(text) if unit else None, units.get(unit)))
    return contexts, facts


def _dk_prefix(uri):
    """The usual prefix for a taxonomy namespace: http://xbrl.dcca.dk/fsa -> fsa, an IFRS
    namespace ending in ifrs-full -> ifrs-full, otherwise its last path segment."""
    return re.split(r"[/#]", uri.rstrip("/"))[-1] or uri


def _dk_scope(dims, name):
    """'entity' for a Danish GAAP fact with no dimension, 'group' for the consolidated
    member, 'reported' for an IFRS fact with no dimension (the group's figures when the
    report is consolidated), None for any other breakdown."""
    if not dims:
        return "entity" if name.startswith("fsa:") else "reported"
    return "group" if all(d.endswith("ConsolidatedMember") for d in dims) else None


def dk_parse_report(doc, period_start, period_end):
    """(figures by scope, header facts, notes by topic, officers by role, currency) for the
    report's own period from one Danish annual report."""
    contexts, facts = dk_facts(doc)
    name_to_field = {n: f for f, names in DK_FIGURES.items() for n in names}
    figures, header, notes, officers, currency = {}, {}, {}, {}, None
    for name, cid, text, number, unit in facts:
        if not name:
            continue
        start, end, dims = contexts.get(cid, (None, None, ()))
        field = name_to_field.get(name)
        if field and number is not None:
            if end != period_end or (start is None) != (field in DK_INSTANT_FIELDS) or (start and start != period_start):
                continue
            scope = _dk_scope(dims, name)
            if scope:
                row = figures.setdefault(scope, {})
                rank = DK_FIGURES[field].index(name)
                if field not in row or rank < row[field][1]:
                    row[field] = (number, rank)
                if unit and unit.startswith("iso4217:"):
                    currency = currency or unit.split(":")[1]
            continue
        if number is not None or not text:
            continue
        for key, element in DK_HEADER.items():
            if name == element and key not in header:
                header[key] = text[:200]
        if name in _DK_OFFICER_FIELDS:
            role, part = _DK_OFFICER_FIELDS[name]
            officers.setdefault(role, {}).setdefault(cid, {})[part] = text
        local = name.split(":")[-1]
        for topic, pattern in DK_NOTE_TOPICS.items():
            if re.search(pattern, local) and len(text) > 3:
                picked = notes.setdefault(topic, [])
                if len(picked) < 4 and not any(text[:200] == t[:200] for t in picked):
                    picked.append(text[:1200])
    people = {role: [p for p in by_ctx.values() if p.get("name")] for role, by_ctx in officers.items()}
    return ({s: {f: v for f, (v, _) in row.items()} for s, row in figures.items()},
            header, notes, {r: p for r, p in people.items() if p}, currency)


def dk_deadline(period_end, reporting_class=None):
    """(due date, rule) under ÅRL § 138: received within 6 months of the year end, 4 for
    class D. Years ending before 2020-12-31 had 5 months, with COVID-19 extensions for
    years ending in 2019 and 2020. A deadline on a weekend moves to the Monday."""
    if reporting_class and re.search(r"\bD\b", reporting_class):
        months, rule = 4, "ÅRL § 138: class D, received within 4 months of the year end"
    elif period_end >= dt.date(2020, 12, 31):
        months, rule = 6, "ÅRL § 138: received within 6 months of the year end (4 for class D)"
    else:
        months, rule = 5, "5 months after the year end, the rule before the current 6"
    if dt.date(2019, 12, 31) <= period_end <= dt.date(2020, 12, 31):
        if period_end <= dt.date(2020, 6, 30):
            months += 3  # 2019 reports were due 31 August 2020 instead of 31 May
        rule += ("; COVID-19: 2019 reports had 3 months more, and 2020 reports were due 30 June 2021 or "
                 "3 months later on request, so check this year by hand")
    month_end = period_end == _add_months_end(period_end, 0)
    due = _add_months_end(period_end, months) if month_end else _add_months(period_end, months)
    while due.weekday() >= 5:
        due += dt.timedelta(days=1)
    return due, rule


def dk_candidates(name, fetcher=None):
    """Danish companies with an LEI matching the name, from GLEIF: the filings index has no names."""
    found = 0
    for r in gleif_search(name, 50, fetcher):
        if r["type"] == "gleif_candidate" and (r.get("jurisdiction") or "").startswith("DK"):
            found += 1
            yield {"type": "dk_candidate", "cvr": r.get("registered_as"), "name": r.get("legal_name"),
                   "lei": r.get("lei"), "status": r.get("entity_status"), "url": r.get("url")}
    yield {"type": "dk_note", "note": ("run mr.py dk <CVR> with the right company's number" if found else
                                       "no Danish LEI record matches; find the CVR number on datacvr.virk.dk in a browser"),
           "search": "https://datacvr.virk.dk"}


def _dk_doc(docs, kind, mime):
    return next((d.get("dokumentUrl") for d in docs if d.get("dokumentType") == kind
                 and (d.get("dokumentMimeType") or "").endswith(mime)), None)


def dk_report(query, years=3, fetcher=None, today=None):
    """Danish company from the Business Authority's open filings index and the XBRL of
    its annual reports: each filing with its publication date against the ÅRL § 138
    deadline, and figures, officers and auditor, and notes from the latest `years`
    reports, with flags for late or missing accounts, negative equity, going-concern
    notes, and auditor remarks."""
    get = fetcher or (lambda u: fetch_bytes(u, None))
    today = today or dt.date.today()
    cvr = re.sub(r"\D", "", query) if re.fullmatch(r"\s*(?:DK)?[\d\s]{8,14}", query, re.I) else ""
    if len(cvr) != 8:
        yield from dk_candidates(query, fetcher)
        return
    url = f"{DK_FILINGS}?q=cvrNummer:{cvr}&size=200"
    page = f"https://datacvr.virk.dk/enhed/virksomhed/{cvr}"
    by_end = {}
    for h in json.loads(get(url)).get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        period = (s.get("regnskab") or {}).get("regnskabsperiode") or {}
        if s.get("offentliggoerelsestype") == "regnskab" and period.get("slutDato"):
            by_end.setdefault(period["slutDato"], []).append({
                "start": period.get("startDato"), "published": (s.get("offentliggoerelsesTidspunkt") or "")[:10] or None,
                "approved": ((s.get("regnskab") or {}).get("godkendelse") or {}).get("godkendelsesdato"),
                "correction": bool(s.get("omgoerelse")), "docs": s.get("dokumenter") or []})
    if not by_end:
        yield {"type": "dk_note", "note": f"no annual reports published for CVR {cvr} (a new company, one exempt "
                                          "from filing, or a wrong number)", "url": url, "page": page}
        return
    ends = sorted(by_end)
    recent_cut = today - dt.timedelta(days=365 * DK_RECENT_YEARS)
    flags, parsed, reporting_class = 0, [], None
    parse_ends = set(ends[-years:]) if years > 0 else set()
    for end in ends:
        group = sorted(by_end[end], key=lambda f: f["published"] or "")
        first, docs = group[0], [d for f in group for d in f["docs"]]
        header = {}
        if end in parse_ends:
            sources = [u for u in [_dk_doc(docs, "AARSRAPPORT", "/xml")] if u]
            ixbrl = _dk_doc(docs, "AARSRAPPORT", "xhtml+xml")
            if ixbrl and (not sources or any(d.get("dokumentType") == "AARSRAPPORT_ESEF" for d in docs)):
                sources.append(ixbrl)  # the only machine-readable copy, or the IFRS (ESEF) group report
            p = None
            for src in sources:
                try:
                    fig, head, notes, people, currency = dk_parse_report(decode_body(get(src)), first["start"], end)
                except (FetchError, ValueError, ET.ParseError) as e:
                    yield {"type": "dk_unavailable", "source": "annual report XBRL", "period_end": end,
                           "error": str(e), "url": src}
                    continue
                if p is None:
                    p = {"end": end, "figures": {}, "header": head, "notes": {src: notes}, "people": people,
                         "currency": currency, "url": src}
                    parsed.append(p)
                else:  # a second document of the same filing adds figures and note topics, not officers
                    p["currency"] = p["currency"] or currency
                    extra = {t: v for t, v in notes.items() if not any(t in n for n in p["notes"].values())}
                    if extra:
                        p["notes"][src] = extra
                for scope, row in fig.items():
                    have = p["figures"].setdefault(scope, {"url": src})
                    for k, v in row.items():
                        have.setdefault(k, v)
            if p:
                header = p["header"]
                # a Danish cover file marks the report as consolidated while the IFRS file tags the group's
                # figures with no dimension: one group record
                fig = p["figures"]
                if "reported" in fig and "group" in fig:
                    fig["group"] = {**fig["group"], **fig.pop("reported")}
        reporting_class = header.get("reporting_class") or reporting_class
        due, rule = dk_deadline(_date(end), header.get("reporting_class"))
        record = {"type": "dk_accounts_filed", "period_start": first["start"], "period_end": end,
                  "approved": first["approved"], "published": first["published"], "due": due.isoformat(),
                  "documents": sorted({d.get("dokumentType") for d in docs if d.get("dokumentType")}),
                  "report": _dk_doc(docs, "AARSRAPPORT", "/pdf") or _dk_doc(docs, "AARSRAPPORT", "xhtml+xml"),
                  "xbrl": _dk_doc(docs, "AARSRAPPORT", "/xml") or _dk_doc(docs, "AARSRAPPORT", "xhtml+xml"),
                  "url": url}
        if len(group) > 1 or first["correction"]:
            record["later_versions"] = [{"published": f["published"], "correction": f["correction"]} for f in group[1:]]
        parent_doc = _dk_doc(docs, "KONCERNREGNSKAB_FOR_OVERLIGGENDE_MODER", "")
        if parent_doc:  # a parent consolidates the company and files its group accounts here (ÅRL § 112)
            record["parent_group_accounts"] = parent_doc
        yield record
        published = _date(first["published"])
        if published and published > due:
            recent = _date(end) >= recent_cut
            flags += 1
            yield {"type": "dk_flag", "flag": "late accounts",
                   "severity": "major" if recent and (published - due).days > DK_LATE_GRACE_DAYS else "minor",
                   "period_end": end, "published": first["published"], "due": due.isoformat(),
                   "days_late": (published - due).days, "recent": recent, "rule": rule,
                   "note": "the publication date; the Business Authority may have received the report a few days earlier",
                   "url": url}
    for prev, nxt in zip(ends, ends[1:]):
        start = _date(by_end[nxt][0]["start"])
        if start and start > _date(prev) + dt.timedelta(days=1):
            flags += 1
            yield {"type": "dk_flag", "flag": "gap between filed periods", "severity": "minor", "after": prev,
                   "next_start": start.isoformat(), "url": url}
    next_end = _add_months_end(_date(ends[-1]), 12) if _date(ends[-1]) == _add_months_end(_date(ends[-1]), 0) \
        else _add_months(_date(ends[-1]), 12)
    due, rule = dk_deadline(next_end, reporting_class)
    if due < today:
        flags += 1
        yield {"type": "dk_flag", "flag": "accounts not published", "severity": "major",
               "period_end": next_end.isoformat(), "due": due.isoformat(), "rule": rule,
               "note": "assumes a 12-month year after the last one filed; check the financial year and status on datacvr",
               "url": url}

    for p in parsed:
        for scope, fig in sorted(p["figures"].items()):
            fig = dict(fig)
            src = fig.pop("url")
            yield {"type": "dk_accounts_year", "period_end": p["end"], "scope": scope, "currency": p["currency"],
                   **fig, "url": src}
        if p["header"]:
            yield {"type": "dk_report_facts", "period_end": p["end"], **p["header"], "url": p["url"]}
        if p["people"]:
            yield {"type": "dk_officers", "period_end": p["end"], **p["people"],
                   "note": "as named in the annual report; current officers are on datacvr", "url": p["url"]}
        for src, notes in p["notes"].items():
            if notes:
                yield {"type": "dk_notes", "period_end": p["end"], **notes, "url": src}
    latest = max((p["end"] for p in parsed), default=None)
    for p in parsed:
        recent = _date(p["end"]) >= recent_cut
        if p["end"] == latest:
            for scope, fig in sorted(p["figures"].items()):
                if (fig.get("equity") or 0) < 0:
                    flags += 1
                    yield {"type": "dk_flag", "flag": "negative equity", "severity": "major", "period_end": latest,
                           "scope": scope, "equity": fig["equity"], "currency": p["currency"], "url": fig["url"]}
            for src, notes in p["notes"].items():
                gc = [t for t in notes.get("going_concern", []) if len(t) > 40]
                if gc:
                    flags += 1
                    yield {"type": "dk_flag", "flag": "going-concern note", "severity": "review", "period_end": latest,
                           "quote": gc[0][:300], "url": src,
                           "note": "read the note: a material uncertainty, or reliance on a parent's support, is a red flag"}
        opinion = (p["header"].get("modified_opinion") or "").strip()
        if re.search(r"qualif|adverse|disclaim|forbehold|afkræft|manglende", opinion, re.I):  # often just a heading
            flags += 1
            yield {"type": "dk_flag", "flag": "modified audit opinion", "severity": "major" if recent else "minor",
                   "period_end": p["end"], "opinion": opinion, "basis": p["header"].get("modified_opinion_basis"),
                   "url": p["url"]}
        for src, notes in p["notes"].items():
            for t in notes.get("audit_remarks", []):
                if len(t) > 40 and _DK_LAW_BREACH_RE.search(t):
                    flags += 1
                    yield {"type": "dk_flag", "flag": "auditor remark", "severity": "major" if recent else "minor",
                           "period_end": p["end"], "quote": t[:300], "url": src}
    yield {"type": "dk_summary", "cvr": cvr, "filings": sum(len(v) for v in by_end.values()), "first_period_end": ends[0],
           "last_period_end": ends[-1], "years_parsed": sorted({p["end"] for p in parsed}),
           "reporting_class": reporting_class, "flags": flags,
           "note": ("the filings index and the XBRL give the accounts, officers and auditor at each year end, and the "
                    "notes; current status, insolvency, officer changes, owners, and capital increases are on datacvr "
                    "(a browser tool)"),
           "page": page}


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
    totals = {"confirmed": 0, "not_found": 0, "unreachable": 0, "too_large": 0, "no_text_layer": 0, "no_quote": 0,
              "no_url": 0}

    def page_text(url):
        if url not in pages:
            try:
                body = fetcher(url)
                if body.lstrip()[:5] == "%PDF-":  # a PDF has no searchable text here (often a scan)
                    pages[url] = ("pdf", None)
                else:
                    pages[url] = ("ok", searchable_text(body).lower())
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
                elif errors and all("larger than" in e for e in errors):
                    record.update(result="too_large", errors=errors,
                                  note="the cited file is over the size limit (bulk open data, such as Luxembourg's "
                                       "Centrale des Bilans files); check the quote against the run folder's extract "
                                       "with mr.py quote-check <extract file> \"<quote>\"")
                    totals["too_large"] += 1
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

    s = sub.add_parser("jobs", help="open roles from the company's job board, optionally with a monthly trend")
    s.add_argument("target", help="the careers page URL, a job-board URL, or provider:token (greenhouse:acme)")
    s.add_argument("--history", action="store_true", help="also count roles in monthly archived copies (slow)")

    s = sub.add_parser("uk-accounts", help="UK Companies House: multi-year figures from iXBRL accounts")
    s.add_argument("company_number")
    s.add_argument("--sets", type=int, default=3, help="accounts filings to read (each covers two years)")

    s = sub.add_parser("fr", help="France: register profile, officers, and BODACC notices with missing-accounts flags")
    s.add_argument("siren_or_name", help="a 9-digit SIREN, or a name to list candidates")

    s = sub.add_parser("lu", help="Luxembourg: filed accounts from the Centrale des Bilans open data, with late-filing flags")
    s.add_argument("rcs", help="the RCS number, such as B165616")
    s.add_argument("--quarters", type=int, default=12, help="newest quarterly deposit files to search (each 70-820 MB)")
    s.add_argument("--save", metavar="FILE", help="write the company's matching records to this file, for quote-check")

    s = sub.add_parser("ie", help="Ireland: CRO open data profile and annual-return filings with late-filing flags")
    s.add_argument("cro_or_name", help="a CRO company number, or a name to list candidates")

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
            if a.registered_as:
                results = gleif_search(None, a.limit, registered_as=a.registered_as.strip())
            elif not a.name_or_lei:
                p.error("gleif needs a name, an LEI, or --registered-as")
            else:
                target = a.name_or_lei.strip().upper()
                results = gleif_report(target, a.max_children) if LEI_RE.match(target) else gleif_search(a.name_or_lei, a.limit)
            for r in results:
                emit(r)
        elif a.cmd == "ch-search":
            for r in ch_search(a.name, CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY")), a.limit):
                emit(r)
        elif a.cmd in ("ch", "uk-accounts"):
            ch = CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY"))
            results = ch_report(a.company_number, ch, a.max_filings, list_filings=a.list_filings) if a.cmd == "ch" \
                else uk_accounts(a.company_number, ch, a.sets)
            for r in results:
                emit(r)
        elif a.cmd == "ch-officers":
            ch = CompaniesHouse(os.environ.get("COMPANIES_HOUSE_API_KEY"))
            for r in ch_officers(a.company_number, ch, a.max_appointments):
                emit(r)
        elif a.cmd == "warn":
            for r in warn_report(a.name):
                emit(r)
        elif a.cmd == "us-states":
            for r in us_states_report(a.names):
                emit(r)
        elif a.cmd == "jobs":
            for r in jobs_report(a.target, a.history):
                emit(r)
        elif a.cmd == "lu":
            for r in lu_report(a.rcs, a.quarters, save=a.save):
                emit(r)
        elif a.cmd == "ie":
            for r in ie_report(a.cro_or_name):
                emit(r)
        elif a.cmd == "no":
            for r in no_report(a.orgnr_or_name):
                emit(r)
        elif a.cmd == "dk":
            for r in dk_report(a.cvr_or_name, a.years):
                emit(r)
        elif a.cmd == "fi":
            for r in fi_report(a.business_id_or_name, a.fy_end):
                emit(r)
        elif a.cmd == "fr":
            for r in fr_report(a.siren_or_name):
                emit(r)
        elif a.cmd == "pdf-text":
            if a.pdf.startswith(("http://", "https://")):
                pdf = fetch_bytes(a.pdf, None)
            else:
                with open(a.pdf, "rb") as f:
                    pdf = f.read()
            try:
                for r in pdf_text_records(pdf, a.pdf):
                    emit(r)
            except ValueError as e:
                emit({"type": "error", "source": a.pdf, "error": str(e)})
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
