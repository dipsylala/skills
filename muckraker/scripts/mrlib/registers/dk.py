"""Denmark: annual reports from the Business Authority's open index and XBRL."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .. import common, gleif, sec, uk
from . import no


# --------------------------------------------------------------- Denmark ----

# Explicitly http, as documented at https://datacvr.virk.dk/artikel/system-til-system-adgang-til-regnskabsdata:
# neither distribution.virk.dk nor regnskaber.virk.dk answers https
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
            self.facts.append((kind, attrs, re.sub(r"\s+", " ", common._INVISIBLE_RE.sub("", "".join(parts))).strip()))

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
        for cid, body in sec._CONTEXT_RE.findall(doc):
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
        text = common.text_of("".join(el.itertext()))
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
    month_end = period_end == no._add_months_end(period_end, 0)
    due = no._add_months_end(period_end, months) if month_end else uk._add_months(period_end, months)
    while due.weekday() >= 5:
        due += dt.timedelta(days=1)
    return due, rule


def dk_candidates(name, fetcher=None):
    """Danish companies with an LEI matching the name, from GLEIF: the filings index has no names."""
    found = 0
    for r in gleif.gleif_search(name, 50, fetcher):
        if r["type"] == "gleif_candidate" and (r.get("jurisdiction") or "").startswith("DK"):
            found += 1
            yield {"type": "dk_candidate", "cvr": r.get("registered_as"), "name": r.get("legal_name"),
                   "lei": r.get("lei"), "status": r.get("entity_status"), "url": r.get("url")}
    yield {"type": "dk_note", "note": ("run mr.py dk <CVR> with the right company's number" if found else
                                       "no Danish LEI record matches; find the CVR number on datacvr.virk.dk in a browser"),
           "search": "https://datacvr.virk.dk"}


DK_DOC_HOST = "regnskaber.virk.dk"


def _dk_doc(docs, kind, mime):
    """The first document of this type, only when it is on the Business Authority's document
    host: the index and documents are served over http only (no https on either host), so a
    link to anywhere else is not followed."""
    for d in docs:
        u = d.get("dokumentUrl") or ""
        p = urllib.parse.urlparse(u)
        if (d.get("dokumentType") == kind and (d.get("dokumentMimeType") or "").endswith(mime)
                and p.scheme in ("http", "https") and p.hostname == DK_DOC_HOST):
            return u
    return None


def dk_report(query, years=3, fetcher=None, today=None):
    """Danish company from the Business Authority's open filings index and the XBRL of
    its annual reports: each filing with its publication date against the ÅRL § 138
    deadline, and figures, officers and auditor, and notes from the latest `years`
    reports, with flags for late or missing accounts, negative equity, going-concern
    notes, and auditor remarks. Every record from the index or the reports carries
    `transport`: both hosts serve plain http only, so what comes back is unauthenticated."""
    cvr = re.sub(r"\D", "", query) if re.fullmatch(r"\s*(?:DK)?[\d\s]{8,14}", query, re.I) else ""
    if len(cvr) != 8:
        yield from dk_candidates(query, fetcher)  # GLEIF, over https
        return
    for r in _dk_filings_report(cvr, years, fetcher, today):
        yield {**r, "transport": DK_TRANSPORT}


DK_TRANSPORT = ("unauthenticated http (the Business Authority serves no https): confirm a figure or flag "
                "on datacvr.virk.dk or in the filed report before relying on it")


def _dk_filings_report(cvr, years, fetcher, today):
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    today = today or dt.date.today()
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
                    fig, head, notes, people, currency = dk_parse_report(common.decode_body(get(src)), first["start"], end)
                except (common.FetchError, ValueError, ET.ParseError) as e:
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
        due, rule = dk_deadline(uk._date(end), header.get("reporting_class"))
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
        published = uk._date(first["published"])
        if published and published > due:
            recent = uk._date(end) >= recent_cut
            flags += 1
            yield {"type": "dk_flag", "flag": "late accounts",
                   "severity": "major" if recent and (published - due).days > DK_LATE_GRACE_DAYS else "minor",
                   "period_end": end, "published": first["published"], "due": due.isoformat(),
                   "days_late": (published - due).days, "recent": recent, "rule": rule,
                   "note": "the publication date; the Business Authority may have received the report a few days earlier",
                   "url": url}
    for prev, nxt in zip(ends, ends[1:]):
        start = uk._date(by_end[nxt][0]["start"])
        if start and start > uk._date(prev) + dt.timedelta(days=1):
            flags += 1
            yield {"type": "dk_flag", "flag": "gap between filed periods", "severity": "minor", "after": prev,
                   "next_start": start.isoformat(), "url": url}
    next_end = no._add_months_end(uk._date(ends[-1]), 12) if uk._date(ends[-1]) == no._add_months_end(uk._date(ends[-1]), 0) \
        else uk._add_months(uk._date(ends[-1]), 12)
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
        recent = uk._date(p["end"]) >= recent_cut
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
