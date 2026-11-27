"""UK Companies House: profile, officers, PSCs, charges, filings, iXBRL accounts, officers' other companies."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from . import common, sec


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
            raise common.FetchError("Companies House commands need COMPANIES_HOUSE_API_KEY")
        import base64
        self.auth = "Basic " + base64.b64encode(f"{key}:".encode()).decode() if key else None
        self._fetch = fetcher or (lambda url, accept=None: common.fetch(url, None, auth=self.auth, accept=accept))

    def get(self, path):
        """API JSON, or None for 404."""
        try:
            return json.loads(self._fetch(CH_API + path))
        except common.FetchError as e:
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


CH_CLOSED_STATUSES = {"dissolved", "converted-closed", "closed", "removed"}


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
    # a dissolved or closed company owes no filings, though its last profile can still say "overdue"
    closed = (p.get("company_status") or "") in CH_CLOSED_STATUSES or bool(p.get("date_of_cessation"))
    for field, what in (("accounts_overdue", "accounts overdue"), ("confirmation_overdue", "confirmation statement overdue")):
        if (acc if field == "accounts_overdue" else cs).get("overdue") and not closed:
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
    for cid, body in sec._CONTEXT_RE.findall(doc):
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
    for fact in sec.iter_facts(doc):
        kind, attrs, raw = fact.kind, fact.attrs, fact.raw
        name = (sec._attr(attrs, "name") or "").split(":")[-1]
        cid = sec._attr(attrs, "contextRef")
        if kind == "nonNumeric":
            for field, names in UK_TEXT.items():
                if name in names and field not in texts:
                    texts[field] = common.text_of(raw)
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
        value = sec._number(attrs, raw)
        if value is None:
            continue
        # UK filers often get the sign attribute wrong (Veracode Ltd tags a printed
        # inflow of 613,886 as negative and a printed (92,485) as positive), so the
        # printed sign decides, and a disagreement is reported
        tagged_neg = sec._attr(attrs, "sign") == "-" and value != 0
        shown_neg = sec.printed_negative(doc, fact)
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
    text = common.text_of(re.sub(r"<(script|style|ix:header)\b.*?</\1>", " ", doc, flags=re.S | re.I))
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
        except common.FetchError as e:
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
