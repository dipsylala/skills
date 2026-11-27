"""Norway: Brønnøysund profile, officers, accounts and announcements."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .. import common
from . import fr


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
        cells = [common.text_of(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c]
        date = next((_no_date(c) for c in cells if _NO_DATE_RE.fullmatch(c)), None) or last
        kind = next((c for c in cells if not _NO_DATE_RE.fullmatch(c)), "")
        last = date
        out.append((date, kind, kid.group(1)))
    return out


def parse_no_notice(page):
    """Title and plain text of one kunngjøring page, from its heading to the
    register's signature line."""
    text = common.text_of(re.sub(r"<(script|style)\b.*?</\1\s*>", " ", page, flags=re.S | re.I))
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
    get = fetcher or (lambda u: common.fetch(u, None))
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
    except common.FetchError as err:
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
    except common.FetchError:
        pass

    roles_url = f"{url}/roller"
    try:
        roles = json.loads(get(roles_url))
    except common.FetchError as err:
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
    except common.FetchError:  # 404 when nothing is filed
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
    except common.FetchError as err:
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
        except common.FetchError as err:
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
        parts = [p.lower().translate(_QUOTE_CHARS) for p in (common.text_of(x) for x in re.split(r"<[^>]+>", quote)) if p]
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
        inner = fr._json_field(value) if depth < 3 and value[:1] in "{[" else None
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
            return common.text_of(" \n ".join(_json_strings(json.loads(body))))
        except ValueError:
            pass
    return common.text_of(body)


def quote_check(url, quote, user_agent, context_chars):
    try:
        if url.startswith(("http://", "https://")):
            body = common.fetch(url, user_agent)
        else:  # a saved extract, such as mr.py lu --save
            with open(url, encoding="utf-8", errors="replace") as f:
                body = f.read()
        page = searchable_text(body).lower()
    except common.FetchError as e:
        common.emit({"type": "quote_check", "url": url, "quote": quote, "found": None, "unreachable": str(e),
              "note": "the page could not be fetched; check the quote in a browser"})
        return
    pos, span = find_quote(page, quote)
    record = {"type": "quote_check", "url": url, "quote": quote, "found": pos >= 0}
    if pos >= 0:
        record["context"] = page[max(0, pos - context_chars): pos + span + context_chars]
    common.emit(record)
