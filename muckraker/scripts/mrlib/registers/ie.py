"""Ireland: CRO open data profile and annual-return filings."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .. import common, uk


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
    return uk._date(s[:10]) if s else None


def ie_report(query, fetcher=None, today=None):
    """Irish company from the CRO's open data: profile, each annual return's
    accounts filing with the days it took, and flags for late or overdue returns."""
    get = fetcher or (lambda u: common.fetch(u, None))
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
