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


def fetch(url, user_agent, retries=2):
    """Return the decoded body of `url`."""
    global _last_sec_request
    is_sec = urllib.parse.urlparse(url).hostname.endswith("sec.gov")
    if is_sec and not user_agent:
        raise FetchError("sec.gov needs --user-agent or MUCKRAKER_SEC_UA")
    headers = {"User-Agent": user_agent or "muckraker", "Accept-Encoding": "gzip"}
    for attempt in range(retries + 1):
        if is_sec:
            wait = SEC_MIN_INTERVAL - (time.monotonic() - _last_sec_request)
            if wait > 0:
                time.sleep(wait)
            _last_sec_request = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                body = read_body(r, r.headers.get("Content-Encoding") == "gzip")
                return body.decode("utf-8", errors="replace")
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
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise FetchError(f"not a CIK: {cik}")
    return digits.zfill(10)


def text_of(fragment):
    """Visible text of an HTML/XML fragment, whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


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
        notes.append("negative fair value: usually an unfunded commitment; no mark computed")
    elif _REVOLVER_RE.search(text):
        notes.append(REVOLVER_NOTE)
    if _JV_RE.search(text):
        notes.append(JV_NOTE)
    return notes


_CONTEXT_RE = re.compile(r"<xbrli:context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.S)
_TYPED_RE = re.compile(r"<xbrldi:typedMember\b[^>]*dimension=\"us-gaap:InvestmentIdentifierAxis\"[^>]*>(.*?)</xbrldi:typedMember>", re.S)
_FACT_RE = re.compile(r"<ix:(nonFraction|nonNumeric)\b([^>]*)>(.*?)</ix:\1>", re.S)


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
    rows, durations = {}, {}
    for kind, attrs, raw in _FACT_RE.findall(doc):
        cid = _attr(attrs, "contextRef")
        if cid not in contexts:
            continue
        field = HOLDING_CONCEPTS.get(_attr(attrs, "name"))
        if not field:
            continue
        ident, date, is_instant = contexts[cid]
        value = text_of(raw) if field == "maturity" else _number(attrs, raw)
        if value is None:
            continue
        if field in ("interest_rate", "spread", "pik_rate") and _attr(attrs, "scale") == "-2":
            value = round(value * 100, 4)  # back to percent as printed
        if is_instant:
            rows.setdefault((ident, date), {})[field] = value
        else:
            durations.setdefault(ident, {})[field] = value
    out = []
    for (ident, date), fields in rows.items():
        for k, v in durations.get(ident, {}).items():
            fields.setdefault(k, v)
        record = {"identifier": ident, "as_of": date, **fields}
        if fields.get("principal", 0) > 0 and fields.get("fair_value", -1) >= 0:
            record["mark"] = round(100 * fields["fair_value"] / fields["principal"], 1)
        notes = holding_notes(ident, fields.get("fair_value"))
        if notes:
            record["notes"] = notes
        out.append(record)
    return sorted(out, key=lambda r: (r["identifier"], r["as_of"] or ""))


_HOLDING_WORDS = re.compile(r"\b(lien|loan|revolv\w*|term|notes?|bonds?|units|shares|membership|preferred|warrants?|sofr|libor)\b", re.I)


def parse_table_rows(doc, aliases):
    """Fallback for filings without row-level XBRL: table rows that name an alias
    and read like a holding (a loan, notes, units, shares...)."""
    wanted = [a.lower() for a in aliases]

    def row_text(row):
        cells = [text_of(c) for c in re.findall(r"<t[dh]\b.*?</t[dh]>", row, re.S | re.I)]
        return " | ".join(c for c in cells if c and c not in ("$", "%"))

    out = []
    for table in re.findall(r"<table\b.*?</table>", doc, re.S | re.I):
        header = None
        for row in re.findall(r"<tr\b.*?</tr>", table, re.S | re.I):
            line = row_text(row)
            if not line:
                continue
            if header is None:  # first non-empty row: usually the column headings
                header = line
            if (any(a in line.lower() for a in wanted) and _HOLDING_WORDS.search(line)
                    and re.search(r"\d[\d,.]{3,}", line)):  # a holding row carries an amount
                record = {"row": line}
                if header != line:
                    record["header"] = header
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
    out = []
    for sec in root.iter("invstOrSec"):
        name, title = find_text(sec, "name") or "", find_text(sec, "title") or ""
        if not any(a in name.lower() or a in title.lower() for a in wanted):
            continue
        record = {"fund": fund, "as_of": period, "name": name, "title": title}
        for tag in ("balance", "units", "curCd", "valUSD", "pctVal", "assetCat", "fairValLevel", "cusip", "lei"):
            v = find_text(sec, tag)
            if v is not None:
                record[tag] = float(v) if tag in ("balance", "valUSD", "pctVal") else v
        for tag in ("maturityDt", "couponKind", "annualizedRt", "isDefault", "areIntrstPmntsInArrs", "isPaidKind"):
            v = find_text(sec, f"debtSec/{tag}")
            if v is not None:
                record[tag] = v
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
                notes.append({"type": "no_earlier_filing", "filer": any_doc["filer"],
                              "latest_filed": latest.isoformat(), "wanted_around": target.isoformat(),
                              "note": f"no filing within {TARGET_WINDOW_DAYS} days of this date"})
                continue
            picked |= batch(min(near, key=lambda d: abs((d - target).days)))
        chosen.extend(h for h in docs.values() if dt.date.fromisoformat(h["filed"]) in picked)
    return chosen, notes


def marks(aliases, user_agent, since, per_filer, max_filers, verbose=False):
    hits = []
    for alias in aliases:
        # separate searches, so a flood of fund filings cannot push lenders past the cap
        for forms in (["10-K", "10-Q"], ["NPORT-P"]):
            found, summary = edgar_search(alias, forms, since, None, user_agent, 300)
            hits += found
            if summary["truncated"] or verbose:
                emit(summary)
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
    for note in notes:
        emit(note)
    # an N-PORT filing's HTML exhibit repeats holdings its XML already gives in full
    has_xml = {h["accession"] for h in chosen if h["url"].lower().endswith(".xml")}
    chosen = [h for h in chosen if h["url"].lower().endswith(".xml") or h["accession"] not in has_xml
              or not h["form"].startswith("NPORT")]
    # a trust can attach the same schedule (one large HTML file) to every fund's
    # filing; read one copy per filer, file name, and month
    seen, unique = set(), []
    for h in chosen:
        key = (h["cik"], h["url"].rsplit("/", 1)[-1].lower(), h["filed"][:7])
        if h["url"].lower().endswith(".xml") or key not in seen:
            seen.add(key)
            unique.append(h)
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
        for row in rows:
            emit({**base, "type": kind, **row})


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


def quote_check(url, quote, user_agent, context_chars):
    doc = fetch(url, user_agent)
    page = text_of(doc).lower()
    if re.search(r"<[A-Za-z/][^>]*>", quote):
        # an XML quote (N-PORT elements with their tags): the elements quoted are
        # often not adjacent, so find each element's value in order, close together
        parts = [p.lower() for p in (text_of(x) for x in re.split(r"<[^>]+>", quote)) if p]
        pos = _find_in_order(page, parts, window=1500)
        record = {"type": "quote_check", "url": url, "quote": quote, "found": pos >= 0}
        if pos >= 0:
            record["context"] = page[max(0, pos - context_chars): pos + 1500]
        emit(record)
        return
    needle = re.sub(r"\s+", " ", quote.replace("|", " ")).strip().lower()
    tokens = [t for t in re.split(r"[\s|]+", needle) if t]
    pos = page.find(needle)
    if pos < 0 and tokens:  # table quotes: allow anything between the cells
        pattern = r"\W+".join(re.escape(t) for t in tokens)
        m = re.search(pattern, page)
        pos = m.start() if m else -1
    record = {"type": "quote_check", "url": url, "quote": quote, "found": pos >= 0}
    if pos >= 0:
        record["context"] = page[max(0, pos - context_chars): pos + len(needle) + context_chars]
    emit(record)


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
    s.add_argument("--verbose", action="store_true",
                   help="also print search summaries and filings with no matching rows")

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
            marks(a.aliases, a.user_agent, a.since, a.per_filer, a.max_filers, a.verbose)
        elif a.cmd == "quote-check":
            quote_check(a.url, a.quote, a.user_agent, a.context)
    except FetchError as e:
        emit({"type": "error", "error": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
