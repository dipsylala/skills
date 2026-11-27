"""Spain: a company's acts in BORME."""

import datetime as dt
import html
import json
import re
import time
from .. import common, documents, uk


# ---------------------------------------------------------------- Spain ----

BORME_SUMARIO = "https://www.boe.es/datosabiertos/api/borme/sumario/"
# BOE's own search paths (/buscar/anborme.php) and XML (/diario_borme/xml.php) are barred by robots.txt,
# so companies are found by reading the daily per-province PDFs of section A
_BORME_HEADER_RE = re.compile(r"\n*BOLET[ÍI]N OFICIAL DEL REGISTRO MERCANTIL\nN[úu]m\. \d+\n[^\n]*\nP[áa]g\. \d+\n"
                              r"cve: [^\n]+\nVerificable en https://www\.boe\.es\n*")
_BORME_ENTRY_RE = re.compile(r"(?ms)^(\d{1,7}) - (.+?)\.?\s*$\n(.*?)(?=^\d{1,7} - |\Z)")
BORME_ACTS = ["Constitución", "Nombramientos", "Revocaciones", "Ceses/Dimisiones", "Reelecciones",
              "Ampliación de capital", "Reducción de capital", "Modificaciones estatutarias",
              "Cambio de domicilio social", "Cambio de objeto social", "Ampliacion del objeto social",
              "Cambio de denominación social", "Declaración de unipersonalidad", "Sociedad unipersonal",
              "Pérdida del caracter de unipersonalidad", "Disolución", "Extinción", "Fusión por absorción",
              "Fusión por unión", "Escisión parcial", "Escisión total", "Transformación de sociedad",
              "Situación concursal", "Cierre provisional hoja registral", "Reapertura hoja registral",
              "Desembolso de dividendos pasivos", "Primera inscripción", "Otros conceptos", "Datos registrales"]
# the text layer drops some spaces at line ends ("Datosregistrales"), so headings match with or without them
_BORME_ACT_RE = re.compile(r"(?:^|(?<=\.)|(?<=\.\s))(" + "|".join(re.escape(a).replace(r"\ ", r"\s*") for a in BORME_ACTS)
                           + r")\s*[.:]\s*")
_BORME_CANON = {re.sub(r"\s", "", a): a for a in BORME_ACTS}
_BORME_ROLE_RE = re.compile(r"(?:^|\.\s*)([A-ZÀ-Ý][A-ZÀ-Ý0-9 .\-/]{1,30}?):\s*")
_BORME_MAJOR = {"Disolución": "dissolution", "Extinción": "extinction", "Situación concursal": "insolvency proceedings",
                "Cierre provisional hoja registral": "register sheet provisionally closed"}
_ES_FORMS_RE = re.compile(r"\b(S\.?L\.?U?|S\.?A\.?U?|S\.?L\.?L|S\.?L\.?N\.?E|SOCIEDAD LIMITADA|SOCIEDAD ANONIMA|"
                          r"SOCIEDAD AN[ÓO]NIMA)\.?\s*$")


def _es_key(name):
    """A company or person name reduced for matching: upper case, no legal form, no "(EN LIQUIDACION)",
    no spaces or punctuation (the PDF text layer sometimes runs two words together)."""
    n = re.sub(r"\(.*?\)", "", (name or "").upper()).strip(" .,")
    n = _ES_FORMS_RE.sub("", n.replace(",", " ")).strip(" .,")
    return re.sub(r"[^0-9A-ZÀ-Ý]", "", n)


def _es_euros(s):
    return float(s.replace(".", "").replace(",", ".")) if s else None


def borme_entries(text):
    """Each company entry in a BORME section A PDF's text: (entry number, name, body as one line)."""
    text = _BORME_HEADER_RE.sub("\n", text)
    for m in _BORME_ENTRY_RE.finditer(text):
        yield m.group(1), m.group(2).strip(), re.sub(r"\s*\n\s*", " ", m.group(3)).strip()


