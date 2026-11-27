"""France: register profile, officers, and BODACC notices."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .. import common, uk


# --------------------------------------------------------------- France ----

FR_SEARCH = "https://recherche-entreprises.api.gouv.fr/search?q="
BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
FR_ACCOUNTS_DUE_MONTHS = 8  # filed within 7 months of the year end, plus about a month for BODACC to publish
MAX_BODACC_NOTICES = 1000


def _json_field(value):
    """BODACC stores some fields as JSON text inside the JSON record."""
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def bodacc_url(siren, offset=0):
    query = urllib.parse.urlencode({"where": f'registre like "{siren}"', "order_by": "dateparution",
                                    "limit": 100, "offset": offset})
    return f"{BODACC}?{query}"


def fr_notice_records(notice, capital_before):
    """Typed records for one BODACC notice; returns (records, capital after it)."""
    url = notice.get("url_complete") or f"https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:{notice.get('id')}"
    base = {"date": notice.get("dateparution"), "url": url}
    family = notice.get("familleavis")
    person = _json_field(notice.get("listepersonnes")).get("personne") or {}
    if isinstance(person, list):
        person = person[0] if person else {}
    capital = (person.get("capital") or {}).get("montantCapital")
    capital = float(capital) if capital and re.fullmatch(r"\d+(\.\d+)?", capital) else None
    records = []
    if family == "dpc":
        depot = _json_field(notice.get("depot"))
        descriptif = depot.get("descriptif") or ""
        records.append({"type": "fr_accounts_filed", "year_end": depot.get("dateCloture"),
                        "kind": depot.get("typeDepot"), "confidential": "L. 232-25" in descriptif or "L.232-25" in descriptif,
                        "quote": descriptif or depot.get("typeDepot"), **base})
    elif family == "collective":
        j = _json_field(notice.get("jugement"))
        records.append({"type": "fr_insolvency", "nature": j.get("nature"), "judgment_date": j.get("date"),
                        "court": notice.get("tribunal"), "quote": (j.get("complementJugement") or j.get("nature") or "")[:400],
                        **base})
    elif family == "radiation":
        records.append({"type": "fr_struck_off", "quote": str(_json_field(notice.get("radiationaurcs")))[:300], **base})
    elif family == "creation":
        acte = _json_field(notice.get("acte"))
        records.append({"type": "fr_registered", "registered": acte.get("dateImmatriculation"),
                        "activity_start": acte.get("dateCommencementActivite"), **base})
    elif family == "modification":
        descriptif = _json_field(notice.get("modificationsgenerales")).get("descriptif") or ""
        if "capital" in descriptif:
            direction = "increase" if "augmentation" in descriptif else "reduction" if "diminution" in descriptif else None
            records.append({"type": "fr_capital", "direction": direction, "capital_eur": capital,
                            "previous_capital_eur": capital_before, "quote": descriptif, **base})
        if person.get("administration"):
            records.append({"type": "fr_officer_change", "quote": person["administration"], **base})
        if not records:
            records.append({"type": "fr_notice", "kind": notice.get("familleavis_lib"), "quote": descriptif, **base})
    else:
        records.append({"type": "fr_notice", "kind": notice.get("familleavis_lib"), **base})
    # other notices repeat the capital as it stood when filed, which can be stale
    changed = capital is not None and any(r["type"] in ("fr_capital", "fr_registered") for r in records)
    return records, capital if changed else capital_before


def fr_filing_gaps(year_ends, created, today, closed=None):
    """Financial years whose accounts should have had a BODACC filing notice by
    `today` but have none. BODACC publishes about two million filing notices a
    year, confidential filings included, so a missing year is a signal."""
    end = closed or today
    if not year_ends:
        if created and uk._add_months(created, 24 + FR_ACCOUNTS_DUE_MONTHS) <= end:
            return [{"type": "fr_flag", "rule": "no accounts-filing notice since the company was registered",
                     "registered": created.isoformat()}]
        return []
    gaps, ye = [], min(year_ends)
    while uk._add_months(ye, FR_ACCOUNTS_DUE_MONTHS) <= end:
        if ye not in year_ends:
            gaps.append({"type": "fr_flag", "rule": "no accounts-filing notice for this financial year",
                         "year_end": ye.isoformat(), "due_by": uk._add_months(ye, FR_ACCOUNTS_DUE_MONTHS).isoformat()})
        ye = uk._add_months(ye, 12)
    return gaps


def fr_report(query, fetcher=None, today=None):
    """French company: register profile and officers, then its BODACC notices as
    typed records, with a flag for each financial year missing an accounts notice."""
    get = fetcher or (lambda u: common.fetch(u, None))
    today = today or dt.date.today()
    siren = re.sub(r"\s", "", query)
    search_url = FR_SEARCH + urllib.parse.quote(siren if re.fullmatch(r"\d{9}", siren) else query)
    results = json.loads(get(search_url)).get("results") or []
    if not re.fullmatch(r"\d{9}", siren):
        for r in results[:10]:
            yield {"type": "fr_candidate", "siren": r.get("siren"), "name": r.get("nom_complet"),
                   "city": (r.get("siege") or {}).get("libelle_commune"), "created": r.get("date_creation"),
                   "status": r.get("etat_administratif")}
        yield {"type": "fr_note", "note": "run mr.py fr <SIREN> with the right company's SIREN"}
        return
    company = next((r for r in results if r.get("siren") == siren), None)
    created = closed = None
    if company:
        seat = company.get("siege") or {}
        created, closed = uk._date(company.get("date_creation")), uk._date(company.get("date_fermeture"))
        yield {"type": "fr_company", "siren": siren, "name": company.get("nom_complet"),
               "status": {"A": "active", "C": "closed"}.get(company.get("etat_administratif"), company.get("etat_administratif")),
               "created": company.get("date_creation"), "closed": company.get("date_fermeture"),
               "legal_form_code": company.get("nature_juridique"), "activity": company.get("activite_principale"),
               "head_office": seat.get("adresse"), "headcount_band": company.get("tranche_effectif_salarie"),
               "headcount_year": company.get("annee_tranche_effectif_salarie"),
               "category": company.get("categorie_entreprise"), "url": search_url,
               "page": f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"}
        for d in company.get("dirigeants") or []:
            name = d.get("denomination") or " ".join(x for x in (d.get("prenoms"), d.get("nom")) if x)
            yield {"type": "fr_officer", "name": name, "role": d.get("qualite"), "born": d.get("date_de_naissance"),
                   "siren": d.get("siren"), "url": search_url}
        finances = company.get("finances")
        if finances:
            for year, figures in sorted(finances.items()):
                yield {"type": "fr_finances", "year": year, "revenue_eur": figures.get("ca"),
                       "net_income_eur": figures.get("resultat_net"), "url": search_url}
        else:
            yield {"type": "fr_finances", "published": False, "url": search_url,
                   "note": "the register publishes no figures: the accounts were filed with a confidentiality "
                           "declaration (art. L. 232-25) or not filed; the fr_accounts_filed records show which"}
    else:
        yield {"type": "fr_note", "note": f"the register search returned no company with SIREN {siren}", "url": search_url}
    notices, offset = [], 0
    while offset < MAX_BODACC_NOTICES:
        page = json.loads(get(bodacc_url(siren, offset)))
        batch = page.get("results") or []
        notices += batch
        offset += len(batch)
        if not batch or offset >= (page.get("total_count") or 0):
            break
    capital, year_ends, counts = None, set(), {}
    for n in notices:
        records, capital = fr_notice_records(n, capital)
        for r in records:
            counts[r["type"]] = counts.get(r["type"], 0) + 1
            if r["type"] == "fr_accounts_filed" and r.get("year_end"):
                year_ends.add(uk._date(r["year_end"]))
            yield r
    for r in fr_filing_gaps(year_ends, created, today, closed):
        counts["fr_flag"] = counts.get("fr_flag", 0) + 1
        yield {**r, "url": bodacc_url(siren)}
    yield {"type": "fr_summary", "siren": siren, "bodacc_notices": len(notices), "bodacc_url": bodacc_url(siren),
           "counts": counts, "truncated": len(notices) >= MAX_BODACC_NOTICES}
