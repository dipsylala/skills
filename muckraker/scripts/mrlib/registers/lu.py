"""Luxembourg: filed accounts from the Centrale des Bilans open data."""

import http.client
import datetime as dt
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .. import common, uk


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
    """Stream a quarterly file and return the <Declarer> blocks for one RCS number, or any of several, decoded."""
    needles = [f"<RcsNumber>{r}</RcsNumber>".encode() for r in ([rcs] if isinstance(rcs, str) else rcs)]
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
                if any(n in block for n in needles):
                    found.append(block[block.rfind(b"<Declarer>"):].decode("iso8859_15", errors="replace"))
            if len(buf) > 64 << 20:
                raise common.FetchError(f"no </Declarer> in 64 MB of {url}")
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
    for late filing and negative equity. `rcs` is one RCS number or a list of them:
    each quarterly file is read once for all of them."""
    import concurrent.futures
    get = fetcher or (lambda u: common.fetch(u, None))
    stream = streamer or cdb_stream_blocks
    today = today or dt.date.today()
    wanted = [re.sub(r"\s", "", r).upper() for r in ([rcs] if isinstance(rcs, str) else rcs)]
    files = cdb_quarters(get, quarters)
    hits, saved = {r: [] for r in wanted}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(stream, url, wanted[0] if len(wanted) == 1 else tuple(wanted)): (q, url)
                   for q, url, _ in files}
        for fut in concurrent.futures.as_completed(futures):
            q, url = futures[fut]
            try:
                blocks = fut.result()
            except (common.FetchError, OSError, http.client.HTTPException) as e:
                yield {"type": "lu_quarter_unreadable", "quarter": q, "error": str(e), "url": url}
                continue
            for b in blocks:
                m = re.search(r"<RcsNumber>([^<]+)</RcsNumber>", b)
                owner = m.group(1).strip().upper() if m and m.group(1).strip().upper() in hits else wanted[0]
                saved.append(f"<!-- {url} -->\n{b}")
                hits[owner] += [dict(d, quarter=q, url=url) for d in lu_declarations(b)]
    if save and saved:
        with open(save, "w", encoding="utf-8") as f:
            f.write("<CdbExtract>\n" + "\n".join(saved) + "\n</CdbExtract>\n")
    for r in wanted:
        records = list(_lu_company(r, hits[r], today))
        yield from records
        yield {"type": "lu_summary", "rcs": r, "years": len({d["end"] for d in hits[r]}),
               "flags": sum(x["type"] == "lu_flag" for x in records), "quarters_searched": [q for q, _, _ in files],
               "saved_extract": save if save and saved else None,
               "note": "a filing appears in the quarter it was deposited, so years filed before the oldest quarter "
                       "searched are missing; raise --quarters to look further back"}


def _lu_company(rcs, hits, today):
    """One company's lu_accounts_filed, lu_accounts_year and lu_flag records from its declarations."""
    years = {}
    for d in sorted(hits, key=lambda d: (d["end"] or "", d["deposited"] or "")):
        years.setdefault(d["end"], []).append(d)
    for end, decls in sorted(years.items()):
        end_date = uk._date(end)
        first = min((d["deposited"] for d in decls if d["deposited"]), default=None)
        due = uk._add_months(end_date, LU_DUE_MONTHS) if end_date else None
        late = (uk._date(first) - due).days if first and due else None
        yield {"type": "lu_accounts_filed", "rcs": rcs, "name": decls[-1]["name"], "year_end": end,
               "forms": sorted({d["form"] for d in decls if d["form"]}), "deposited": first,
               "due": due and due.isoformat(), "days_late": max(late, 0) if late is not None else None,
               "filings": len({d["doc"] for d in decls}), "url": decls[0]["url"]}
        if late and late > 0:
            yield {"type": "lu_flag", "rcs": rcs, "flag": "late accounts", "severity": "major", "year_end": end,
                   "deposited": first, "due": due.isoformat(), "days_late": late,
                   "recent": bool(end_date and (today - end_date).days <= 3 * 366),
                   "rule": "accounts are due within 7 months of the year end (approval within 6 months, filing "
                           "within 1 month after)", "url": decls[0]["url"]}
        figures, labels = {}, {}
        for d in decls:  # the latest filing for the year wins
            figures.update(d["figures"])
            labels.update(d["labels"])
        yield {"type": "lu_accounts_year", "rcs": rcs, "year_end": end, "currency": decls[-1]["currency"], **figures,
               "quotes": labels, "url": decls[-1]["url"]}
    latest = max(years) if years else None
    if latest:
        equity = next((d["figures"].get("equity") for d in reversed(years[latest]) if "equity" in d["figures"]), None)
        if equity is not None and equity < 0:
            yield {"type": "lu_flag", "rcs": rcs, "flag": "negative equity", "severity": "major", "year_end": latest,
                   "equity": equity, "quote": next(d["labels"]["equity"] for d in reversed(years[latest]) if "equity" in d["labels"]),
                   "rule": "equity below zero at the latest year end; when losses exceed half the capital, "
                           "Luxembourg law requires the shareholders to decide on dissolution (art. 480-2 / 1100-2)",
                   "url": years[latest][-1]["url"]}