def borme_parse(body):
    """The acts in one entry's text: headings, officer appointments and removals, capital changes,
    the registry data (sheet, inscription number and date)."""
    marks = list(_BORME_ACT_RE.finditer(body))
    acts, people, capital, registry = [], [], [], {}
    for i, m in enumerate(marks):
        act, seg = _BORME_CANON[re.sub(r"\s", "", m.group(1))], body[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(body)].strip()
        acts.append(act)
        if act in ("Nombramientos", "Revocaciones", "Ceses/Dimisiones", "Reelecciones"):
            roles = list(_BORME_ROLE_RE.finditer(seg))
            for j, r in enumerate(roles):
                names = seg[r.end(): roles[j + 1].start() if j + 1 < len(roles) else len(seg)].strip(" .")
                for n in filter(None, (x.strip(" .") for x in names.split(";"))):
                    people.append({"act": act, "role": r.group(1).strip(), "name": n})
        elif act == "Ampliación de capital":
            for c in re.finditer(r"Capital:\s*([\d.,]+)\s*Euros\.?\s*Resultante\s*Suscrito:\s*([\d.,]+)", seg):
                capital.append({"change": _es_euros(c.group(1)), "resulting": _es_euros(c.group(2))})
        elif act == "Reducción de capital":
            for c in re.finditer(r"Importe\s*reducci[óo]n:\s*([\d.,]+)\s*Euros\.?\s*Resultante\s*Suscrito:\s*([\d.,]+)", seg):
                capital.append({"change": -_es_euros(c.group(1)), "resulting": _es_euros(c.group(2))})
        elif act == "Constitución":
            c = re.search(r"Capital:\s*([\d.,]+)\s*Euros", seg)
            if c:
                capital.append({"change": _es_euros(c.group(1)), "resulting": _es_euros(c.group(1))})
            d = re.search(r"Domicilio:\s*(.+?)(?:\.\s*Capital|$)", seg)
            if d:
                registry["address"] = d.group(1).strip()
        elif act == "Cambio de domicilio social":
            registry["address"] = seg.strip(" .")
        elif act == "Datos registrales":
            sheet = re.search(r"H\s*([A-Z]{1,2})\s*(\d+)", seg)
            ia = re.search(r"I/A\s*(\d+)\s*\(\s*(\d{1,2})\.(\d{2})\.(\d{2})\s*\)", seg)
            if sheet:
                registry["sheet"] = f"{sheet.group(1)} {sheet.group(2)}"
            if ia:
                registry["inscription"] = int(ia.group(1))
                registry["inscribed"] = f"20{ia.group(4)}-{ia.group(3)}-{int(ia.group(2)):02d}"
    return acts, people, capital, registry


def _borme_day_pdfs(day, province, get):
    """(section A PDF URL for the province, section C items) from one day's BORME summary, or None
    when no BORME was published that day."""
    url = BORME_SUMARIO + day.strftime("%Y%m%d")
    try:
        data = json.loads(get(url, "application/json"))
    except common.FetchError as e:
        if "HTTP 404" in str(e):
            return None
        raise
    pdf, notices = None, []
    for diario in (data.get("data") or {}).get("sumario", {}).get("diario") or []:
        for sec in diario.get("seccion") or []:
            items = sec.get("item") or []
            for it in items if isinstance(items, list) else [items]:
                if sec.get("codigo") == "A" and str(it.get("identificador", "")).endswith(f"-{province}"):
                    pdf = (it.get("url_pdf") or {}).get("texto")
            for ap in sec.get("apartado") or []:
                items = ap.get("item") or []
                for it in items if isinstance(items, list) else [items]:
                    notices.append({"apartado": ap.get("nombre"), "title": it.get("titulo"),
                                    "url": (it.get("url_pdf") or {}).get("texto")})
    return pdf, notices


def empresia_borme_pdfs(url, get, max_pages=20):
    """BORME section A PDF links listed on an empresia.es company page and its event pages (a copy
    of BORME; its robots.txt allows it), used as the list of PDFs to read."""
    pdfs, page, pages = [], get(url), 0
    while page and pages < max_pages:
        pages += 1
        for u in re.findall(r"https?://www\.boe\.es/borme/dias/[^\"'<> ]+?/BORME-A-[^\"'<> ]+?\.pdf", page):
            if u not in pdfs:
                pdfs.append(u)
        nxt = re.search(r"/async/\?t=EventosEntidad[^\"'<> ]+", page)
        page = get("https://www.empresia.es" + html.unescape(nxt.group(0))) if nxt else None
    return pdfs


