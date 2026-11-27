"""US: WARN layoff notices, state registers' open data, federal spending (USAspending)."""

import http.client
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from . import common, gleif


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
    words = gleif.distinctive_words(name) or set(re.findall(r"\w+", name.lower()))
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
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    covered, found = [], 0
    try:
        for r in warn_ca(name, get(CA_WARN)):
            found += 1
            yield r
        covered.append("CA (current fiscal year from 1 July; earlier years are PDFs)")
    except (common.FetchError, ValueError, KeyError) as e:
        yield {"type": "warn_unavailable", "state": "CA", "error": str(e), "url": CA_WARN}
    word = max(gleif.distinctive_words(name) or {name}, key=len).upper().replace("'", "''")
    tx_url = TX_WARN + "?" + urllib.parse.urlencode({"$where": f"upper(job_site_name) like '%{word}%'", "$limit": 200})
    try:
        for r in json.loads(get(tx_url)):
            if _name_match(name, r.get("job_site_name")):
                found += 1
                yield {"type": "warn_notice", "state": "TX", "company": r.get("job_site_name"),
                       "notice_date": (r.get("notice_date") or "")[:10], "effective_date": (r.get("layoff_date") or "")[:10],
                       "employees": _int_or_none(r.get("total_layoff_number")), "site": r.get("city_name"), "url": tx_url}
        covered.append("TX (open data, updated every few months)")
    except (common.FetchError, ValueError) as e:
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
# the Comptroller's record layout for the franchise-tax dataset (data.texas.gov 9cir-efmm)
TX_RIGHT_TO_TRANSACT = {"A": "active", "N": "forfeited", "D": "eligible for termination",
                        "I": "involuntarily ended", "U": "not established"}
# statuses that mean a state has suspended the entity's standing; the entity can usually cure them by filing
US_STATE_BAD_STATUS = re.compile(r"delinquent|noncompliant|forfeit|revoked|suspended|eligible for termination|"
                                 r"involuntarily ended", re.I)


def us_state_flag(state, entity):
    """A `us_state_flag` when the entity's status shows it lost good standing in that state, else None."""
    status = entity.get("status") or ""
    if not US_STATE_BAD_STATUS.search(status):
        return None
    return {"type": "us_state_flag", "state": state, "name": entity.get("name"), "number": entity.get("number"),
            "status": status, "severity": "major" if re.search(r"forfeit|revoked|involuntarily", status, re.I) else "minor",
            "match_first": "the search returns every entity whose name starts with the query, so this flag says "
                           "nothing until the entity is matched to the company by address, state of formation and agent",
            "rule": "the entity lost good standing for missing annual reports, taxes or a registered agent; a forfeited "
                    "or revoked entity may not transact business in that state until it is reinstated. Confirm on the "
                    "state's own page before citing it",
            **({"page": entity["page"]} if entity.get("page") else {})}


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
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    searched = []
    for state, base, field in US_STATE_DATASETS:
        clauses = " or ".join(f"upper({field}) like '{n.upper().strip().replace(chr(39), chr(39) * 2)}%'" for n in names)
        url = base + "?" + urllib.parse.urlencode({"$where": clauses, "$limit": limit * (6 if state == "OR" else 1)})
        try:
            rows = json.loads(get(url))
        except (common.FetchError, ValueError) as e:
            yield {"type": "us_state_unavailable", "state": state, "error": str(e), "url": url}
            continue
        entities = oregon_entities(rows) if state == "OR" else [us_state_entity(state, r) for r in rows]
        for e in entities:
            yield {"type": "us_state_entity", "state": state, **{k: v for k, v in e.items() if v}, "url": url}
            flag = us_state_flag(state, e)
            if flag:
                yield {**flag, "url": url}
        searched.append({"state": state, "matches": len(entities), "url": url,
                         **({"truncated": True} if len(rows) >= limit * (6 if state == "OR" else 1) else {})})
    yield {"type": "us_states_summary", "query": names, "searched": searched,
           "note": "names starting with the query; match each entity to the company by address, state of formation, "
                   "and agent before using it. NY, TX and OR list active entities only, so a missing entity there is "
                   "inactive or never registered. Other states' registers are web pages: search them by hand"}


# ------------------------------------------------------- US federal money ----

USASPENDING = "https://api.usaspending.gov/api/v2"
USA_EARLIEST = "2007-10-01"  # the award search covers nothing earlier
USA_LOANS_FROM = "2020-04-01"  # loans are searched back to the PPP's start whatever the window
USA_MAX_PAGES = 4  # pages read per name and group while every row is another recipient
USA_IDV_CODES = ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]
_USA_FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "Awarding Agency", "Awarding Sub Agency", "Description",
               "generated_internal_id", "recipient_id"]
