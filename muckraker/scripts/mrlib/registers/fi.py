"""Finland: PRH profile, registered notices and accounts periods."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .. import common, uk
from . import no


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
    for line in common.decode_body(get(f"{PRH_NOTICES}/description?code={code}&lang=EN")).splitlines():
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
        due = no._add_months_end(end, FI_ACCOUNTS_MONTHS)
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
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
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
    registered = uk._date((c.get("businessId") or {}).get("registrationDate")) or today
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
    except (common.FetchError, ValueError) as e:
        yield {"type": "fi_unavailable", "source": "registered notices", "error": str(e), "url": notices_url}
    try:
        codes, kinds = fi_code_list(get, "EC"), fi_code_list(get, "NRT")
    except (common.FetchError, ValueError):
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
    except (common.FetchError, ValueError, KeyError) as e:
        yield {"type": "fi_unavailable", "source": "digital financial statements", "error": str(e), "url": xbrl_url}
    for p in periods:
        yield {"type": "fi_accounts_digital", "period_end": p,
               "url": f"{PRH_XBRL}/financial?businessId={bid}&financialDate={p}",
               "note": "an XBRL statement coded in the Finnish taxonomy; the figures are not parsed"}

    fy_source = "--fy-end"
    if fy_end is None and periods:
        ends = [p[5:] for p in periods]
        fy_end, fy_source = max(set(ends), key=ends.count), "the periods of the digitally filed accounts"
    tase = [d for d in (uk._date(x) for x in topics_seen.get("accounts", [])) if d]
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