def es_report(name, pdfs=(), empresia=None, scan_from=None, scan_to=None, province="08", fetcher=None,
              pdf_reader=None, pause=0.3):
    """A Spanish company's acts in BORME section A (officers, capital, address, dissolution), from the
    PDFs given, the PDFs an empresia.es page links, or a scan of the daily summaries between two dates."""
    get = fetcher or (lambda u, accept=None: common.fetch_bytes(u, None, accept=accept))
    read = pdf_reader or (lambda raw: "\n\n".join(documents.pdf_text(raw)))
    key = _es_key(name)
    urls = list(pdfs)
    if empresia:
        urls += [u for u in empresia_borme_pdfs(empresia, lambda u: common.decode_body(get(u))) if u not in urls]
    if scan_from:
        day, end, days = uk._date(scan_from), uk._date(scan_to) if scan_to else dt.date.today(), 0
        while day <= end:
            found = _borme_day_pdfs(day, province, get)
            if found:
                days += 1
                pdf, notices = found
                if pdf and pdf not in urls:
                    urls.append(pdf)
                for n in notices:
                    if key and key in _es_key(n["title"]):
                        yield {"type": "es_notice", "date": day.isoformat(), **n,
                               "note": "a BORME section C announcement (liquidation balance, merger, capital "
                                       "reduction, meeting call): read it"}
                time.sleep(pause)
            day += dt.timedelta(days=1)
        yield {"type": "es_scan", "from": scan_from, "to": end.isoformat(), "borme_days": days, "province": province}
    entries, unread = [], []
    for url in urls:
        try:
            text = read(get(url))
        except (common.FetchError, ValueError) as e:
            unread.append(url)
            yield {"type": "es_unreadable", "url": url, "error": str(e)}
            continue
        cve = re.search(r"(BORME-A-\d{4}-\d+-\d+)", url)
        for number, entry_name, body in borme_entries(text):
            if _es_key(entry_name) != key:
                continue
            acts, people, capital, registry = borme_parse(body)
            entries.append({"type": "es_entry", "name": entry_name, "entry": number,
                            "cve": cve.group(1) if cve else None, **registry, "acts": acts,
                            **({"officers": people} if people else {}), **({"capital": capital} if capital else {}),
                            "quote": body[:300], "url": url})
    entries.sort(key=lambda e: (e.get("sheet") or "", e.get("inscription") or 0))
    yield from entries
    sheets = {}
    for e in entries:
        sheets.setdefault(e.get("sheet"), []).append(e)
    for sheet, items in sheets.items():
        board = {}
        for e in items:
            for p in e.get("officers") or []:
                k = (p["role"], re.sub(r"\W", "", p["name"]))
                if p["act"] in ("Nombramientos", "Reelecciones"):
                    board[k] = {"role": p["role"], "name": p["name"], "since": e.get("inscribed")}
                else:
                    board.pop(k, None)
            for act, what in _BORME_MAJOR.items():
                if act in e["acts"]:
                    yield {"type": "es_flag", "flag": what, "severity": "major", "sheet": sheet,
                           "inscribed": e.get("inscribed"), "quote": e["quote"][:200], "url": e["url"]}
        numbers = sorted({e["inscription"] for e in items if e.get("inscription")})
        missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)) if numbers else []
        if missing:
            yield {"type": "es_flag", "flag": "inscriptions missing", "severity": "minor", "sheet": sheet,
                   "missing": missing, "note": "the PDFs read skip these inscription numbers: the list of PDFs is "
                                               "incomplete, or those acts were published in another section"}
        caps = [c for e in items for c in e.get("capital") or []]
        yield {"type": "es_summary", "name": name, "sheet": sheet, "entries": len(items),
               "inscriptions": [numbers[0], numbers[-1]] if numbers else None,
               "capital": caps[-1]["resulting"] if caps else None,
               "current_officers": list(board.values()),
               "note": "acts as BORME publishes them: capital figures are nominal (no share premium), and the "
                       "current officers are worked out from the appointments and removals read, so they are only "
                       "complete when no inscription is missing. Names come from the PDF text layer, which sometimes "
                       "runs two words together"}
    if not entries:
        yield {"type": "es_summary", "name": name, "entries": 0, "pdfs_read": len(urls) - len(unread),
               "note": "no entry with this exact name (legal form ignored) in the PDFs read"}