_USA_SPENDING = ["Start Date", "End Date", "Award Amount", "Total Outlays"]
# (group, award type codes, extra fields, sort field); the API takes one group per search
USA_AWARD_GROUPS = [
    ("contracts", ["A", "B", "C", "D"], _USA_SPENDING, "Award Amount"),
    ("grants", ["02", "03", "04", "05"], _USA_SPENDING, "Award Amount"),
    ("direct payments", ["06", "10"], _USA_SPENDING, "Award Amount"),
    ("other assistance", ["09", "11"], _USA_SPENDING, "Award Amount"),
    ("loans", ["07", "08"], ["Loan Value", "Subsidy Cost", "Issued Date"], "Loan Value"),
]


def post_json(url, body, retries=2):
    """POST `body` as JSON and return the parsed reply, retrying like fetch_bytes."""
    data = json.dumps(body).encode()
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers={
            "User-Agent": "muckraker", "Content-Type": "application/json", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                return json.loads(common.read_body(r, r.headers.get("Content-Encoding") == "gzip"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise common.FetchError(f"HTTP {e.code} for {url}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise common.FetchError(f"{type(e).__name__} for {url}") from e


def usaspending_report(names, since=None, poster=None, today=None, limit=25):
    """Federal contracts, grants, loans and other awards to recipients named like the company,
    from USAspending.gov's open API, with yearly obligations for the recipients found."""
    post = poster or (lambda path, body: post_json(USASPENDING + path, body))
    today = today or dt.date.today()
    since = max(since or (today - dt.timedelta(days=5 * 365)).isoformat(), USA_EARLIEST)
    period = [{"start_date": since, "end_date": today.isoformat()}]
    seen, recipients, other_names, truncated, agencies = set(), {}, set(), [], {}
    for name in names:
        for group, codes, extra, sort in USA_AWARD_GROUPS:
            window = ([{"start_date": min(since, USA_LOANS_FROM), "end_date": today.isoformat()}]
                      if group == "loans" else period)
            rows, page, more = [], 0, False
            # the search matches inside words ("Azimo" finds AZIMOV), so a page of rejects can hide the company's
            # awards on the next page: read on while every row so far is another recipient
            while page < USA_MAX_PAGES:
                page += 1
                body = {"filters": {"recipient_search_text": [name], "award_type_codes": codes, "time_period": window},
                        "fields": _USA_FIELDS + extra, "sort": sort, "order": "desc", "limit": limit, "page": page}
                try:
                    reply = post("/search/spending_by_award/", body)
                except (common.FetchError, ValueError) as e:
                    yield {"type": "usa_unavailable", "query": name, "group": group, "error": str(e)}
                    break
                rows += reply.get("results") or []
                more = bool((reply.get("page_metadata") or {}).get("hasNext"))
                if not more or any(_name_match(n, r.get("Recipient Name") or "") for r in rows for n in names):
                    break
            if more:
                matched_any = any(_name_match(n, r.get("Recipient Name") or "") for r in rows for n in names)
                truncated.append({"query": name, "group": group, "pages_read": page,
                                  **({} if matched_any else {"all_other_recipients": True})})
            for row in rows:
                recipient = row.get("Recipient Name") or ""
                if not any(_name_match(n, recipient) for n in names):
                    other_names.add(recipient)  # the search also matches inside words ("Pleo" finds PeopleOne)
                    continue
                gid = row.get("generated_internal_id")
                if gid in seen:
                    continue
                seen.add(gid)
                amount = row.get("Loan Value") if group == "loans" else row.get("Award Amount")
                uei = row.get("Recipient UEI")
                rec = recipients.setdefault(uei or recipient, {
                    "name": recipient, "uei": uei, "awards": 0, "amount": 0.0,
                    **({"page": f"https://www.usaspending.gov/recipient/{row['recipient_id']}/latest"}
                       if row.get("recipient_id") else {})})
                rec["awards"] += 1
                rec["amount"] += amount or 0
                agency = row.get("Awarding Agency")
                if agency and group != "loans":
                    agencies[agency] = agencies.get(agency, 0) + (amount or 0)
                yield {"type": "usa_award", "group": group, "award_id": row.get("Award ID"), "recipient": recipient,
                       "uei": uei, "amount": amount,
                       **({"subsidy_cost": row.get("Subsidy Cost"), "issued": row.get("Issued Date")} if group == "loans"
                          else {"outlays": row.get("Total Outlays"), "start": row.get("Start Date"),
                                "end": row.get("End Date")}),
                       "agency": agency, "sub_agency": row.get("Awarding Sub Agency"),
                       "description": (row.get("Description") or "")[:300] or None,
                       "url": f"https://www.usaspending.gov/award/{gid}"}
    # contract vehicles (IDIQs, GWACs) carry no money themselves but show what the company can bid on
    vehicles = []
    for name in names:
        body = {"filters": {"recipient_search_text": [name], "award_type_codes": USA_IDV_CODES, "time_period": period},
                "fields": ["Award ID", "Recipient Name", "Start Date", "Awarding Agency", "Awarding Sub Agency",
                           "Description", "generated_internal_id"], "sort": "Start Date", "order": "desc",
                "limit": limit, "page": 1}
        try:
            reply = post("/search/spending_by_award/", body)
        except (common.FetchError, ValueError) as e:
            yield {"type": "usa_unavailable", "query": name, "group": "contract vehicles", "error": str(e)}
            continue
        for row in reply.get("results") or []:
            gid = row.get("generated_internal_id")
            if gid in seen or not any(_name_match(n, row.get("Recipient Name") or "") for n in names):
                continue
            seen.add(gid)
            vehicles.append({"award_id": row.get("Award ID"), "start": row.get("Start Date"),
                             "agency": row.get("Awarding Sub Agency") or row.get("Awarding Agency"),
                             "description": (row.get("Description") or "")[:200] or None,
                             "url": f"https://www.usaspending.gov/award/{gid}"})
    if vehicles:
        yield {"type": "usa_vehicles", "vehicles": vehicles,
               "note": "indefinite-delivery contracts the company holds a place on; money comes only through task "
                       "orders, which are listed as contracts"}
    ueis = sorted(r["uei"] for r in recipients.values() if r["uei"])
    years = []
    if ueis:
        try:
            reply = post("/search/spending_over_time/", {"group": "fiscal_year",
                                                         "filters": {"recipient_search_text": ueis, "time_period": period}})
            for y in reply.get("results") or []:
                row = {"fiscal_year": int(y["time_period"]["fiscal_year"]), "obligations": y.get("aggregated_amount"),
                       **{k: y.get(f"{k.capitalize()}_Obligations") for k in ("contract", "grant", "loan", "direct", "other")}}
                years.append(row)
                yield {"type": "usa_year", "ueis": ueis, **row}
                if (row["obligations"] or 0) < 0:
                    yield {"type": "usa_flag", "severity": "review", "fiscal_year": row["fiscal_year"],
                           "obligations": row["obligations"],
                           "detail": "negative obligations: an agency took back money it had committed (a closeout, "
                                     "a reduced scope, or a termination); open the largest award's transaction history "
                                     "on its page to see which"}
        except (common.FetchError, ValueError, KeyError, TypeError) as e:
            yield {"type": "usa_unavailable", "query": ueis, "group": "yearly totals", "error": str(e)}
    total = sum(agencies.values())
    yield {"type": "usa_summary", "query": names, "since": since, "recipients": list(recipients.values()),
           "agencies": [{"agency": a, "share": round(v / total, 3)} for a, v in
                        sorted(agencies.items(), key=lambda kv: -kv[1])] if total > 0 else [],
           **({"truncated": truncated} if truncated else {}),
           **({"other_recipients": sorted(other_names)[:20]} if other_names else {}),
           "loans_since": min(since, USA_LOANS_FROM),
           **({"no_uei": [r["name"] for r in recipients.values() if not r["uei"]]}
              if any(not r["uei"] for r in recipients.values()) else {}),
           "note": "award amounts are each award's lifetime total and `usa_year` obligations are what agencies committed "
                   "in each US fiscal year (October to September), not cash paid. Recipients are matched by name: check "
                   "each UEI's page (address, parent) before counting it as the company. `agencies` shares cover the "
                   "awards listed here, not loans; a truncated group lists only its largest awards. SBA loans, including "
                   "PPP and disaster loans, are loans, not income; a forgiven PPP loan is still listed at its value. "
                   "Recipients in `no_uei` (often a PPP borrower) are matched by name only and left out of `usa_year`. "
                   "USAspending leaves out Other Transaction agreements (DIU and other OT deals, often a defence "
                   "startup's largest) and some SBIR awards: check SBIR.gov's firm portfolio and the company's own "
                   "contract announcements for those"}
