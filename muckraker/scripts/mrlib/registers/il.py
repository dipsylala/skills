"""Israel: Corporations Authority profile from the Public Knowledge Workshop's daily copy."""

import datetime as dt
import json
import re
from .. import common


# --------------------------------------------------------------- Israel ----

# The Public Knowledge Workshop's daily copy of the Corporations Authority's company file; its
# robots.txt bars /api/ (where name search lives) but allows /get/. data.gov.il, the source, refuses scripts.
IL_COPY = "https://next.obudget.org/get/org/company/"
IL_SEARCH = "https://ica.justice.gov.il/GenericCorporarionInfo/SearchCorporation?unit=8"
IL_STATUS = {"פעילה": "active", "מחוקה": "struck off", "מחוסלת": "liquidated", "מחוסלת מרצון": "liquidated voluntarily",
             "בפירוק": "in liquidation", "בפירוק מרצון": "in voluntary liquidation", "לא פעילה": "inactive"}


def il_report(query, fetcher=None, today=None):
    """Israeli company from a daily copy of the Corporations Authority's register: profile and
    flags for a violating company (מפרה: unpaid annual fees or unfiled annual reports), a status
    other than active, and a lagging last annual report."""
    get = fetcher or (lambda u: common.fetch(u, None))
    today = today or dt.date.today()
    number = re.sub(r"[\s-]", "", query)
    if not re.fullmatch(r"\d{9}", number):
        yield {"type": "il_note", "url": IL_SEARCH,
               "note": "mr.py il takes a 9-digit company number. Find it in the Corporations Authority's free search "
                       "in a browser (do not script it; search the English name if the Hebrew one finds nothing)"}
        return
    url = IL_COPY + number
    try:
        record = json.loads(get(url))
    except common.FetchError as e:
        if "HTTP 404" not in str(e):
            raise
        yield {"type": "il_note", "url": IL_SEARCH,
               "note": f"the register copy has no company {number}; check the number in the Corporations Authority's search"}
        return
    v = record.get("value") or {}
    d = v.get("details") or {}
    status, sub_status = (d.get("status") or "").strip(), (d.get("sub_status") or "").strip() or None
    copied = (v.get("__last_modified_at") or "")[:10] or None
    yield {"type": "il_company", "company_number": number, "name": v.get("name"), "name_en": v.get("name_en"),
           "company_type": d.get("type"), "limit": d.get("limit"), "status": status,
           "status_en": IL_STATUS.get(status), "sub_status": sub_status, "registered": d.get("registration_date"),
           "violating": bool(d.get("is_mafera")), "last_annual_report_year": d.get("last_report_year"),
           "address": ", ".join(d.get("address_lines") or []) or None, "objects": d.get("goal"),
           "government_contracts": v.get("received_amount_contracts_alltime"),
           "government_supports": v.get("received_amount_supports_alltime"),
           "copy_date": copied, "url": url, "register_url": IL_SEARCH}
    flags = []
    if d.get("is_mafera"):
        flags.append({"flag": "violating company", "severity": "major",
                      "rule": "the Corporations Authority marks a company מפרה (violating) when it has not paid its "
                              "annual fee or filed its annual reports (Companies Law, s. 362A)"})
    if status and status != "פעילה":
        flags.append({"flag": "not active", "severity": "minor" if "מרצון" in status else "major", "status": status,
                      "status_en": IL_STATUS.get(status),
                      "rule": "a voluntary (solvent) liquidation is minor; struck off or court liquidation is major"})
    if sub_status:
        flags.append({"flag": "sub-status", "severity": "major" if "מחיק" in sub_status else "minor",
                      "sub_status": sub_status, "rule": "a sub-status mentioning מחיקה is a warning before strike-off"})
    last = d.get("last_report_year")
    if status == "פעילה" and isinstance(last, int) and last < today.year - 1:
        flags.append({"flag": "annual report lagging", "severity": "minor", "last_annual_report_year": last,
                      "rule": "a company files an annual report every year; one more than a year behind is overdue"})
    for f in flags:
        yield {"type": "il_flag", **f, "url": url}
    yield {"type": "il_summary", "company_number": number, "flags": len(flags), "copy_date": copied,
           "note": "a copy of the Corporations Authority's register made by the Public Knowledge Workshop (obudget.org), "
                   "refreshed daily: name it as a copy with its date and confirm a red flag in the Authority's search "
                   "(register_url). Officers, shareholders, allotments, charges and annual reports are in the paid "
                   "company file; private companies publish no accounts"}
